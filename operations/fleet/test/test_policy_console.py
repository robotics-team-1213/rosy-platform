"""D-793 /console/policy: the page is served under the console CSP and its rules run in node."""
from pathlib import Path
import subprocess

from fastapi.testclient import TestClient

from fleet.server.app import create_app
from fleet.server.console import FleetConsole


def test_policy_model_rules_in_node():
    script = Path(__file__).parent / 'web/policy-model.test.mjs'
    result = subprocess.run(['node', '--test', str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_policy_page_and_assets_are_served_with_the_console_csp():
    client = TestClient(create_app(FleetConsole([], []), start_task_dispatcher=False))
    page = client.get('/console/policy')
    assert page.status_code == 200 and "script-src 'self'" in page.headers['content-security-policy']
    assert '학습 정책 승인' in page.text and 'style=' not in page.text and '<script>' not in page.text
    for asset in ('policy-page.js', 'policy-model.js', 'policy.css'):
        assert client.get(f'/console/assets/{asset}').status_code == 200


def test_api_reference_documents_every_governance_route():
    reference = (Path(__file__).resolve().parents[3] / 'docs/reference/ROSY API & Protocol Reference.md').read_text(
        encoding='utf-8-sig')
    section = reference.split('## 10.18 Learned-policy governance (D-793)')[1].split('# 11. 변경 이력')[0]
    for route in ('/policy-governance/workcells', '/policy/proposals', '/decision', '/policy/windows', '/approve',
                  '/close', '/policy/lease', '/policy/confirmations', '/sync-owner', '/resolve', '/policy/incidents',
                  '/clear'):
        assert route in section, route
