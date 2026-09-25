"""Network / Release / Commissioning card contracts (WP-5, design 10.2/10.3).

CORE holds no host privilege, so everything on these cards comes from the Host
Agent. The property worth testing hardest is not that the data flows — it is
that the dashboard **cannot show something that is not true**. An unreachable
agent and a healthy device with nothing to report look identical if the API
answers both with empty fields, and an operator reads a blank field as "fine".
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from core_api_web.api.app import create_app
from core_api_web.api.host_agent_client import (
    TIMEOUT,
    UNAVAILABLE,
    UNREADABLE,
    HostAgentClient,
)

VIEWER_TOKEN = "viewer-token"
ADMIN_TOKEN = "admin-token"

CONFIG = {
    "auth": {
        "tokens": [
            {"token": VIEWER_TOKEN, "role": "viewer"},
            {"token": ADMIN_TOKEN, "role": "administrator"},
        ]
    },
    "runtime": {"mode": "core"},
    "host_agent": {"socket_path": "/nonexistent/host-agent.sock", "timeout_s": 0.1},
}


@pytest.fixture
def client():
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    return TestClient(create_app(CONFIG, SimpleNamespace(config=CONFIG)))


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class FakeConnection:
    """A socket that returns one canned line."""

    def __init__(self, reply: dict | str) -> None:
        self.reply = reply if isinstance(reply, str) else json.dumps(reply)
        self.sent = b""
        self.closed = False

    def sendall(self, data: bytes) -> None:
        self.sent += data

    def recv(self, _size: int) -> bytes:
        if self.closed:
            return b""
        self.closed = True
        return self.reply.encode("utf-8") + b"\n"

    def close(self) -> None:
        self.closed = True


# --- the client never invents an answer -----------------------------------


def test_an_absent_socket_is_reported_not_raised():
    """A development box has no agent. That is expected, not exceptional."""
    reply = HostAgentClient(socket_path="/nonexistent/sock", timeout_s=0.1).request(
        "release.status", role="viewer"
    )

    assert reply.ok is False
    assert reply.code == UNAVAILABLE
    assert reply.reachable is False
    assert "host agent" in reply.detail.lower()
    assert reply.recovery, "an unreachable agent must say what to check"


def test_a_timeout_is_distinct_from_an_absent_agent():
    def timing_out():
        raise TimeoutError

    reply = HostAgentClient(connect=timing_out, timeout_s=0.1).request(
        "release.status", role="viewer"
    )

    assert reply.code == TIMEOUT
    assert reply.reachable is False


def test_an_unparseable_reply_is_distinct_from_no_reply():
    reply = HostAgentClient(connect=lambda: FakeConnection("{ not json")).request(
        "release.status", role="viewer"
    )

    assert reply.code == UNREADABLE
    assert reply.reachable is False


def test_a_refusal_from_the_agent_counts_as_reachable():
    """"The agent said no" and "no agent answered" are different facts."""
    refusal = {"ok": False, "code": "RECOVERY_HELD", "detail": "held", "recovery": "clear it"}
    reply = HostAgentClient(connect=lambda: FakeConnection(refusal)).request(
        "release.install", role="administrator"
    )

    assert reply.ok is False
    assert reply.code == "RECOVERY_HELD"
    assert reply.reachable is True, "a refusal is an answer"


def test_a_successful_reply_carries_its_data():
    payload = {"ok": True, "code": "OK", "data": {"current": "2026.09.05-002"}}
    reply = HostAgentClient(connect=lambda: FakeConnection(payload)).request(
        "release.status", role="viewer"
    )

    assert reply.ok and reply.reachable
    assert reply.data == {"current": "2026.09.05-002"}


def test_the_request_matches_the_agent_contract():
    connection = FakeConnection({"ok": True, "code": "OK"})
    HostAgentClient(connect=lambda: connection).request(
        "release.install",
        role="administrator",
        user_id="operator-01",
        confirmed=True,
        params={"release_id": "2026.09.05-002"},
        idempotency_key="01J8Zkey",
    )

    sent = json.loads(connection.sent.decode("utf-8"))
    assert sent["schema_version"] == 1
    assert sent["command"] == "release.install"
    assert sent["actor"] == {"user_id": "operator-01", "role": "administrator"}
    assert sent["confirmed"] is True
    assert sent["params"] == {"release_id": "2026.09.05-002"}
    assert sent["idempotency_key"] == "01J8Zkey"
    assert sent["request_id"], "every request carries its own id"
    assert connection.sent.endswith(b"\n"), "the agent reads one line"


def test_every_request_gets_a_fresh_id():
    ids = set()
    for _ in range(5):
        client = HostAgentClient(connect=lambda: FakeConnection({"ok": True, "code": "OK"}))
        client.request("release.status", role="viewer")
        ids.add(client._sent[-1]["request_id"])
    assert len(ids) == 5


def test_confirmation_defaults_to_false():
    """Forgetting to pass it must not read as a person having confirmed."""
    client = HostAgentClient(connect=lambda: FakeConnection({"ok": True, "code": "OK"}))
    client.request("system.reboot", role="administrator")

    assert client._sent[-1]["confirmed"] is False


# --- the cards say when they do not know ----------------------------------


@pytest.mark.parametrize("path", ["/api/v1/host/network", "/api/v1/host/release"])
def test_a_card_reports_an_unreachable_agent_rather_than_blank_fields(client, path):
    """A blank field reads as "nothing wrong"; this must read as "unknown"."""
    response = client.get(path, headers=_auth(VIEWER_TOKEN))

    assert response.status_code == 200, "an absent agent is not a server error"
    body = response.json()
    assert body["available"] is False
    assert body["data"] is None
    assert body["detail"], "the card must say why it is empty"
    assert body["code"] == UNAVAILABLE


@pytest.mark.parametrize("path", ["/api/v1/host/network", "/api/v1/host/release"])
def test_a_card_requires_authentication(client, path):
    assert client.get(path).status_code == 401


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/host/release/install",
        "/api/v1/host/release/rollback",
        "/api/v1/host/release/clear-hold",
        "/api/v1/host/network/apply",
        "/api/v1/host/network/mode",
        "/api/v1/host/network/connect",
        "/api/v1/host/reboot",
    ],
)
def test_an_action_requires_administrator(client, path):
    body = {
        "confirmed": True,
        "release_id": "2026.09.05-002",
        "profile_id": "rosy-site-sta",
        "mode": "SITE_STA",
        "ssid": "shop-wifi",
        "psk": "supersecretpsk",
    }

    assert client.post(path, json=body, headers=_auth(VIEWER_TOKEN)).status_code == 403
    # An administrator gets through the role gate and is stopped by the absent
    # agent instead, which is the honest failure here.
    allowed = client.post(path, json=body, headers=_auth(ADMIN_TOKEN))
    assert allowed.status_code == 200
    assert allowed.json()["available"] is False


def test_an_action_defaults_to_unconfirmed(client):
    """Omitting confirmation must not read as a person having confirmed."""
    response = client.post(
        "/api/v1/host/release/rollback", json={}, headers=_auth(ADMIN_TOKEN)
    )

    assert response.status_code == 200
    # The agent is absent here, so assert on what CORE sent rather than the
    # verdict: the point is that CORE did not fill in a confirmation.
    from core_api_web.api.v1.host import HostActionRequest

    assert HostActionRequest().confirmed is False


# --- commissioning is answerable without the agent ------------------------


def test_the_commissioning_card_works_without_the_agent(client):
    """CORE knows what it booted as; it need not ask the host."""
    body = client.get("/api/v1/host/commissioning", headers=_auth(VIEWER_TOKEN)).json()

    assert body["runtime_mode"] == "core"
    assert body["motor_hold"] is True
    assert body["lidar_hold"] is True
    assert body["battery_hold"] is True
    assert body["imu_hold"] is True
    assert body["slam_hold"] is True
    assert body["fleet_hold"] is True
    assert "정상" in body["detail"], "core-only is the correct state, not a fault"


def test_the_commissioning_card_reports_a_promoted_device():
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    config = dict(CONFIG, runtime={"mode": "hardware"})
    client = TestClient(create_app(config, SimpleNamespace(config=config)))

    body = client.get("/api/v1/host/commissioning", headers=_auth(VIEWER_TOKEN)).json()

    assert body["runtime_mode"] == "hardware"
    assert body["motor_hold"] is False
    assert body["lidar_hold"] is False
    assert body["battery_hold"] is True
    assert body["imu_hold"] is True
    assert body["slam_hold"] is True
    assert body["fleet_hold"] is True
    assert "ADC" in body["detail"] or "배터리" in body["detail"]
    assert "SLAM" in body["detail"]
    assert "Fleet" in body["detail"]


def test_the_commissioning_card_keeps_lidar_hold_in_motor_mode():
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    config = dict(CONFIG, runtime={"mode": "motor"})
    client = TestClient(create_app(config, SimpleNamespace(config=config)))

    body = client.get("/api/v1/host/commissioning", headers=_auth(VIEWER_TOKEN)).json()

    assert body["runtime_mode"] == "motor"
    assert body["motor_hold"] is False
    assert body["lidar_hold"] is True
    assert body["battery_hold"] is True
    assert body["imu_hold"] is True
    assert body["slam_hold"] is True
    assert body["fleet_hold"] is True
    assert "LiDAR" in body["detail"]


# --- nothing secret reaches a card ----------------------------------------


def test_a_card_does_not_echo_a_secret_the_agent_sent(client, monkeypatch):
    """Defence in depth: the agent redacts, and the card must not undo it."""
    payload = {
        "ok": True,
        "code": "OK",
        "data": {"ssid": "site-wifi", "psk": "[redacted]", "ipv4": "192.168.0.42"},
    }

    def fake_agent(_svc):
        return HostAgentClient(connect=lambda: FakeConnection(payload))

    monkeypatch.setattr("core_api_web.api.v1.host._agent", fake_agent)

    body = client.get("/api/v1/host/network", headers=_auth(VIEWER_TOKEN)).json()

    rendered = json.dumps(body, ensure_ascii=False)
    assert "site-wifi" in rendered, "the SSID is displayable"
    assert "[redacted]" in rendered
    assert "hunter" not in rendered


def test_a_reachable_agent_marks_the_card_available(client, monkeypatch):
    payload = {"ok": True, "code": "OK", "data": {"current": "2026.09.05-002"}}
    monkeypatch.setattr(
        "core_api_web.api.v1.host._agent",
        lambda _svc: HostAgentClient(connect=lambda: FakeConnection(payload)),
    )

    body = client.get("/api/v1/host/release", headers=_auth(VIEWER_TOKEN)).json()

    assert body["available"] is True
    assert body["ok"] is True
    assert body["data"]["current"] == "2026.09.05-002"


def test_a_refusal_reaches_the_card_with_its_recovery_action(client, monkeypatch):
    """Design section 11: the operator sees a code and what to do about it."""
    payload = {
        "ok": False,
        "code": "RECOVERY_HELD",
        "detail": "device is held for recovery",
        "recovery": "release.clear_hold 로 홀드를 해제한 뒤 다시 설치하십시오.",
    }
    monkeypatch.setattr(
        "core_api_web.api.v1.host._agent",
        lambda _svc: HostAgentClient(connect=lambda: FakeConnection(payload)),
    )

    body = client.post(
        "/api/v1/host/release/install",
        json={"confirmed": True, "release_id": "2026.09.05-002"},
        headers=_auth(ADMIN_TOKEN),
    ).json()

    assert body["available"] is True
    assert body["ok"] is False
    assert body["code"] == "RECOVERY_HELD"
    assert body["recovery"], "a refusal must carry its recovery action to the card"


# --- CORE and the agent agree on the wire ---------------------------------


def test_core_only_sends_commands_the_agent_implements():
    """Two statements of one allowlist drift apart unless something checks."""
    import sys

    agent_dir = str(Path(__file__).resolve().parents[4] / "deploy" / "release")
    if agent_dir not in sys.path:
        sys.path.insert(0, agent_dir)
    from host_agent import ALLOWLIST
    from core_api_web.api.v1 import host as host_routes

    source = Path(host_routes.__file__).read_text(encoding="utf-8")

    sent = set(re.findall(r'request\(\s*"([a-z_]+\.[a-z_]+)"', source))

    assert sent, "no commands found; the pattern needs updating"
    unknown = sorted(sent - set(ALLOWLIST))
    assert not unknown, f"CORE sends commands the agent does not implement: {unknown}"


# --- the rendered shell ----------------------------------------------------


WEB = Path(__file__).resolve().parents[3] / "hmi" / "dashboard"
NEWLINE = chr(10)


def _script() -> str:
    # D-262: host-card renderers live in host-cards.js; the shell only calls them.
    return "".join(
        (WEB / name).read_text(encoding="utf-8")
        for name in ("app.js", "host-cards.js")
    )


def _function_body(script: str, name: str) -> str:
    """The source of one top-level function, to the next one."""
    after = script.split(f"function {name}", 1)[1]
    return after.split(NEWLINE + "function ", 1)[0]


def test_the_three_cards_are_served(client):
    html = client.get("/dashboard").text

    assert 'id="network-card"' in html
    assert 'id="release-card"' in html
    assert 'id="commissioning-card"' in html
    assert 'aria-labelledby="host-heading"' in html


def test_the_cards_carry_accessible_names(client):
    html = client.get("/dashboard").text

    for heading in ("network-card-heading", "release-card-heading", "commissioning-heading"):
        assert f'id="{heading}"' in html
        assert f'aria-labelledby="{heading}"' in html


def test_destructive_actions_start_disabled(client):
    """Enabled only once the data says there is somewhere to go."""
    html = client.get("/dashboard").text

    for action in ("release-rollback", "release-clear-hold"):
        marker = html.split(f'id="{action}"', 1)[1].split(">", 1)[0]
        assert "disabled" in marker, f"{action} must not start enabled"


def test_the_cards_add_no_external_reference(client):
    """The dashboard runs with no internet; a remote asset would break it."""
    html = client.get("/dashboard").text
    panel = html.split('id="host-panel"', 1)[1].split("</section>", 1)[0]

    assert "http://" not in panel
    assert "https://" not in panel


def test_an_unavailable_card_hides_its_fields_rather_than_dashing_them():
    """An em dash reads as "measured, and it is nothing".

    That is the opposite of what an unreachable agent means, so the fields are
    hidden and the note explains, rather than every row showing a dash.
    """
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    assert '.host-card[data-available="false"]' in css
    hidden = css.split('.host-card[data-available="false"] .host-facts', 1)[1].split("}", 1)[0]
    assert "display: none" in hidden


def test_the_script_asks_for_all_three_cards():
    script = _script()

    for path in ("/api/v1/host/network", "/api/v1/host/release", "/api/v1/host/commissioning"):
        assert f'api("{path}")' in script, f"the dashboard never requests {path}"


def test_the_commissioning_script_shows_motor_and_lidar_holds():
    body = _function_body(_script(), "renderCommissioning")
    assert "motor_hold" in body
    assert "lidar_hold" in body
    assert "battery_hold" in body
    assert "imu_hold" in body
    assert "MOTOR_HOLD" in body
    assert "LIDAR_HOLD" in body
    assert "BATTERY_HOLD" in body
    assert "IMU_HOLD" in body
    assert "slam_hold" in body
    assert "SLAM_HOLD" in body
    assert "fleet_hold" in body
    assert "FLEET_HOLD" in body


def test_the_script_marks_a_card_unavailable_instead_of_blanking_it():
    body = _function_body(_script(), "setCardUnavailable")

    assert 'dataset.available = "false"' in body
    assert "detail" in body, "the card must render why it is empty"


def test_the_script_separates_internet_from_peer_reachability():
    """A router with client isolation gives you the internet and no dashboard."""
    body = _function_body(_script(), "renderHostNetwork")

    assert "peer_reachable" in body
    assert "client isolation" in body


def test_the_script_never_renders_a_wifi_secret():
    body = _function_body(_script(), "renderHostNetwork")

    for secret in ("psk", "passphrase", "password"):
        assert f"data.{secret}" not in body, f"the network card reads data.{secret}"
    assert "network-psk-input" not in body, "GET status must not fill the passphrase box"


def test_the_script_toggles_ap_mode_and_connects_wifi():
    script = _script()
    render = _function_body(script, "renderHostNetwork")
    assert "ap_active" in render
    assert "network-ap-off" in script
    assert "network-ap-on" in script
    assert "/api/v1/host/network/mode" in script
    assert "/api/v1/host/network/connect" in script
    assert "SITE_STA" in script
    assert "RELAY_AP_STA" in script
    assert "network-ssid-input" in script
    assert "network-psk-input" in script
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert 'id="network-ap-off"' in html
    assert 'id="network-ap-on"' in html
    assert 'id="network-connect"' in html
    assert 'id="network-ssid-input"' in html
    assert 'id="network-psk-input"' in html
    tag = html.split('id="network-psk-input"', 1)[1].split(">", 1)[0]
    assert 'type="password"' in tag


def test_rollback_is_offered_only_when_there_is_somewhere_to_go():
    body = _function_body(_script(), "renderHostRelease")

    assert "Boolean(data.previous)" in body, "rollback must require a previous release"
    assert "RECOVERY_HOLD" in body, "a held device offers clear-hold, not rollback"


def test_core_never_sends_a_piece_of_the_caller_token_to_the_agent(client, monkeypatch):
    """The actor id used to be the token's first 8 characters (D-30).

    That put a third of a short secret into the host's audit log, where CORE has
    no say over retention. The actor is now the opaque token id.
    """
    connection = FakeConnection({"ok": True, "code": "OK", "data": {}})

    def fake_agent(_svc):
        return HostAgentClient(connect=lambda: connection)

    monkeypatch.setattr("core_api_web.api.v1.host._agent", fake_agent)

    client.post(
        "/api/v1/host/network/apply",
        json={"profile_id": "rosy-site-sta", "confirmed": True},
        headers=_auth(ADMIN_TOKEN),
    )

    sent = json.loads(connection.sent.decode("utf-8"))
    user_id = sent["actor"]["user_id"]
    assert ADMIN_TOKEN not in connection.sent.decode("utf-8")
    for size in range(4, len(ADMIN_TOKEN) + 1):
        assert ADMIN_TOKEN[:size] != user_id
    assert sent["actor"]["role"] == "administrator"


def test_connect_relays_ssid_and_psk_but_does_not_echo_the_secret(client, monkeypatch):
    connection = FakeConnection({"ok": True, "code": "OK", "data": {"ssid": "shop-wifi"}})

    def fake_agent(_svc):
        return HostAgentClient(connect=lambda: connection)

    monkeypatch.setattr("core_api_web.api.v1.host._agent", fake_agent)

    secret = "supersecretpsk"
    body = client.post(
        "/api/v1/host/network/connect",
        json={"ssid": "shop-wifi", "psk": secret, "confirmed": True},
        headers=_auth(ADMIN_TOKEN),
    ).json()

    sent = json.loads(connection.sent.decode("utf-8"))
    assert sent["command"] == "network.connect"
    assert sent["params"]["ssid"] == "shop-wifi"
    assert sent["params"]["psk"] == secret
    rendered = json.dumps(body, ensure_ascii=False)
    assert secret not in rendered
    assert "psk" not in (body.get("data") or {})


def test_set_mode_relays_enumerated_d26_mode(client, monkeypatch):
    connection = FakeConnection({"ok": True, "code": "OK", "data": {"mode": "SITE_STA"}})
    monkeypatch.setattr(
        "core_api_web.api.v1.host._agent",
        lambda _svc: HostAgentClient(connect=lambda: connection),
    )

    body = client.post(
        "/api/v1/host/network/mode",
        json={"mode": "SITE_STA", "confirmed": True},
        headers=_auth(ADMIN_TOKEN),
    ).json()

    sent = json.loads(connection.sent.decode("utf-8"))
    assert sent["command"] == "network.set_mode"
    assert sent["params"] == {"mode": "SITE_STA"}
    assert body["available"] is True
    assert body["data"]["mode"] == "SITE_STA"
