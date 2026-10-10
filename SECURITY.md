# XKF5 AI — Security Architecture & Threat Self-Assessment

## Executive Overview
XKF5 AI enforces strict separation between **LLM Reasoning (Unstrusted)** and **Financial State Execution (Trusted Engine)**. The application implements deterministic policy guards to eliminate risk vectors associated with AI prompt injections, unauthorised fund transfers, and state corruption.

---

## Authorization & Action Hierarchy

| Action Level | Description | Execution Authority | LLM Scope |
|---|---|---|---|
| **Level 0 (Read-Only)** | Snapshots, balances, rate checks | Engine (`engine.py`) | Allowed |
| **Level 1 (Drafting)** | Creating `PENDING_AUTH` proposals | Engine (`engine.py`) | Limited to proposal creation |
| **Level 2 (State Mutation)** | Balance deductions, fund execution | Engine (`engine.py`) | **COMPLETELY EXCLUDED** |

---

## Key Security Mitigation Controls

### 1. LLM Isolation Boundary
* **Tool Manifest Scope**: Execution functions (`execute_proposal`, `authorize_proposal`) are intentionally omitted from the LLM tool definition.
* **Deterministic Fallback**: The LLM can only output standard text and call `create_proposal`. Final approval requires an out-of-band user UI click sending a direct HTTP POST payload to `/api/authorize` and `/api/execute`.

### 2. Double-Spending & Replay Protection
* Every transaction proposal generates a unique UUID `proposal_id`.
* The engine checks `proposal.status == "AUTHORIZED"` before allowing state mutations.
* Once executed, the state locks to `EXECUTED`. Subsequent execution attempts are immediately rejected with HTTP 400.

### 3. Input Validation & Schema Integrity
* All endpoints leverage Pydantic models with strict mathematical boundaries (`amount_myr > 0`).
* Negative amounts, string injections, and out-of-bound numerical payloads are caught at the ASGI gateway layer before hitting business logic.

### 4. Auditability & Non-Repudiation
* Every proposal, authorization choice, execution, and policy block appends a structured record to the engine's append-only in-memory audit trail (`/api/audit`).

---

## Running the Security Verification Suite

Run automated security tests with `pytest`:

```cmd
python -m pytest tests/test_red_team.py