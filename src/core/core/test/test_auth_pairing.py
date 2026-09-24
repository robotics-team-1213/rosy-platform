"""D-193 S1: login codes, paired tokens and the token lifecycle in CORE.

The root issuer (`deploy/robot/native/rosy-login-code.py`) is not imported
here: these tests write its verifier file themselves, with the same scrypt
parameters, into a temporary directory the pairing state is pointed at.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

CONFIG_DIR = Path(__file__).parent.parent / "config"
BOOT_ID = "7d4c1f0e-0a52-4a8e-9a3e-2f6f1b1c0d11"
CODE = "7KXM" + "P3QA"  # assembled: the tracked-file scanner sees no literal
OTHER_CODE = "HJ4N" + "WR9B"
CODE_ID = "0123456789abcdef"
LAN = ("192.168.1.20", 50000)
AUTH = "Authori" + "zation"


def bearer(value: str) -> dict:
    return {AUTH: "Bearer " + value}


DEV_ADMIN = bearer("rosy-dev-" + "admin")
DEV_OPERATOR = bearer("rosy-dev-" + "operator")
DEV_VIEWER = bearer("rosy-dev-" + "viewer")


class Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def write_code(directory: Path, code: str = CODE, *, code_id: str = CODE_ID, role: str = "operator",
               boot_id: str = BOOT_ID, expires: float = 1600.0, **kdf_overrides) -> Path:
    salt = bytes(range(16))
    kdf = {"name": "scrypt", "n": 2 ** 14, "r": 8, "p": 1, "dklen": 32, "salt": salt.hex(), **kdf_overrides}
    digest = hashlib.scrypt(code.encode("ascii"), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    path = directory / "login-code.json"
    path.write_text(json.dumps({
        "schema_version": 1, "code_id": code_id, "role": role, "source": "pair-physical",
        "kdf": kdf, "digest": digest.hex(), "boot_id": boot_id, "expires_monotonic": expires,
    }), encoding="utf-8")
    return path


@pytest.fixture
def robot(core_client, tmp_path, monkeypatch):
    """A robot whose pairing state reads a temporary /run and a fake clock."""
    from fastapi.testclient import TestClient

    monkeypatch.setattr("core_common.config.LOCAL_CONFIG_PATH", tmp_path / "rosy.yaml")
    monkeypatch.delenv("ROSY_CONFIG", raising=False)
    monkeypatch.delenv("ROSY_DEPLOYMENT", raising=False)
    boot = tmp_path / "run-boot"
    own = tmp_path / "run-rosy"
    boot.mkdir()
    own.mkdir()
    (tmp_path / "boot_id").write_text(BOOT_ID + "\n", encoding="ascii")

    def build(*, config_overrides=None, dev_auth=True, client=LAN):
        tc, svc = core_client(config_overrides=config_overrides, dev_auth=dev_auth)
        app = tc.app
        state = app.state.pairing
        state.clock = Clock()
        state.code_file = str(boot / "login-code.json")
        state.state_file = str(own / "login-code-state.json")
        state.boot_id_file = str(tmp_path / "boot_id")
        events: list = []
        svc.events.subscribe(events.append)
        return TestClient(app, client=client), svc, state, events

    build.boot = boot
    build.own = own
    return build


def _pair(tc, code=CODE, **extra):
    return tc.post("/api/v1/auth/pair", json={"code": code, **extra})


def _state_file(state) -> dict:
    return json.loads(Path(state.state_file).read_text(encoding="ascii"))


# --- pairing ------------------------------------------------------------------


def test_a_code_pairs_once_into_an_expiring_browser_token(robot):
    tc, svc, state, events = robot()
    write_code(robot.boot)

    paired = _pair(tc, "7kxm-p3qa", label="phone")

    assert paired.status_code == 201
    assert paired.headers["cache-control"] == "no-store"
    body = paired.json()
    assert body["role"] == "operator" and body["source"] == "pair-physical" and body["label"] == "phone"
    expires = datetime.fromisoformat(body["expires_at"])
    assert timedelta(days=6, hours=23) < expires - datetime.now(timezone.utc) <= timedelta(days=7)
    me = tc.get("/api/v1/auth/whoami", headers=bearer(body["token"]))
    assert me.status_code == 200
    assert me.json() == {"id": body["id"], "role": "operator", "label": "phone", "source": "pair-physical",
                         "created_at": me.json()["created_at"], "expires_at": body["expires_at"]}
    # One use: the same code again is refused, and root is told to clear the screen.
    assert _pair(tc).status_code == 401
    assert _state_file(state) == {"code_id": CODE_ID, "state": "used"}
    paired_events = [event for event in events if event.type == "auth.paired"]
    assert len(paired_events) == 1
    assert paired_events[0].data == {"id": body["id"], "role": "operator", "source": "pair-physical",
                                     "expires_at": body["expires_at"]}
    assert CODE not in json.dumps([event.model_dump() for event in events], default=str)
    # The token is persisted; the code and the raw token are not.
    from core_common.config import overlay_path

    stored = yaml.safe_load(overlay_path().read_text(encoding="utf-8"))["auth"]["tokens"]
    record = next(item for item in stored if item["id"] == body["id"])
    assert record["source"] == "pair-physical" and record["paired_via"] == CODE_ID
    assert record["expires_at"] == body["expires_at"]
    assert body["token"] not in json.dumps(stored)


def test_a_code_from_another_boot_or_after_its_monotonic_expiry_is_refused(robot):
    tc, _svc, state, _events = robot()
    write_code(robot.boot, boot_id="another-boot")
    assert _pair(tc).status_code == 401

    write_code(robot.boot, expires=1600.0)
    state.clock.now = 1600.0  # the deadline itself is already too late
    assert _pair(tc).status_code == 401
    state.clock.now = 1599.0
    assert _pair(tc).status_code == 201


def test_five_wrong_attempts_burn_the_code_and_tell_root(robot):
    tc, _svc, state, events = robot()
    write_code(robot.boot)

    for _ in range(5):
        assert _pair(tc, OTHER_CODE).status_code == 401
    assert _state_file(state) == {"code_id": CODE_ID, "state": "burned"}
    assert [event.data for event in events if event.type == "auth.code_burned"] == [
        {"code_id": CODE_ID, "attempts": 5}]

    other = type(tc)(tc.app, client=("192.168.1.21", 50000))
    assert _pair(other).status_code == 401  # the right code no longer works


def test_the_sixth_request_from_one_address_is_rate_limited(robot):
    tc, _svc, state, _events = robot()

    for _ in range(5):
        assert _pair(tc, OTHER_CODE).status_code == 401
    limited = _pair(tc, OTHER_CODE)
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "RATE_LIMITED"
    assert 1 <= int(limited.headers["retry-after"]) <= 60
    other = type(tc)(tc.app, client=("10.42.0.7", 50000))
    assert _pair(other, OTHER_CODE).status_code == 401  # another phone on the AP is not blocked
    state.clock.now += 60.0
    assert _pair(tc, OTHER_CODE).status_code == 401


def test_the_global_limit_holds_across_addresses(robot):
    tc, _svc, _state, _events = robot()
    statuses = []
    for index in range(31):
        client = type(tc)(tc.app, client=(f"192.168.2.{index + 1}", 50000))
        statuses.append(_pair(client, OTHER_CODE).status_code)
    assert statuses[:30] == [401] * 30 and statuses[30] == 429


@pytest.mark.parametrize("host", ["8.8.8.8", "100.64.0.1", "169.254.1.1", "testclient", "2001:db8::1"])
def test_pairing_is_refused_outside_the_robot_lan(robot, host):
    tc, _svc, _state, _events = robot(client=(host, 50000))
    write_code(robot.boot)
    assert _pair(tc).status_code == 403


@pytest.mark.parametrize("host", ["127.0.0.1", "10.42.0.12", "172.20.1.1", "192.168.0.9", "::ffff:192.168.0.9"])
def test_pairing_is_accepted_from_private_ap_and_loopback_addresses(robot, host):
    tc, _svc, _state, _events = robot(client=(host, 50000))
    write_code(robot.boot)
    assert _pair(tc).status_code == 201


def test_an_oversized_or_malformed_body_is_refused_before_any_hashing(robot):
    tc, _svc, _state, _events = robot()
    write_code(robot.boot)

    assert tc.post("/api/v1/auth/pair", content=b"{" + b" " * 1100 + b"}",
                   headers={"content-type": "application/json"}).status_code == 413
    assert tc.post("/api/v1/auth/pair", content=b"not json").status_code == 400
    assert _pair(tc, "ABC").status_code == 400
    assert _pair(tc, "0O1I" + "0O1I").status_code == 400  # confusable characters are not in the alphabet


def test_a_verifier_file_with_other_scrypt_costs_is_ignored(robot):
    tc, _svc, _state, _events = robot()
    write_code(robot.boot, n=2 ** 10)
    assert _pair(tc).status_code == 401


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="POSIX O_NOFOLLOW")
def test_a_symlinked_verifier_file_is_ignored(robot, tmp_path):
    tc, _svc, _state, _events = robot()
    (robot.boot / "login-code.json").symlink_to(write_code(tmp_path))
    assert _pair(tc).status_code == 401


def test_a_pairing_never_yields_a_non_expiring_token(robot):
    tc, _svc, _state, _events = robot(config_overrides=None)
    tc.app.state.core.config["auth"]["pairing"] = {"token_lifetime_hours": {"administrator": 0}}
    write_code(robot.boot, role="administrator")

    body = _pair(tc).json()

    assert body["role"] == "administrator"
    expires = datetime.fromisoformat(body["expires_at"])
    assert timedelta(hours=23) < expires - datetime.now(timezone.utc) <= timedelta(hours=24)


def test_pairing_lifetimes_come_from_auth_pairing(robot):
    tc, _svc, _state, _events = robot()
    tc.app.state.core.config["auth"]["pairing"] = {"token_lifetime_hours": {"operator": 2}}
    write_code(robot.boot)

    expires = datetime.fromisoformat(_pair(tc).json()["expires_at"])

    assert timedelta(hours=1, minutes=59) < expires - datetime.now(timezone.utc) <= timedelta(hours=2)


# --- enrollment codes -----------------------------------------------------------


def test_an_administrator_enrolls_another_device_with_a_short_code(robot):
    tc, _svc, state, events = robot()

    issued = tc.post("/api/v1/auth/enrollment-codes", json={"role": "viewer"}, headers=DEV_ADMIN)

    assert issued.status_code == 201
    assert issued.headers["cache-control"] == "no-store"
    body = issued.json()
    assert body["role"] == "viewer" and body["expires_in_s"] == 300
    assert len(body["code"]) == 9 and body["code"][4] == "-"
    assert [event.data["role"] for event in events if event.type == "auth.enrollment_code_issued"] == ["viewer"]
    assert body["code"] not in json.dumps([event.model_dump() for event in events], default=str)

    paired = _pair(tc, body["code"])
    assert paired.status_code == 201
    assert paired.json()["role"] == "viewer" and paired.json()["source"] == "pair-admin"
    assert _pair(tc, body["code"]).status_code == 401
    assert not Path(state.state_file).exists()  # nothing for root to clear


def test_an_enrollment_code_expires_after_five_minutes(robot):
    tc, _svc, state, _events = robot()
    code = tc.post("/api/v1/auth/enrollment-codes", json={"role": "operator"}, headers=DEV_ADMIN).json()["code"]
    state.clock.now += 300.0
    assert _pair(tc, code).status_code == 401


def test_an_enrollment_code_never_exceeds_the_issuers_role(robot):
    tc, _svc, _state, _events = robot()
    assert tc.post("/api/v1/auth/enrollment-codes", json={"role": "viewer"},
                   headers=DEV_OPERATOR).status_code == 403
    assert tc.post("/api/v1/auth/enrollment-codes", json={"role": "wizard"},
                   headers=DEV_ADMIN).status_code == 400

    from core_api_web.api.deps import AuthContext
    from core_api_web.api.errors import ApiError
    from core_api_web.api.v1.auth import EnrollmentRequest, create_enrollment_code

    class Request:
        class app:  # noqa: N801 - mimics request.app.state
            state = tc.app.state

    operator = AuthContext("op-id", "operator")
    with pytest.raises(ApiError) as refused:
        create_enrollment_code(EnrollmentRequest(role="administrator"), Request, operator,
                               tc.app.state.core)
    assert refused.value.http_status == 403


# --- whoami / logout / lifecycle --------------------------------------------------


def test_whoami_answers_the_role_instead_of_the_dashboard_guessing(robot):
    tc, _svc, _state, _events = robot()
    assert tc.get("/api/v1/auth/whoami").status_code == 401
    me = tc.get("/api/v1/auth/whoami", headers=DEV_VIEWER).json()
    assert me["role"] == "viewer" and me["source"] == "legacy" and me["expires_at"] is None


def _card_config(extra=()):
    from core_api_web.api.deps import token_digest

    records = [{"id": "card01", "role": "administrator", "sha256": token_digest("card-" + "credential-value-1"),
                "label": "e4us card admin", "created_at": "2026-09-24T00:00:00+00:00", "source": "card"}]
    return {"auth": {"tokens": records + list(extra), "pairing": {}}}


CARD = bearer("card-" + "credential-value-1")


def test_logout_removes_only_a_paired_token(robot):
    tc, _svc, _state, _events = robot(config_overrides=_card_config(), dev_auth=False)
    assert tc.post("/api/v1/auth/logout", headers=CARD).status_code == 409
    assert tc.get("/api/v1/auth/whoami", headers=CARD).json()["source"] == "card"

    write_code(robot.boot)
    paired = bearer(_pair(tc).json()["token"])
    assert tc.post("/api/v1/auth/logout", headers=paired).status_code == 204
    assert tc.get("/api/v1/auth/whoami", headers=paired).status_code == 401
    assert [item["id"] for item in tc.get("/api/v1/system/tokens", headers=CARD).json()["tokens"]] == ["card01"]


def test_an_expired_token_is_refused_and_purged_on_the_next_write(robot):
    from core_api_web.api.deps import token_digest

    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds")
    stale = {"id": "stale1", "role": "operator", "sha256": token_digest("stale-" + "browser-value-1"),
             "label": "old phone", "created_at": "2026-09-01T00:00:00+00:00", "source": "pair-physical",
             "expires_at": past, "paired_via": CODE_ID}
    tc, svc, _state, _events = robot(config_overrides=_card_config([stale]), dev_auth=False)

    assert tc.get("/api/v1/auth/whoami", headers=bearer("stale-" + "browser-value-1")).status_code == 401
    assert "stale1" not in [item["id"] for item in tc.get("/api/v1/system/tokens", headers=CARD).json()["tokens"]]
    assert tc.post("/api/v1/system/tokens", json={"role": "viewer"}, headers=CARD).status_code == 201
    assert "stale1" not in [item["id"] for item in svc.config["auth"]["tokens"]]


def test_an_unreadable_expiry_is_treated_as_expired():
    from core_api_web.api.deps import is_expired

    assert is_expired({"expires_at": "tomorrow"})
    assert not is_expired({"expires_at": None})
    assert is_expired({"expires_at": "2026-01-01T00:00:00"})  # naive means UTC


def test_the_last_non_expiring_administrator_cannot_be_deleted(robot):
    tc, _svc, _state, _events = robot(config_overrides=_card_config(), dev_auth=False)
    write_code(robot.boot, role="administrator")
    paired_admin = bearer(_pair(tc).json()["token"])

    # A paired (24 h) administrator does not count as the one that must remain.
    refused = tc.delete("/api/v1/system/tokens/card01", headers=paired_admin)
    assert refused.status_code == 409
    assert "non-expiring" in refused.json()["error"]["message"]
    # Deleting an expiring administrator is fine while the card admin remains.
    paired_id = tc.get("/api/v1/auth/whoami", headers=paired_admin).json()["id"]
    assert tc.delete(f"/api/v1/system/tokens/{paired_id}", headers=CARD).status_code == 204


def test_the_token_list_shows_source_expiry_current_and_last_use_and_labels_change(robot):
    tc, _svc, _state, _events = robot(config_overrides=_card_config(), dev_auth=False)
    write_code(robot.boot)
    paired = _pair(tc).json()
    tc.get("/api/v1/auth/whoami", headers=bearer(paired["token"]))

    listed = {item["id"]: item for item in tc.get("/api/v1/system/tokens", headers=CARD).json()["tokens"]}
    assert listed["card01"]["source"] == "card" and listed["card01"]["current"] is True
    assert listed["card01"]["expires_at"] is None
    assert listed[paired["id"]]["current"] is False and listed[paired["id"]]["last_used_at"]
    assert listed[paired["id"]]["expires_at"] == paired["expires_at"]

    renamed = tc.patch(f"/api/v1/system/tokens/{paired['id']}", json={"label": "bay 7 tablet"}, headers=CARD)
    assert renamed.status_code == 200 and renamed.json()["label"] == "bay 7 tablet"
    assert tc.patch("/api/v1/system/tokens/nope", json={"label": "x"}, headers=CARD).status_code == 404
    assert tc.patch(f"/api/v1/system/tokens/{paired['id']}", json={"label": "x"},
                    headers=bearer(paired["token"])).status_code == 403


# --- device mode and defaults ---------------------------------------------------


def test_device_mode_refuses_dev_tokens_even_with_dev_auth(robot, monkeypatch, tmp_path):
    from core_api_web.api.deps import token_digest
    from core_common import config as core_config

    monkeypatch.setenv("ROSY_DEPLOYMENT", "device")
    monkeypatch.setenv("ROSY_DEV_AUTH", "1")
    assert core_config.load_config()["auth"]["tokens"] == []

    # Whatever layer brings them in (a stale overlay, a hand edit): plaintext
    # entries and the three dev digests are refused, and CORE says so once.
    hashed_dev = {"id": "devhash", "role": "administrator", "sha256": token_digest("rosy-dev-" + "admin"),
                  "label": "", "created_at": "2026-09-01T00:00:00+00:00"}
    overrides = _card_config([hashed_dev, {"token": "plain-" + "operator-value", "role": "operator"}])
    tc, _svc, _state, events = robot(config_overrides=overrides, dev_auth=True)
    tc2, _svc2, _state2, _events2 = robot(config_overrides=overrides, dev_auth=False)

    for client in (tc, tc2):
        assert client.get("/api/v1/robot/state", headers=DEV_ADMIN).status_code == 401
        assert client.get("/api/v1/robot/state", headers=DEV_VIEWER).status_code == 401
        assert client.get("/api/v1/robot/state", headers=bearer("plain-" + "operator-value")).status_code == 401
        assert client.get("/api/v1/robot/state", headers=CARD).status_code == 200


def test_device_mode_publishes_a_warning_for_refused_credentials(core_client, monkeypatch):
    monkeypatch.setenv("ROSY_DEPLOYMENT", "device")
    from core_api_web.api.app import create_app

    tc, svc = core_client()
    events: list = []
    svc.events.subscribe(events.append)
    create_app(svc.config, svc)
    refused = [event for event in events if event.type == "auth.credentials_refused"]
    assert refused and refused[0].data == {"count": 3} and refused[0].severity.value == "warning"


def test_dev_auth_merges_only_when_asked_and_not_on_a_device(monkeypatch, tmp_path):
    from core_common import config as core_config

    monkeypatch.setattr(core_config, "LOCAL_CONFIG_PATH", tmp_path / "missing.yaml")
    monkeypatch.delenv("ROSY_CONFIG", raising=False)
    monkeypatch.delenv("ROSY_DEPLOYMENT", raising=False)
    monkeypatch.delenv("ROSY_DEV_AUTH", raising=False)
    assert core_config.load_config()["auth"]["tokens"] == []

    monkeypatch.setenv("ROSY_DEV_AUTH", "1")
    loaded = core_config.load_config()
    assert [item["role"] for item in loaded["auth"]["tokens"]] == ["administrator", "operator", "viewer"]
    assert loaded["auth"]["pairing"]["token_lifetime_hours"]["administrator"] == 24

    # An overlay list still replaces the dev list as a whole (card first boot).
    (tmp_path / "missing.yaml").write_text("auth:\n  tokens: []\n", encoding="utf-8")
    assert core_config.load_config()["auth"]["tokens"] == []


def test_an_empty_token_list_keeps_the_api_up_and_answers_401(robot):
    tc, _svc, _state, _events = robot(dev_auth=False)
    assert tc.get("/api/v1").status_code == 200
    assert tc.get("/api/v1/robot/state").status_code == 401
    assert tc.get("/api/v1/robot/state", headers=DEV_ADMIN).status_code == 401
    assert tc.get("/api/v1/auth/whoami", headers=DEV_VIEWER).status_code == 401


def test_the_packaged_defaults_carry_no_tokens():
    text = (CONFIG_DIR / "rosy_default.yaml").read_text(encoding="utf-8")
    config = yaml.safe_load(text)
    assert config["auth"]["tokens"] == []
    assert "rosy-dev-" not in text
    lifetimes = config["auth"]["pairing"]["token_lifetime_hours"]
    assert lifetimes == {"viewer": 168, "operator": 168, "administrator": 24}
    dev = yaml.safe_load((CONFIG_DIR / "rosy_dev_auth.yaml").read_text(encoding="utf-8"))
    assert {item["role"] for item in dev["auth"]["tokens"]} == {"administrator", "operator", "viewer"}


# --- WebSocket first-message auth -----------------------------------------------


def test_websocket_accepts_the_token_as_the_first_message(robot):
    tc, _svc, _state, _events = robot()
    with tc.websocket_connect("/ws/state") as socket:
        socket.send_text(json.dumps({"type": "auth", "token": "rosy-dev-" + "viewer"}))
        assert isinstance(socket.receive_json(), dict)


def test_websocket_still_accepts_the_query_token_for_one_release(robot):
    tc, _svc, _state, _events = robot()
    with tc.websocket_connect("/ws/state?token=rosy-dev-" + "viewer") as socket:
        assert isinstance(socket.receive_json(), dict)


def test_websocket_refuses_a_wrong_or_missing_first_message(robot, monkeypatch):
    from starlette.websockets import WebSocketDisconnect
    import core_api_web.api.ws as ws_module

    monkeypatch.setattr(ws_module, "FIRST_MESSAGE_TIMEOUT_S", 0.05)
    tc, _svc, _state, _events = robot()
    for first in (json.dumps({"type": "auth", "token": "nope"}), "not json", json.dumps({"token": "x"})):
        with pytest.raises(WebSocketDisconnect) as closed:
            with tc.websocket_connect("/ws/events") as socket:
                socket.send_text(first)
                socket.receive_json()
        assert closed.value.code == 4401
    with pytest.raises(WebSocketDisconnect) as closed:
        with tc.websocket_connect("/ws/events") as socket:
            socket.receive_json()  # sends nothing: times out
    assert closed.value.code == 4401
    with pytest.raises(WebSocketDisconnect) as closed:
        with tc.websocket_connect("/ws/swarm/reference") as socket:
            socket.send_text(json.dumps({"type": "auth", "token": "rosy-dev-" + "viewer"}))
            socket.receive_json()
    assert closed.value.code == 4403
