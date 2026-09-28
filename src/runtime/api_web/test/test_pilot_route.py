"""D-323 — /pilot 조종 표면과 자산 allowlist."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from core_api_web.api.app import create_app


def _client() -> TestClient:
    return TestClient(create_app({}, SimpleNamespace()))


def test_pilot_page_serves_html_with_csp():
    resp = _client().get("/pilot")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "default-src 'self'" in resp.headers["content-security-policy"]
    assert "Rosy Pilot" in resp.text


def test_pilot_assets_allowlist_blocks_the_rest():
    client = _client()
    assert client.get("/pilot/assets/styles.css").status_code == 200
    assert client.get("/pilot/assets/stick.js").status_code == 200
    assert client.get("/pilot/assets/link.js").status_code == 200
    assert client.get("/pilot/assets/drivers/registry.js").status_code == 200
    assert client.get("/pilot/assets/drivers/pinky_core.js").status_code == 200
    assert client.get("/pilot/assets/app.js").status_code == 200
    assert client.get("/pilot/assets/client.js").status_code == 200
    assert client.get("/pilot/assets/screens/connect.js").status_code == 200
    assert client.get("/pilot/assets/secrets.env").status_code == 404
    assert client.get("/pilot/assets/../api/app.py").status_code == 404
