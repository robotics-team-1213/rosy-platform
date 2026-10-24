"""Early-failure recovery authority, session and HTTP boundary contracts."""
from dataclasses import replace
import importlib
import json
from pathlib import Path
import socket
import threading

import pytest

NATIVE = Path(__file__).resolve().parents[1] / "deploy/robot/pinky_pro/native"


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(NATIVE))
    return importlib.import_module("network_recovery"), importlib.import_module("network_recovery_http")


@pytest.fixture
def rig(modules, tmp_path):
    recovery, http = modules
    state = recovery.RecoveryState(
        boot_id="boot-1", ap_epoch="ap-1", ap_address="10.42.0.1",
        device_uid="device-1", identity_serial="board-1", hardware_serial="board-1",
        firstboot_state="site_wifi_unreachable", core_healthy=False, handoff_supported=True,
    )
    current = [state]
    now = [100.0]
    calls = []

    def network(command, payload):
        calls.append((command, payload))
        return {"job_id": payload.get("request_id", "job-1"), "state": "prepared"}

    record, code = recovery.issue_code(state, now=now[0], uid=0)
    coordinator = recovery.RecoveryCoordinator(lambda: current[0], network, record,
        clock=lambda: now[0], auth_state_path=tmp_path / "auth-state.json")
    return recovery, http, current, now, calls, coordinator, code


@pytest.mark.parametrize("change", [
    {"device_uid": ""}, {"hardware_serial": "another-board"}, {"ap_address": ""},
    {"ap_address": "0.0.0.0"}, {"ap_address": "127.0.0.1"}, {"ap_epoch": ""},
    {"firstboot_state": "SETUP"}, {"firstboot_state": "complete"}, {"core_healthy": True},
])
def test_activation_denies_untrusted_or_normal_states(rig, change):
    recovery, _, current, _, calls, coordinator, _ = rig
    current[0] = replace(current[0], **change)
    assert coordinator.active_state() is None
    with pytest.raises(recovery.RecoveryError):
        coordinator.exchange("ABCDEFGH")
    assert calls == []


def test_issuer_is_root_only_and_stores_only_scrypt_verifier(rig):
    recovery, _, current, now, _, _, _ = rig
    with pytest.raises(PermissionError):
        recovery.issue_code(current[0], now=now[0], uid=1000)
    record, code = recovery.issue_code(current[0], now=now[0], uid=0)
    assert len(code) == 8 and set(code) <= set(recovery.ALPHABET)
    assert code not in json.dumps(record)
    assert record["scope"] == "network-recovery"
    assert record["deadline"] == now[0] + 600


def test_exchange_is_one_use_and_five_failures_burn_code(rig):
    recovery, _, _, _, _, coordinator, code = rig
    for _ in range(5):
        with pytest.raises(recovery.RecoveryError):
            coordinator.exchange("WRONG123")
    with pytest.raises(recovery.RecoveryError):
        coordinator.exchange(code)


def test_session_and_code_have_separate_bounded_lifetime(rig):
    recovery, _, _, now, _, coordinator, code = rig
    session, csrf = coordinator.exchange(code)
    assert session and csrf and session != csrf
    with pytest.raises(recovery.RecoveryError):
        coordinator.exchange(code)
    now[0] += 600
    with pytest.raises(recovery.RecoveryError):
        coordinator.status(session)


def test_expired_code_is_refused(rig):
    recovery, _, _, now, _, coordinator, code = rig
    now[0] += 600
    with pytest.raises(recovery.RecoveryError):
        coordinator.exchange(code)


def test_code_consumption_and_attempts_survive_http_process_restart(rig, tmp_path):
    recovery, _, current, now, _, _, _ = rig
    record, code = recovery.issue_code(current[0], now=now[0], uid=0)
    def restart():
        return recovery.RecoveryCoordinator(lambda: current[0], lambda *_: {}, record,
            clock=lambda: now[0], auth_state_path=tmp_path / "auth-state.json")
    for _ in range(5):
        with pytest.raises(recovery.RecoveryError):
            restart().exchange("WRONG123")
    with pytest.raises(recovery.RecoveryError):
        restart().exchange(code)
    record, code = recovery.issue_code(current[0], now=now[0], uid=0)
    restart().exchange(code)
    with pytest.raises(recovery.RecoveryError):
        restart().exchange(code)


@pytest.mark.parametrize("change", [
    {"ap_epoch": "ap-2"}, {"boot_id": "boot-2"}, {"ap_address": "10.43.0.1"},
    {"core_healthy": True}, {"ap_address": ""},
])
def test_lifecycle_change_permanently_invalidates_session(rig, change):
    recovery, _, current, _, calls, coordinator, code = rig
    session, _ = coordinator.exchange(code)
    original = current[0]
    current[0] = replace(original, **change)
    assert coordinator.active_state() is None
    current[0] = original
    with pytest.raises(recovery.RecoveryError):
        coordinator.status(session)
    assert calls == []


def test_connect_requires_csrf_handoff_and_validated_fields(rig):
    recovery, _, current, _, calls, coordinator, code = rig
    session, csrf = coordinator.exchange(code)
    for supplied, ssid, psk in [("wrong", "site", "password"), (csrf, "", "password"),
                                (csrf, "site", "short")]:
        with pytest.raises(recovery.RecoveryError):
            coordinator.connect(session, supplied, ssid, psk, "request-1")
    current[0] = replace(current[0], handoff_supported=False)
    with pytest.raises(recovery.RecoveryError, match="image_required"):
        coordinator.connect(session, csrf, "site", "password", "request-1")
    assert calls == []


def test_durable_job_and_reconnect_status_use_only_network_socket(rig):
    _, _, _, _, calls, coordinator, code = rig
    session, csrf = coordinator.exchange(code)
    accepted = coordinator.connect(session, csrf, "site", "password", "request-1")
    assert accepted == {"job_id": "request-1", "state": "prepared"}
    assert coordinator.status(session, "request-1")["job_id"] == "request-1"
    assert [call[0] for call in calls] == ["network.connect", "network.status"]
    assert calls[0][1] == {"ssid": "site", "psk": "password", "request_id": "request-1"}


def test_backend_exception_cannot_disclose_credentials(rig):
    recovery, _, _, _, _, coordinator, code = rig
    session, csrf = coordinator.exchange(code)
    def broken(*_):
        raise RuntimeError("secret-password-from-nmcli")
    coordinator.network_call = broken
    with pytest.raises(recovery.RecoveryError) as error:
        coordinator.connect(session, csrf, "site", "password", "request-1")
    assert "secret-password" not in str(error.value)


def test_http_same_origin_cookie_and_body_limits(rig):
    _, http, _, _, calls, coordinator, code = rig
    app = http.RecoveryHTTP(coordinator, fingerprint="AB:" * 31 + "AB")
    headers = {"Host": "10.42.0.1:8443", "Origin": "https://10.42.0.1:8443",
               "Content-Type": "application/json"}
    body = json.dumps({"code": code}).encode()
    for bad in [{"Host": "evil.example"}, {"Origin": "https://evil.example"}, {"Origin": "null"}]:
        assert app.response("POST", "/session", dict(headers, **bad), body)[0] == 403
    assert app.response("POST", "/session", headers, b"x" * 4097)[0] == 413
    status, response_headers, response = app.response("POST", "/session", headers, body)
    assert status == 200
    cookie = response_headers["Set-Cookie"]
    assert all(flag in cookie for flag in ("Secure", "HttpOnly", "SameSite=Strict", "Path=/"))
    assert json.loads(response)["csrf"]
    assert calls == []


def test_public_status_and_errors_have_no_secrets(rig):
    _, http, _, _, calls, coordinator, code = rig
    app = http.RecoveryHTTP(coordinator, fingerprint="AB:" * 31 + "AB")
    status, _, body = app.response("GET", "/status", {"Host": "10.42.0.1:8443"}, b"")
    assert status == 200 and code.encode() not in body
    assert calls == []
    assert app.response("POST", "/reboot", {"Host": "10.42.0.1:8443"}, b"{}")[0] in (403, 404)


def test_tls_failure_never_opens_plaintext_listener(rig, tmp_path):
    _, http, _, _, _, coordinator, _ = rig
    opened = []
    with pytest.raises((OSError, ValueError)):
        http.create_server(coordinator, tmp_path / "missing-cert", tmp_path / "missing-key",
                           server_factory=lambda *args: opened.append(args))
    assert opened == []


def test_connect_acknowledges_durable_job_before_explicit_start(rig):
    _, http, _, _, calls, coordinator, code = rig
    session, csrf = coordinator.exchange(code)
    app = http.RecoveryHTTP(coordinator, fingerprint="AB:" * 31 + "AB")
    headers = {"Host": "10.42.0.1:8443", "Origin": "https://10.42.0.1:8443",
               "Content-Type": "application/json", "Cookie": f"{http.COOKIE}={session}"}
    body = json.dumps({"ssid": "site", "psk": "password", "request_id": "job-1", "csrf": csrf}).encode()
    status, _, response = app.response("POST", "/network/connect", headers, body)
    assert status == 202 and json.loads(response)["state"] == "prepared"
    assert [call[0] for call in calls] == ["network.connect"]
    app.after_response()
    assert calls[-1] == ("network.start", {"request_id": "job-1"})


@pytest.mark.parametrize("raw,status", [
    (b"Content-Length: 4097\r\n", b"413"),
    (b"Content-Length: 1\r\nContent-Length: 2\r\n", b"400"),
    (b"Transfer-Encoding: chunked\r\n", b"400"),
    (b"Host: another.example\r\n", b"400"),
])
def test_http_transport_rejects_oversized_and_ambiguous_framing(rig, raw, status):
    _, http, _, _, calls, coordinator, _ = rig
    app = http.RecoveryHTTP(coordinator, fingerprint="AB:" * 31 + "AB")
    client, server = socket.socketpair()
    worker = threading.Thread(target=http.handler(app), args=(server, ("127.0.0.1", 12345), object()))
    try:
        client.settimeout(1)
        worker.start()
        client.sendall(b"POST /session HTTP/1.1\r\nHost: 10.42.0.1:8443\r\n" + raw + b"\r\n")
        assert status in client.recv(4096).split(b"\r\n", 1)[0]
        worker.join(1)
        assert not worker.is_alive()
        assert calls == []
    finally:
        client.close()
        server.close()


def test_slow_body_has_absolute_deadline(rig, monkeypatch):
    _, http, _, _, calls, coordinator, _ = rig
    monkeypatch.setattr(http, "IO_SECONDS", 0.1)
    app = http.RecoveryHTTP(coordinator, fingerprint="AB:" * 31 + "AB")
    client, server = socket.socketpair()
    worker = threading.Thread(target=http.handler(app), args=(server, ("127.0.0.1", 12345), object()))
    try:
        worker.start()
        client.sendall(b"POST /session HTTP/1.1\r\nHost: 10.42.0.1:8443\r\nContent-Length: 10\r\n\r\nx")
        worker.join(1)
        assert not worker.is_alive()
        assert calls == []
    finally:
        client.close()
        server.close()


def test_auth_state_symlink_refuses_exchange(rig, tmp_path):
    recovery, _, current, now, _, _, _ = rig
    record, code = recovery.issue_code(current[0], now=now[0], uid=0)
    target = tmp_path / "unrelated"
    target.write_text("keep")
    link = tmp_path / "link"
    link.symlink_to(target)
    coordinator = recovery.RecoveryCoordinator(lambda: current[0], lambda *_: {}, record,
        auth_state_path=link, clock=lambda: now[0])
    with pytest.raises(recovery.RecoveryError):
        coordinator.exchange(code)
    assert target.read_text() == "keep"


def test_listener_closes_and_session_is_destroyed_when_core_becomes_healthy(rig, monkeypatch, tmp_path):
    recovery, http, current, _, _, coordinator, code = rig
    session, _ = coordinator.exchange(code)
    closed = []
    class Server:
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            closed.append(True)
        def handle_request(self):
            current[0] = replace(current[0], core_healthy=True)
    monkeypatch.setattr(http, "create_server", lambda *_args, **_kwargs: Server())
    http.serve(coordinator, tmp_path / "cert", tmp_path / "key", assets_dir=tmp_path)
    assert closed == [True]
    current[0] = replace(current[0], core_healthy=False)
    with pytest.raises(recovery.RecoveryError):
        coordinator.status(session)
