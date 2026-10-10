from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest


def test_inline_frontend_javascript_has_valid_syntax(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not installed in this test environment.")

    html_path = Path(__file__).resolve().parents[1] / "static" / "index.html"
    html = html_path.read_text(encoding="utf-8")
    scripts = re.findall(r"<script\b[^>]*>(.*?)</script\s*>", html, re.IGNORECASE | re.DOTALL)
    inline_scripts = [script.strip() for script in scripts if script.strip()]
    assert inline_scripts, "The web interface should contain inline JavaScript."

    script_path = tmp_path / "xkf5-inline.js"
    script_path.write_text("\n;\n".join(inline_scripts), encoding="utf-8")
    result = subprocess.run(
        [node, "--check", str(script_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_proposal_card_discloses_risk_status_and_escaped_reasons():
    html_path = Path(__file__).resolve().parents[1] / "static" / "index.html"
    html = html_path.read_text(encoding="utf-8")
    start = html.index("function showProposal(p)")
    end = html.index("\nasync function authorize", start)
    proposal_ui = html[start:end]

    assert "risk.status" in proposal_ui
    assert "risk.reasons" in proposal_ui
    assert "escapeFXHtml(reason)" in proposal_ui
    assert "Review required:" in proposal_ui
    assert "const canAuthorize=(riskStatus==='LOW'||riskStatus==='REVIEW')&&Number.isFinite(rate)" in proposal_ui
    assert "disabled title=" in proposal_ui


def test_authorize_ui_checks_engine_status_before_execution_and_verifies_transaction():
    html = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text(encoding="utf-8")
    start = html.index("async function authorize(approved)")
    end = html.index("\nfunction setJourney", start)
    function = html[start:end]

    authorization_check = function.index("if(!r.ok || p.status!==expectedStatus)")
    execution_call = function.index("fetch('/api/execute'")
    execution_check = function.index("if(!r.ok || out.detail || !out.transaction")
    success_message = function.index("✓ VERIFIED:")
    assert authorization_check < execution_call
    assert execution_check < success_message
    assert "out.transaction.status!=='completed'" in function
    assert "latestProposal=null" in function


def test_proposal_card_discloses_quote_source_date_rate_and_expiry():
    html = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text(encoding="utf-8")
    start = html.index("function showProposal(p)")
    end = html.index("\nasync function authorize", start)
    proposal_ui = html[start:end]

    for field in ("quote.source", "quote.rate_date", "quote.expires_at", "p.rate"):
        assert field in proposal_ui
    assert "Fallback / non-live reference" in proposal_ui
    assert "Date.now()<Date.parse(expiryValue)" in proposal_ui
    assert "escapeFXHtml(quoteSource)" not in proposal_ui
    assert "escapeFXHtml(quoteDate)" not in proposal_ui


def test_chat_error_does_not_claim_transaction_state_without_confirmation():
    html = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text(encoding="utf-8")
    start = html.index("async function send()")
    end = html.index("\nfunction showProposal(p)", start)
    send_function = html[start:end]

    assert "I could not confirm the result." in send_function
    assert "Check Transactions and the audit log before retrying" in send_function
    assert "The response was not confirmed. Check account state and audit history" in send_function
    assert "No transaction was created. Please try again." not in send_function
    assert "The request failed before any state-changing operation." not in send_function
