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
    end = html.index("\\nasync function authorize", start)
    proposal_ui = html[start:end]

    assert "risk.status" in proposal_ui
    assert "risk.reasons" in proposal_ui
    assert "escapeFXHtml(reason)" in proposal_ui
    assert "Review required:" in proposal_ui
    assert "const canAuthorize=riskStatus==='LOW'||riskStatus==='REVIEW'" in proposal_ui
    assert "disabled title=" in proposal_ui
