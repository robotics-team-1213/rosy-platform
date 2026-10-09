"""D-418: the administrator-only SSH access API and its hand-over to rosy-ssh-access.

CORE writes /run/rosy/ssh-access.request and waits for the root helper's
response. Here the helper is the real rosy-ssh-access.py over tmp_path (its
commands faked), run by a thread whenever CORE's request appears, so every
route goes through both programs.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace

import pytest
from core_api_web.api.app import create_app
from core_api_web.api.v1 import ssh_handoff

ADMIN_TOKEN = "admin-token-d418"
OPERATOR_TOKEN = "operator-token-d418"
NATIVE = Path(__file__).resolve().parents[4] / "deploy/robot/pinky_pro/native"


def _load_helper():
    spec = importlib.util.spec_from_file_location("rosy_ssh_access_core_test", NATIVE / "rosy-ssh-access.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


helper = _load_helper()


class FakeSystem(helper.System):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.calls: list[tuple] = []

    def set_password(self, user, password):
        self.calls.append(("set_password", user, password))

    def lock_password(self, user):
        self.calls.append(("lock_password", user))

    def sshd_check(self):
        return True, ""

    def reload_sshd(self):
        self.calls.append(("reload_sshd",))

    def expire_timer(self, start):
        self.calls.append(("expire_timer", start))

    def core_group(self):
        return None

    def boot_id(self):
        return "boot-1"

    def ntp_synced(self):
        return False


class Helper:
    """rosy-ssh-access.path + service: run the helper whenever the request file appears."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.system = FakeSystem(root)
        self.runs = 0
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def _loop(self) -> None:
        request = self.root / helper.REQUEST
        while not self.stop.is_set():
            if request.exists():
                helper.main(["--root", str(self.root)], system=self.system)
                self.runs += 1
            time.sleep(0.01)


def _string(value: bytes) -> bytes:
    return len(value).to_bytes(4, "big") + value


def _key(body: bytes = b"\x01" * 32) -> str:
    return "ssh-ed25519 " + base64.b64encode(_string(b"ssh-ed25519") + _string(body)).decode()


def _config(tmp_path: Path, wait_s: float = 5.0) -> dict:
    (tmp_path / "run/rosy").mkdir(parents=True, exist_ok=True)
    (tmp_path / "etc/ssh").mkdir(parents=True, exist_ok=True)
    return {
        "auth": {"tokens": [
            {"id": "adm1", "role": "administrator", "label": "ops laptop",
             "sha256": hashlib.sha256(ADMIN_TOKEN.encode()).hexdigest()},
            {"token": OPERATOR_TOKEN, "role": "operator"},
        ]},
        "runtime": {"mode": "core"},
        "host_agent": {"socket_path": "/nonexistent/host-agent.sock", "timeout_s": 0.1},
        "ssh_access": {"request_path": str(tmp_path / helper.REQUEST),
                       "response_path": str(tmp_path / helper.RESPONSE),
                       "host_key_dir": str(tmp_path / "etc/ssh"), "wait_s": wait_s},
    }


@pytest.fixture
def robot(tmp_path):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    config = _config(tmp_path)
    running = Helper(tmp_path)
    running.thread.start()
    client = TestClient(create_app(config, SimpleNamespace(config=config, state=None)))
    yield SimpleNamespace(client=client, helper=running, root=tmp_path, config=config)
    running.stop.set()
    running.thread.join(timeout=2)


def _admin() -> dict:
    return {"Authorization": f"Bearer {ADMIN_TOKEN}"}


ROUTES = [("get", "/api/v1/host/ssh/host-keys"), ("get", "/api/v1/host/ssh/keys"),
          ("post", "/api/v1/host/ssh/keys"), ("delete", "/api/v1/host/ssh/keys/dev:x"),
          ("post", "/api/v1/host/ssh/password"), ("get", "/api/v1/host/ssh/password"),
          ("delete", "/api/v1/host/ssh/password")]


@pytest.mark.parametrize("method,path", ROUTES)
def test_every_route_is_administrator_only(robot, method, path):
    assert getattr(robot.client, method)(path).status_code == 401
    operator = getattr(robot.client, method)(path, headers={"Authorization": f"Bearer {OPERATOR_TOKEN}"})
    assert operator.status_code == 403
    assert not (robot.root / helper.REQUEST).exists() and robot.helper.runs == 0


def test_a_dev_mode_robot_never_opens_ssh_to_the_shared_dev_admin(robot, monkeypatch):
    from core_common import config as core_config

    marker = robot.root / "dev-mode"
    marker.write_text("", encoding="ascii")
    monkeypatch.setattr(core_config, "DEV_MODE_MARKER", marker)
    monkeypatch.setenv("ROSY_DEPLOYMENT", "device")
    robot.config["auth"]["tokens"].append({"token": "rosy-dev-" + "admin", "role": "administrator"})
    dev = {"Authorization": "Bearer rosy-dev-" + "admin"}

    # D-548: the marker opens the API (keys list is admin-only) but not the shell.
    assert robot.client.get("/api/v1/host/ssh/host-keys", headers=dev).status_code == 200
    assert robot.client.post("/api/v1/host/ssh/keys", headers=dev,
                             json={"public_key": _key(), "label": "dev:x", "expires_days": 1}).status_code == 403
    assert robot.client.get("/api/v1/host/ssh/password", headers=dev).status_code == 403
    assert not (robot.root / helper.REQUEST).exists() and robot.helper.runs == 0


def test_enroll_list_and_revoke_through_the_helper(robot):
    key = _key()
    created = robot.client.post("/api/v1/host/ssh/keys", headers=_admin(),
                                json={"public_key": key + " me@laptop", "label": "dev:laptop", "expires_days": 30})
    assert created.status_code == 201, created.text
    body = created.json()
    assert set(body) == {"label", "fingerprint", "expires_at"} and body["label"] == "dev:laptop"
    assert body["fingerprint"].startswith("SHA256:")
    line = (robot.root / helper.AUTHORIZED).read_text(encoding="utf-8")
    assert line.startswith('expiry-time="') and line.endswith(f'Z" {key} rosy-managed:dev:laptop\n')

    listed = robot.client.get("/api/v1/host/ssh/keys", headers=_admin())
    assert listed.status_code == 200
    [row] = listed.json()["keys"]
    # added_by is the requesting token's label.
    assert row["added_by"] == "ops laptop" and row["type"] == "ssh-ed25519"
    assert set(row) == {"label", "type", "fingerprint", "added_at", "expires_at", "added_by"}

    revoked = robot.client.delete("/api/v1/host/ssh/keys/dev:laptop", headers=_admin())
    assert revoked.status_code == 204 and revoked.content == b""
    assert robot.client.get("/api/v1/host/ssh/keys", headers=_admin()).json() == {"keys": []}
    missing = robot.client.delete("/api/v1/host/ssh/keys/dev:laptop", headers=_admin())
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "SSH_KEY_NOT_FOUND"


@pytest.mark.parametrize("payload", [
    {"public_key": "ssh-rsa AAAAB3NzaC1yc2E=", "label": "a", "expires_days": 1},
    {"public_key": _key(), "label": "Bad Label", "expires_days": 1},
    {"public_key": _key(), "label": "a", "expires_days": 0},
    {"public_key": _key(), "label": "a", "expires_days": 366},
    {"public_key": _key(), "label": "a", "expires_days": "30"},
    {"public_key": _key(), "label": "a"},
    {"public_key": _key(), "label": "a", "expires_days": 1, "options": "command=sh"},
    ["not", "an", "object"],
])
def test_invalid_key_label_or_days_is_422_and_never_reaches_root(robot, payload):
    response = robot.client.post("/api/v1/host/ssh/keys", headers=_admin(), json=payload)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "SSH_INVALID"
    assert robot.helper.runs == 0


def test_a_token_label_the_helper_would_refuse_is_made_printable(robot, monkeypatch):
    """The helper ignores a request whose `by` is not printable; CORE must not send one (a 10 s 503)."""
    from core_api_web.api import deps

    original = deps.AuthContext.__init__

    def labelled(self, *args, **kwargs):
        original(self, *args, **kwargs)
        self.label = "ops\nlaptop\t" + "x" * 200

    monkeypatch.setattr(deps.AuthContext, "__init__", labelled)
    response = robot.client.post("/api/v1/host/ssh/keys", headers=_admin(),
                                 json={"public_key": _key(), "label": "a", "expires_days": 1})
    assert response.status_code == 201, response.text
    [row] = robot.client.get("/api/v1/host/ssh/keys", headers=_admin()).json()["keys"]
    assert row["added_by"].startswith("opslaptop") and len(row["added_by"]) == 128


def test_conflicts_come_back_from_the_helper(robot):
    first = {"public_key": _key(), "label": "a", "expires_days": 1}
    assert robot.client.post("/api/v1/host/ssh/keys", headers=_admin(), json=first).status_code == 201
    again = robot.client.post("/api/v1/host/ssh/keys", headers=_admin(),
                              json={**first, "public_key": _key(b"\x02" * 32)})
    assert again.status_code == 409 and again.json()["error"]["code"] == "SSH_LABEL_EXISTS"


def test_the_temporary_password_round_trip(robot):
    off = robot.client.get("/api/v1/host/ssh/password", headers=_admin())
    assert off.status_code == 200 and off.json() == {"enabled": False, "expires_at": None, "lock_pending": False}

    issued = robot.client.post("/api/v1/host/ssh/password", headers=_admin(), json={"minutes": 10})
    assert issued.status_code == 200, issued.text
    body = issued.json()
    assert set(body) == {"user", "password", "expires_at"} and body["user"] == "rosy"
    assert body["password"].startswith("rosy-") and len(body["password"]) == len("rosy-xxxx-xxxx-xxxx")
    assert "no-store" in issued.headers.get("cache-control", "")
    # Read once and gone: the password is not left in /run/rosy.
    assert not (robot.root / helper.RESPONSE).exists()

    status = robot.client.get("/api/v1/host/ssh/password", headers=_admin()).json()
    assert status["enabled"] is True and status["expires_at"] == body["expires_at"]
    gone = robot.client.delete("/api/v1/host/ssh/password", headers=_admin())
    assert gone.status_code == 204
    assert robot.client.get("/api/v1/host/ssh/password", headers=_admin()).json()["enabled"] is False
    assert ("lock_password", "rosy") in robot.helper.system.calls


@pytest.mark.parametrize("payload", [{"minutes": 0}, {"minutes": 61}, {"minutes": "5"}, {"minutes": True}, {}])
def test_password_minutes_outside_1_to_60_are_422(robot, payload):
    response = robot.client.post("/api/v1/host/ssh/password", headers=_admin(), json=payload)
    assert response.status_code == 422 and response.json()["error"]["code"] == "SSH_INVALID"
    assert robot.helper.runs == 0


def test_no_helper_answer_is_503_within_the_wait_and_the_request_is_withdrawn(tmp_path):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    config = _config(tmp_path, wait_s=0.3)
    client = TestClient(create_app(config, SimpleNamespace(config=config, state=None)))
    started = time.monotonic()
    response = client.get("/api/v1/host/ssh/keys", headers=_admin())
    assert response.status_code == 503 and response.json()["error"]["code"] == "SSH_ACCESS_UNAVAILABLE"
    assert time.monotonic() - started < 3
    assert not (tmp_path / helper.REQUEST).exists()


def test_the_wait_is_capped_at_ten_seconds():
    assert ssh_handoff.WAIT_S == 10.0
    from core_api_web.api.v1 import host_ssh
    assert host_ssh.wait_seconds({"ssh_access": {"wait_s": 600}}) == 10.0


def test_an_answer_to_another_request_is_not_taken(tmp_path):
    response_path = tmp_path / "response"
    response_path.write_text(json.dumps({"schema": 1, "request_id": "other", "status": 200, "error": None,
                                         "message": "", "result": {"keys": []}}), encoding="utf-8")
    assert ssh_handoff.read_response(str(response_path), "mine") is None
    assert ssh_handoff.read_response(str(response_path), "other") is not None


@pytest.mark.parametrize("change", [{"status": 500}, {"status": 418, "error": "SSH_INVALID"}, {"status": 409, "error": "SHELL"}, {"status": 200, "error": "X"},
                                    {"status": 409, "error": None}, {"result": [1]}, {"schema": 2},
                                    {"status": True}])
def test_a_malformed_answer_is_not_taken(tmp_path, change):
    document = {"schema": 1, "request_id": "mine", "status": 200, "error": None, "message": "",
                "result": {"keys": []}, **change}
    path = tmp_path / "response"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert ssh_handoff.read_response(str(path), "mine") is None


def test_core_writes_what_the_helper_reads(tmp_path):
    request = ssh_handoff.build_request("add", "ops laptop", {"public_key": _key(), "label": "a", "expires_days": 1})
    path = tmp_path / "request"
    ssh_handoff.write_request(str(path), request)
    parsed = helper.read_request(path, time.time())
    assert parsed == request


def test_host_keys_are_the_public_lines_without_comments(robot):
    ed = "ssh-ed25519 " + base64.b64encode(_string(b"ssh-ed25519") + _string(b"\x03" * 32)).decode()
    (robot.root / "etc/ssh/ssh_host_ed25519_key.pub").write_text(ed + " root@rosy-pinky-xxxx\n", encoding="utf-8")
    # Only *.pub is read: a file without it is never served, whatever it holds.
    other = "ssh-ed25519 " + base64.b64encode(_string(b"ssh-ed25519") + _string(b"\x04" * 32)).decode()
    (robot.root / "etc/ssh/ssh_host_ed25519_key").write_text(other + " PRIVATE\n", encoding="utf-8")
    (robot.root / "etc/ssh/ssh_host_bogus_key.pub").write_text("not a key\n", encoding="utf-8")
    response = robot.client.get("/api/v1/host/ssh/host-keys", headers=_admin())
    assert response.status_code == 200
    body = response.json()
    assert body["host_keys"] == [ed] and isinstance(body["hostname"], str) and body["hostname"]
    assert "PRIVATE" not in response.text and robot.helper.runs == 0


# --- review fixes ---------------------------------------------------------------------


def test_turning_the_password_off_works_with_a_corrupt_keys_record(robot):
    issued = robot.client.post("/api/v1/host/ssh/password", headers=_admin(), json={"minutes": 10})
    assert issued.status_code == 200, issued.text
    (robot.root / helper.KEYS).write_text("{not json", encoding="utf-8")
    robot.helper.system.calls.clear()
    gone = robot.client.delete("/api/v1/host/ssh/password", headers=_admin())
    assert gone.status_code == 204, gone.text
    assert ("lock_password", "rosy") in robot.helper.system.calls
    assert not (robot.root / helper.TEMP_LOGIN_DROPIN).exists()


def test_a_password_exchange_that_times_out_asks_the_helper_to_turn_it_off(tmp_path):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    config = _config(tmp_path, wait_s=0.3)
    client = TestClient(create_app(config, SimpleNamespace(config=config, state=None)))
    response = client.post("/api/v1/host/ssh/password", headers=_admin(), json={"minutes": 5})
    assert response.status_code == 503 and response.json()["error"]["code"] == "SSH_ACCESS_UNAVAILABLE"
    # Best effort, not awaited: a helper that starts late turns off what nobody received.
    left = json.loads((tmp_path / helper.REQUEST).read_text(encoding="utf-8"))
    assert left["action"] == "password_off" and set(left) == helper.HEADER_KEYS
    assert helper.read_request(tmp_path / helper.REQUEST, time.time()) == left


def test_only_a_password_on_timeout_leaves_a_password_off_behind(tmp_path):
    request, response = tmp_path / "request", tmp_path / "response"
    for action, expected in (("password_on", "password_off"), ("list", None), ("password_off", None)):
        with pytest.raises(ssh_handoff.HandoffUnavailable):
            ssh_handoff.exchange(action, "a", {"minutes": 5} if action == "password_on" else {},
                                 request_path=str(request), response_path=str(response), wait_s=0.05)
        left = json.loads(request.read_text(encoding="utf-8"))["action"] if request.exists() else None
        assert left == expected, action
        request.unlink(missing_ok=True)


@pytest.mark.parametrize("lock_s,exchange_wait", [(0.4, 0.6), (1.0, None), (3.0, None)])
def test_the_lock_wait_and_the_exchange_share_one_deadline(tmp_path, monkeypatch, lock_s, exchange_wait):
    pytest.importorskip("httpx")
    from core_api_web.api.v1 import host_ssh
    from fastapi.testclient import TestClient

    config = _config(tmp_path, wait_s=1.0)
    client = TestClient(create_app(config, SimpleNamespace(config=config, state=None)))
    now = [100.0]
    seen = []

    class SlowLock:
        """Held by another exchange for `lock_s` of the caller's time."""

        def acquire(self, timeout):
            now[0] += min(lock_s, timeout)
            return lock_s < timeout

        def release(self):
            pass

    def exchange(action, by, params, **kwargs):
        seen.append(kwargs["wait_s"])
        raise ssh_handoff.HandoffUnavailable("no answer")

    monkeypatch.setattr(host_ssh, "time", SimpleNamespace(monotonic=lambda: now[0]))
    monkeypatch.setattr(host_ssh, "_exchange_lock", SlowLock())
    monkeypatch.setattr(ssh_handoff, "exchange", exchange)
    response = client.get("/api/v1/host/ssh/keys", headers=_admin())
    assert response.status_code == 503 and response.json()["error"]["code"] == "SSH_ACCESS_UNAVAILABLE"
    assert seen == ([] if exchange_wait is None else [pytest.approx(exchange_wait)])
    assert now[0] - 100.0 <= 1.0 + 1e-9  # the lock never waits past the shared deadline


@pytest.mark.parametrize("path", ["/api/v1/host/ssh/keys", "/api/v1/host/ssh/password"])
def test_malformed_json_is_a_400_envelope_that_never_reaches_root(robot, path):
    response = robot.client.post(path, headers={**_admin(), "Content-Type": "application/json"},
                                 content=b"{not json")
    assert response.status_code == 400, response.text
    assert set(response.json()) == {"error"} and response.json()["error"]["code"]
    assert robot.helper.runs == 0


# --- second review: CORE's real deadline and a pending password_off ---------------------


def _capture_requests(request: Path) -> tuple[list, callable]:
    seen: list = []

    def sleep(_seconds):
        if request.exists():
            seen.append(json.loads(request.read_text(encoding="utf-8")))
        time.sleep(0.01)

    return seen, sleep


def test_the_request_carries_when_core_stops_waiting(tmp_path):
    request, response = tmp_path / "request", tmp_path / "response"
    seen, sleep = _capture_requests(request)
    before = time.time()
    with pytest.raises(ssh_handoff.HandoffUnavailable):
        ssh_handoff.exchange("list", "a", {}, request_path=str(request), response_path=str(response),
                             wait_s=0.3, sleep=sleep)
    assert seen and set(seen[0]) == helper.HEADER_KEYS
    assert before + 0.2 <= seen[0]["answer_by"] <= time.time() + 0.05


def test_a_pending_password_off_is_never_overwritten(tmp_path):
    request, response = tmp_path / "request", tmp_path / "response"
    off = ssh_handoff.build_request("password_off", "a", {})
    ssh_handoff.write_request(str(request), off)
    with pytest.raises(ssh_handoff.HandoffUnavailable):
        ssh_handoff.exchange("password_on", "a", {"minutes": 5}, request_path=str(request),
                             response_path=str(response), wait_s=0.2)
    assert json.loads(request.read_text(encoding="utf-8"))["request_id"] == off["request_id"]


def test_a_pending_password_off_is_waited_for_until_it_is_consumed(tmp_path):
    request, response = tmp_path / "request", tmp_path / "response"
    ssh_handoff.write_request(str(request), ssh_handoff.build_request("password_off", "a", {}))
    seen = []

    def sleep(_seconds):
        current = json.loads(request.read_text(encoding="utf-8")) if request.exists() else None
        seen.append(current and current["action"])
        if current and current["action"] == "password_off":
            request.unlink()  # the helper consumed it
        time.sleep(0.01)

    with pytest.raises(ssh_handoff.HandoffUnavailable):
        ssh_handoff.exchange("list", "a", {}, request_path=str(request), response_path=str(response),
                             wait_s=0.3, sleep=sleep)
    assert seen[0] == "password_off" and "list" in seen


def test_a_stale_pending_request_is_replaced(tmp_path):
    from datetime import datetime, timedelta, timezone

    request, response = tmp_path / "request", tmp_path / "response"
    old = ssh_handoff.build_request("password_off", "a", {},
                                    now=datetime.now(timezone.utc) - timedelta(seconds=helper.REQUEST_MAX_AGE_S + 5))
    ssh_handoff.write_request(str(request), old)
    seen, sleep = _capture_requests(request)
    with pytest.raises(ssh_handoff.HandoffUnavailable):
        ssh_handoff.exchange("list", "a", {}, request_path=str(request), response_path=str(response),
                             wait_s=0.2, sleep=sleep)
    assert seen and seen[0]["action"] == "list"
