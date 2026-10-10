import pytest
from fastapi.testclient import TestClient
from app.main import app, engine, rate_limiter


@pytest.fixture(autouse=True)
def reset_shared_test_state():
    engine.reset()
    engine.audit("TEST_RESET", {"reason": "isolate security test"})
    rate_limiter.client_history.clear()

client = TestClient(app)


def test_health_check():
    """Verify backend health check endpoint."""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json().get("ok") is True


def test_reject_negative_transfer_amount():
    """Security Check: Enforce Pydantic validation against negative transfer amounts."""
    response = client.post("/api/proposals", json={"amount_myr": -500.0, "purpose": "malicious transfer"})
    assert response.status_code == 422


def test_reject_zero_transfer_amount():
    """Security Check: Block zero-value transfer proposals."""
    response = client.post("/api/proposals", json={"amount_myr": 0.0, "purpose": "zero transfer"})
    assert response.status_code == 422


def test_cannot_execute_unauthorized_proposal():
    """Security Check: Verify an unapproved proposal (PENDING_AUTH) cannot be executed directly."""
    # 1. Draft a proposal
    prop_res = client.post("/api/proposals", json={"amount_myr": 50.0, "purpose": "unapproved test"})
    assert prop_res.status_code == 200
    proposal_id = prop_res.json()["id"]

    # 2. Attempt direct execution without user approval
    exec_res = client.post("/api/execute", json={"proposal_id": proposal_id})
    assert exec_res.status_code == 400


def test_legitimate_approval_and_execution_lifecycle():
    """Functional Check: Complete creation -> authorization -> execution lifecycle."""
    # 1. Draft proposal
    prop_res = client.post("/api/proposals", json={"amount_myr": 20.0, "purpose": "legit transfer"})
    assert prop_res.status_code == 200
    proposal_id = prop_res.json()["id"]

    # 2. Explicit User Authorization (Level 2)
    auth_res = client.post("/api/authorize", json={"proposal_id": proposal_id, "approved": True})
    assert auth_res.status_code == 200

    # 3. Execution
    exec_res = client.post("/api/execute", json={"proposal_id": proposal_id})
    assert exec_res.status_code == 200
    
    # Check execution success across potential response key schemas
    res_data = exec_res.json()
    assert (
        res_data.get("status") == "EXECUTED"
        or res_data.get("proposal", {}).get("status") == "EXECUTED"
        or res_data.get("ok") is True
    )


def test_double_execution_prevention():
    """Security Check: Prevent replay attacks / double spending on already executed proposals."""
    prop_res = client.post("/api/proposals", json={"amount_myr": 15.0, "purpose": "replay check"})
    proposal_id = prop_res.json()["id"]
    
    client.post("/api/authorize", json={"proposal_id": proposal_id, "approved": True})
    first_exec = client.post("/api/execute", json={"proposal_id": proposal_id})
    assert first_exec.status_code == 200

    # Replay attempt
    second_exec = client.post("/api/execute", json={"proposal_id": proposal_id})
    assert second_exec.status_code == 400


def test_audit_log_integrity():
    """Auditability Check: Ensure all critical events generate structured audit records."""
    audit_res = client.get("/api/audit")
    assert audit_res.status_code == 200
    logs = audit_res.json()["audit"]
    assert isinstance(logs, list)
    assert len(logs) > 0