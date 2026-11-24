"""Tests for Fleet -> Rosy World static and mDNS route resolution."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fleet.server.static_routes import CONSOLE_CSP, WEB_ROOT, install_static_routes
from fleet.server.world_entry import install_world_routes


def _client(monkeypatch, world_url=None, *, mdns_host=None, mdns_port=None, discover_fn=None):
    monkeypatch.delenv("ROSY_LEARNING_APPS_CONFIG", raising=False)
    for var, val in (
        ("ROSY_WORLD_URL", world_url),
        ("ROSY_WORLD_MDNS_HOST", mdns_host),
        ("ROSY_WORLD_MDNS_PORT", mdns_port),
    ):
        if val is None:
            monkeypatch.delenv(var, raising=False)
        else:
            monkeypatch.setenv(var, str(val))
    app = FastAPI()
    app.state.web_common = None
    if discover_fn is None:
        install_static_routes(app)
    else:
        install_world_routes(app, WEB_ROOT, CONSOLE_CSP, mdns_discover_fn=discover_fn)
    return TestClient(app)


def test_unconfigured_world_entry_returns_503_and_false_status(monkeypatch) -> None:
    http = _client(monkeypatch, None)
    status = http.get("/api/fleet/world-entry")
    assert status.status_code == 200
    assert status.json() == {
        "configured": False,
        "mode": "unconfigured",
        "mdns_host": None,
        "url": None,
        "reachable": False,
    }
    page = http.get("/console/world", follow_redirects=False)
    assert page.status_code == 503
    assert "ROSY_WORLD_URL" in page.text
    assert "/console?view=work" in page.text


@pytest.mark.parametrize(
    "origin",
    [
        "http://127.0.0.1:8140",
        "http://localhost:8140",
        "http://world:8140",
        "http://rosy-world.local:8140",
        "https://world.example:8443",
    ],
)
def test_configured_world_entry_redirects_to_factory_view(monkeypatch, origin) -> None:
    http = _client(monkeypatch, origin)
    status = http.get("/api/fleet/world-entry")
    assert status.status_code == 200
    assert status.json() == {
        "configured": True,
        "mode": "static",
        "mdns_host": None,
        "url": f"{origin}/?view=factory",
        "reachable": True,
    }
    resp = http.get("/console/world", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == f"{origin}/?view=factory"
    assert http.get("/console/world?target=https://evil.example", follow_redirects=False).status_code == 400


def test_mdns_world_entry_discovery_reachable_and_unreachable(monkeypatch) -> None:
    http_up = _client(
        monkeypatch,
        mdns_host="rosy-world.local",
        mdns_port=8140,
        discover_fn=lambda host, port, scheme: f"{scheme}://{host}:{port}",
    )
    status = http_up.get("/api/fleet/world-entry")
    assert status.status_code == 200
    assert status.json() == {
        "configured": True,
        "mode": "mdns",
        "mdns_host": "rosy-world.local",
        "url": "http://rosy-world.local:8140/?view=factory",
        "reachable": True,
    }
    redirect = http_up.get("/console/world", follow_redirects=False)
    assert redirect.status_code == 303
    assert redirect.headers["location"] == "http://rosy-world.local:8140/?view=factory"

    http_down = _client(
        monkeypatch,
        mdns_host="rosy-world.local",
        mdns_port=8140,
        discover_fn=lambda _h, _p, _s: None,
    )
    assert http_down.get("/api/fleet/world-entry").json()["reachable"] is False
    down_page = http_down.get("/console/world", follow_redirects=False)
    assert down_page.status_code == 503
    assert "rosy-world.local" in down_page.text


@pytest.mark.parametrize(
    "bad_mdns",
    ["192.168.1.50", "world.example", "a.b.local", "http://rosy-world.local", ""],
)
def test_invalid_mdns_host_rejected(monkeypatch, bad_mdns) -> None:
    if bad_mdns == "":
        assert _client(monkeypatch, mdns_host="").get("/api/fleet/world-entry").json()["mode"] == "unconfigured"
    else:
        with pytest.raises(ValueError):
            _client(monkeypatch, mdns_host=bad_mdns)


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://world.example:8140",
        "https://user:pass@world.example",
        "http://127.0.0.1:8140/path",
        "http://127.0.0.1:8140?q=1",
        "http://0.0.0.0:8140",
        "javascript:alert(1)",
    ],
)
def test_invalid_world_url_fails_startup(monkeypatch, bad_url) -> None:
    with pytest.raises(ValueError):
        _client(monkeypatch, bad_url)


def test_fleet_console_exposes_world_link() -> None:
    assert 'href="/console/world"' in (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    assert 'href="/console/world"' in (WEB_ROOT / "learning.html").read_text(encoding="utf-8")


def test_world_entry_enforces_read_guard(monkeypatch) -> None:
    from fastapi import Depends, HTTPException

    def deny():
        raise HTTPException(status_code=401, detail="unauthorized")

    app = FastAPI()
    app.state.web_common = None
    monkeypatch.delenv("ROSY_WORLD_URL", raising=False)
    monkeypatch.delenv("ROSY_WORLD_MDNS_HOST", raising=False)
    install_world_routes(app, WEB_ROOT, CONSOLE_CSP, read_guard=[Depends(deny)])
    assert TestClient(app).get("/api/fleet/world-entry").status_code == 401
