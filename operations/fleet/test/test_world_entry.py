"""Tests for Fleet -> Rosy World static, mDNS and same-origin route resolution."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fleet.server.static_routes import CONSOLE_CSP, WEB_ROOT, install_static_routes
from fleet.server.world_entry import install_world_routes


def _client(monkeypatch, world_url=None, *, mdns_host=None, mdns_port=None, discover_fn=None,
            same_origin=None, health_url=None, probe_fn=None, sessions=None):
    monkeypatch.delenv("ROSY_LEARNING_APPS_CONFIG", raising=False)
    for var, val in (
        ("ROSY_WORLD_URL", world_url),
        ("ROSY_WORLD_MDNS_HOST", mdns_host),
        ("ROSY_WORLD_MDNS_PORT", mdns_port),
        ("ROSY_WORLD_SAME_ORIGIN", same_origin),
        ("ROSY_WORLD_HEALTH_URL", health_url),
    ):
        if val is None:
            monkeypatch.delenv(var, raising=False)
        else:
            monkeypatch.setenv(var, str(val))
    app = FastAPI()
    app.state.web_common = None
    setattr(app.state, "password_sessions", sessions)
    if discover_fn is None and probe_fn is None:
        install_static_routes(app)
    else:
        install_world_routes(app, WEB_ROOT, CONSOLE_CSP, mdns_discover_fn=discover_fn,
                             same_origin_probe_fn=probe_fn)
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
    monkeypatch.delenv("ROSY_WORLD_SAME_ORIGIN", raising=False)
    monkeypatch.delenv("ROSY_WORLD_HEALTH_URL", raising=False)
    install_world_routes(app, WEB_ROOT, CONSOLE_CSP, read_guard=[Depends(deny)])
    assert TestClient(app).get("/api/fleet/world-entry").status_code == 401


def test_same_origin_world_entry_status_and_redirect(monkeypatch) -> None:
    probed = []
    http = _client(monkeypatch, same_origin="1", probe_fn=lambda url: probed.append(url) or True)
    status = http.get("/api/fleet/world-entry")
    assert status.status_code == 200
    assert status.json() == {
        "configured": True,
        "mode": "same_origin",
        "mdns_host": None,
        "url": "/world/?view=factory&adapter=real",
        "reachable": True,
    }
    assert probed == ["http://world:8140/healthz"]  # default probe target
    redirect = http.get("/console/world", follow_redirects=False)
    assert redirect.status_code == 303
    assert redirect.headers["location"] == "/world/?view=factory&adapter=real"


def test_same_origin_world_entry_unreachable_returns_503(monkeypatch) -> None:
    http = _client(monkeypatch, same_origin="1", probe_fn=lambda url: False)
    body = http.get("/api/fleet/world-entry").json()
    assert body["reachable"] is False and body["url"] is None and body["mode"] == "same_origin"
    page = http.get("/console/world", follow_redirects=False)
    assert page.status_code == 503
    assert "same-origin" in page.text


@pytest.mark.parametrize("flag", ["0", "no", "off", "false"])
def test_same_origin_mode_off_for_other_flags(monkeypatch, flag) -> None:
    http = _client(monkeypatch, same_origin=flag, probe_fn=lambda url: True)
    assert http.get("/api/fleet/world-entry").json()["mode"] == "unconfigured"


def test_explicit_world_url_wins_over_same_origin(monkeypatch) -> None:
    http = _client(monkeypatch, "http://127.0.0.1:8140", same_origin="1", probe_fn=lambda url: True)
    assert http.get("/api/fleet/world-entry").json()["mode"] == "static"
    redirect = http.get("/console/world", follow_redirects=False)
    assert redirect.headers["location"] == "http://127.0.0.1:8140/?view=factory"


def test_same_origin_takes_precedence_over_mdns(monkeypatch) -> None:
    http = _client(monkeypatch, same_origin="1", mdns_host="rosy-world.local",
                   probe_fn=lambda url: True)
    assert http.get("/api/fleet/world-entry").json()["mode"] == "same_origin"


@pytest.mark.parametrize(
    "bad_health_url",
    [
        "http://evil.example/healthz",
        "http://192.168.1.5:8140/healthz",
        "https://world:8140/healthz",
        "http://world:8140/statusz",
        "http://world:8140/healthz?x=1",
        "http://user:pass@world:8140/healthz",
        "http://world:0/healthz",
        "http://world:99999/healthz",
        "http://world:",
    ],
)
def test_same_origin_health_url_rejects_untrusted_targets(monkeypatch, bad_health_url) -> None:
    with pytest.raises(ValueError):
        _client(monkeypatch, same_origin="1", health_url=bad_health_url, probe_fn=lambda url: True)


class _Sessions:
    """Minimal Fleet password-sessions stand-in for the /console/world login gate."""

    def __init__(self, principal=None) -> None:
        self.principal = principal

    def authenticate(self, request):
        return self.principal


def test_same_origin_entry_sends_anonymous_browsers_to_login(monkeypatch) -> None:
    http = _client(monkeypatch, same_origin="1", probe_fn=lambda url: True, sessions=_Sessions())
    page = http.get("/console/world", follow_redirects=False, headers={"Accept": "text/html"})
    assert page.status_code == 303
    assert page.headers["location"] == "/console/login?return=/console/world"
    denied = http.get("/console/world", follow_redirects=False)
    assert denied.status_code == 401


def test_same_origin_entry_redirects_authenticated_sessions(monkeypatch) -> None:
    http = _client(monkeypatch, same_origin="1", probe_fn=lambda url: True,
                   sessions=_Sessions(principal=object()))
    redirect = http.get("/console/world", follow_redirects=False, headers={"Accept": "text/html"})
    assert redirect.status_code == 303
    assert redirect.headers["location"] == "/world/?view=factory&adapter=real"


def test_login_return_accepts_the_world_entry() -> None:
    from fleet.server.account_receiver import DESTINATIONS, fleet_return_allowed

    assert "/console/world" in DESTINATIONS
    assert fleet_return_allowed("/console/world") is True
    assert fleet_return_allowed("/console/world?view=factory") is False
    assert fleet_return_allowed("/console/world#factory") is False
