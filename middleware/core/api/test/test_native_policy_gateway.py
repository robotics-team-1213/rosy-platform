"""Native CORE lease ingress: separate machine identity, per-grant challenge, same-host deadline."""
import os

import pytest
from fastapi.testclient import TestClient

from core_api_web.api.deps import token_digest
from core_api_web.native_policy_gateway import NativeRelay, create_app, exchange

SCOPE = "cell-task:trial-1:arm_b"
TOKEN = "test-native-fleet-lease"
CFG = dict(workcell_id="ab-b", arm_id="arm_b", owner_uid=10001, socket_path="/run/rosy/owner.sock",
           fleet_principal="native-fleet", token_sha256=token_digest(TOKEN))
HEADERS = {"Authorization": "Bearer " + TOKEN}
BASE = "/api/v1/arm/"
GRANT = dict(lease_id="l1", episode_id="e1", workcell_id="ab-b", policy_digest="a" * 64,
             rig_revision="rig/arm_b", calibration_revision="v1", scope=SCOPE, ttl_s=1.0,
             window_remaining_s=5.0, seq=1)


def test_gateway_auth_deadline_scope_and_hold(monkeypatch):
    monkeypatch.setattr(os, "geteuid", lambda: 10002, raising=False)
    clock = [10_000_000_000]
    calls = []
    ready = [True]
    feedback = dict(state="fresh", arm_id="arm_b", basis="readonly_motor_registers",
                    observed_at_unix_ns=1_795_000_000_000_000_000, observed_at_monotonic_ns=9_950_000_000,
                    motors=[dict(id=i, model_number=1060, position_raw=-1, hardware_error=0, torque_enabled=0)
                            for i in range(11, 17)])

    def owner(path, uid, req):
        assert (path, uid) == (CFG["socket_path"], CFG["owner_uid"])
        calls.append(req)
        if req["op"] == "status":
            return dict(ready=ready[0], arm_id="arm_b", owner_session_id="boot-1",
                        reason="native_motor_writer_not_enrolled", hardware_readback=feedback)
        if req["op"] == "hold":
            return {"hold_reason": "core_hold"}
        return {"accepted": True, "lease_expires_at_ns": req["not_after_monotonic_ns"]}

    relay = NativeRelay(CFG, connect=owner, clock=lambda: clock[0])
    client = TestClient(create_app(CFG, relay=relay))
    def post(path, body):
        return client.post(BASE + path, headers=HEADERS, json=body)
    def get_challenge():
        return post("lease-challenge", {"scope": SCOPE, "workcell_id": "ab-b"}).json()["challenge"]

    assert client.get(BASE + "lease-status").status_code == 401
    assert client.get(BASE + "lease-status", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.post(BASE + "actions", headers=HEADERS, json={}).status_code == 404
    status = client.get(BASE + "lease-status", headers=HEADERS).json()
    assert status["ready"] is True and status["hardware_readback"] == {**feedback, "age_ms": 50}
    feedback["motors"][0]["serial"] = "private"
    redacted = client.get(BASE + "lease-status", headers=HEADERS).json()["hardware_readback"]
    assert redacted == {"state": "unavailable", "basis": "readonly_motor_registers", "arm_id": "arm_b"}
    del feedback["motors"][0]["serial"]
    assert post("lease-challenge", {"scope": "cell-task:t1:arm_a", "workcell_id": "ab-b"}).status_code == 409
    nonce = get_challenge()
    clock[0] += 200_000_000
    accepted = post("lease", {**GRANT, "challenge": nonce})
    assert accepted.status_code == 200 and accepted.json()["lease_expires_at_ns"] == 11_000_000_000
    assert calls[-1]["grant"] == GRANT and calls[-1]["owner_session_id"] == "boot-1"
    assert post("lease", {**GRANT, "challenge": nonce}).status_code == 409
    late = get_challenge()
    clock[0] += 1_000_000_001
    assert post("lease", {**GRANT, "challenge": late}).status_code == 409
    stopped = get_challenge()
    assert post("hold", {"reason": "test"}).status_code == 409
    assert post("lease", {**GRANT, "challenge": stopped}).status_code == 409
    assert sum(row["op"] == "lease" for row in calls) == 1
    ready[0] = False
    status = client.get(BASE + "lease-status", headers=HEADERS)
    assert status.json()["reason"] == "native_motor_writer_not_enrolled"
    assert post("lease-challenge", {"scope": SCOPE, "workcell_id": "ab-b"}).status_code == 409


@pytest.mark.skipif(not hasattr(os, "geteuid"), reason="SO_PEERCRED is a Linux transport")
def test_unix_peer_uid_checked_before_any_payload(tmp_path):
    import socket
    if not hasattr(socket, "SO_PEERCRED"):
        pytest.skip("Linux credentials required")
    path = str(tmp_path / "owner.sock")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as srv:
        srv.bind(path)
        srv.listen(1)
        with pytest.raises(PermissionError):
            exchange(path, os.geteuid() + 1, {"op": "lease"})
        peer, _ = srv.accept()
        with peer:
            assert peer.recv(1) == b""
