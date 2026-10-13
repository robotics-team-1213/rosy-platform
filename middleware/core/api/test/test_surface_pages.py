"""D-204 — 화면 페이지는 한 템플릿에서 문법·슬롯을 채우고, 자산은 정확한 허용목록으로만 나간다."""

from __future__ import annotations

import re
from types import SimpleNamespace

from fastapi.testclient import TestClient

from core_api_web.api.app import create_app


def _client() -> TestClient:
    return TestClient(create_app({}, SimpleNamespace()))


def test_shell_and_registered_panel_assets_are_served():
    client = _client()
    for path in ("shell/shell.js", "shell/mount.js", "shell/store.js", "shell/shell.css",
                 "panels/system/events.js", "panels/system/events.css", "client.js", "dom.js"):
        response = client.get(f"/assets/{path}")
        assert response.status_code == 200, path
        assert response.headers["cache-control"] == "no-cache"


def test_anything_outside_the_allowlist_is_404():
    client = _client()
    # A literal "./" segment is normalized away by any RFC 3986-conformant HTTP
    # client (including httpx/TestClient) before the request is even sent, so
    # it can never reach the server as a dot-segment — %2E is the only way to
    # exercise the server-side defense against it over this client.
    for path in ("panels/nope.js", "../api/app.py", "shell/surface.html", "panels.yaml", "AGENTS.md",
                 "panels/..%5Capi%5Capp.py", "panels/%2E/system/events.js", "panels//system/events.js"):
        assert client.get(f"/assets/{path}").status_code == 404, path


def test_the_legacy_dashboard_assets_still_work():
    assert _client().get("/dashboard/assets/app.js").status_code == 200


def test_each_surface_page_declares_its_grammar_and_slots():
    client = _client()
    device = client.get("/device")
    assert device.status_code == 200
    assert 'data-surface="device"' in device.text
    assert '<ui-shell grammar="procedure">' in device.text
    assert re.findall(r'data-slot="([a-z_]+)"', device.text) == ["main"]
    console = client.get("/console").text
    assert '<ui-shell grammar="spatial">' in console
    assert re.findall(r'data-slot="([a-z_]+)"', console) == ["banner", "sense", "observe", "act"]


def test_a_surface_page_keeps_the_dashboard_csp_and_has_no_inline_code():
    response = _client().get("/setup")
    csp = response.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "style-src 'self'" in csp
    assert "<script>" not in response.text
    assert "style=" not in response.text
    assert "{{" not in response.text


def test_the_one_estop_is_in_the_shell_topbar():
    text = _client().get("/device").text
    assert text.count('id="shell-estop"') == 1
    assert 'kind="irreversible"' in text
