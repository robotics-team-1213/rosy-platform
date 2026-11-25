"""Native B admission, deadline and UDS peer tests; no motor or fake completion receipts."""
import json
import os
from pathlib import Path
import socket
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
from native_policy_fence import NativePolicyFence
from native_policy_owner import handle


PINS = {"workcell_id": "test-workcell", "policy_digest": "a" * 64, "rig_revision": "rig",
        "calibration_revision": "cal", "scope": "cell-task:test:arm_b"}


def grant(seq=1, **changes):
    return {**PINS, "lease_id": "lease-1", "episode_id": "episode-1", "seq": seq,
            "ttl_s": 1., "window_remaining_s": 3., **changes}


def test_native_fence_expiry_while_idle_latches_without_a_writer(tmp_path):
    fence = NativePolicyFence(PINS, tmp_path / "episodes.db")
    try:
        with pytest.raises(PermissionError):
            fence.require_current()
        deadline = time.monotonic_ns() + 100_000_000
        assert fence.receive(fence.owner_session_id, deadline, grant()) == deadline
        fence.require_current()
        fence._watch.join(timeout=1.5)  # no caller touched the fence while time ran out
        assert not fence._watch.is_alive()
        with pytest.raises(PermissionError):
            fence.require_current()
        assert fence.status()["hold_reason"] == "policy_lease_expired"
        with pytest.raises(PermissionError):
            fence.receive(fence.owner_session_id, time.monotonic_ns()+800_000_000, grant(2))
    finally:
        fence.close()


def test_native_fence_rejects_replay_across_sessions_and_uncurrent_grants(tmp_path):
    now = [1_000_000_000]
    def open_session():
        return NativePolicyFence(PINS, tmp_path / "journal", clock=lambda: now[0])

    fence = open_session()
    try:
        session = fence.owner_session_id
        fence.receive(session, now[0]+500_000_000, grant())
        now[0] += 100_000_000
        fence.receive(session, now[0]+500_000_000, grant(2))
        with pytest.raises(PermissionError):
            fence.receive(session, now[0]+700_000_000, grant(2))
        assert not fence.status()["lease_current"]
    finally:
        fence.close()
    for session_id, change, offset in [
        (session, {}, 400_000_000), (None, {}, 400_000_000),  # stale owner session; durable tombstone
        (None, {"episode_id": "unused", "lease_id": "unused", "seq": 2}, 500_000_000),
        (None, {"scope": "cell-task:test:arm_a"}, 400_000_000),
        (None, {"policy_digest": "b"*64}, 400_000_000), (None, {"rig_revision": "other"}, 400_000_000),
        (None, {"calibration_revision": "other"}, 400_000_000),
        (None, {}, 0), (None, {}, 1_000_000_001),
    ]:
        fence = open_session()
        try:
            with pytest.raises(PermissionError):
                fence.receive(session_id or fence.owner_session_id, now[0]+offset, grant(**change))
            assert fence.status()["hold_reason"] == "policy_grant_refused"
        finally:
            fence.close()


@pytest.mark.skipif(not hasattr(socket, "SO_PEERCRED"), reason="Linux UDS peer credentials")
def test_authenticated_owner_socket_reports_unarmed_and_never_confirms_motor_hold(tmp_path):
    fence = NativePolicyFence(PINS, tmp_path / "journal")
    def request(body, uid):
        left, right = socket.socketpair()
        with left, right:
            left.sendall(json.dumps(body).encode() + b"\n")
            return handle(right, {"core_uid": uid, "arm_id": "arm_b"}, fence)
    try:
        assert request({"op":"status"}, os.getuid()+1) == {"accepted":False, "reason":"core_peer_required"}
        status = request({"op":"status"}, os.getuid())
        assert status["ready"] is False and status["arm_id"] == "arm_b" and status["lease_current"] is False
        refused = request({"op":"lease", "owner_session_id":status["owner_session_id"],
                           "not_after_monotonic_ns":time.monotonic_ns()+1_000_000, "grant":grant()}, os.getuid())
        assert refused == {"accepted":False, "reason":"native_motor_writer_not_enrolled"}
        assert not fence.status()["lease_current"]
        refused = request({"op":"hold", "reason":"window_closed"}, os.getuid())
        assert refused == {"accepted":False, "reason":"motor_hold_unconfirmed"}
        assert fence.status()["hold_reason"] == "core_hold"
    finally:
        fence.close()

def test_native_fence_clock_rollback_latches_before_renewal(tmp_path):
    now = [1_000_000_000]
    fence = NativePolicyFence(PINS, tmp_path / "journal", clock=lambda: now[0])
    try:
        fence.receive(fence.owner_session_id, now[0]+900_000_000, grant())
        now[0] -= 1
        assert fence.status()["hold_reason"] == "owner_clock_fault"
        with pytest.raises(PermissionError):
            fence.require_current()
    finally:
        fence.close()


def test_commissioning_readback_retains_fault_and_torque_and_expires_whole_sweep(monkeypatch):
    import native_policy_readback as rb
    now = [1_000]
    rows = [{"id": motor, "model_number": model, "position_raw": -12+motor,
             "torque_enabled": int(motor == 13), "hardware_error": 32 if motor == 11 else 0}
            for motor, (model, _mode) in rb.FOLLOWER_5DOF.items()]
    def read(port, *, allow_fault):
        assert allow_fault is True and port is serial
        return [dict(row) for row in rows]
    serial = object()
    monkeypatch.setattr(rb, "read_motors", read)
    reader = rb.RegisterReadback(serial, clock=lambda: now[0], wall=lambda: 9_000)
    assert reader.snapshot()["state"] == "unavailable"
    reader.collect()
    taken = reader.snapshot()
    assert taken == {"arm_id": "arm_b", "basis": "readonly_motor_registers", "state": "fresh",
                     "observed_at_unix_ns": 9_000, "observed_at_monotonic_ns": 1_000, "motors": rows}
    now[0] += rb.MAX_AGE_NS+1
    assert reader.snapshot() == {"arm_id": "arm_b", "basis": "readonly_motor_registers", "state": "stale"}
    rows.pop()
    reader.collect()
    assert reader.snapshot() == {"arm_id": "arm_b", "basis": "readonly_motor_registers", "state": "unavailable"}


def test_commissioning_readback_refuses_incomplete_and_slow_sweeps(monkeypatch):
    import native_policy_readback as rb
    serial = object()
    rows = [{"id": motor, "model_number": model, "position_raw": 0, "torque_enabled": 0, "hardware_error": 0}
            for motor, (model, _mode) in rb.FOLLOWER_5DOF.items()]
    clock = iter((100, 101+rb.MAX_AGE_NS))
    reader = rb.RegisterReadback(serial, clock=lambda: next(clock))
    monkeypatch.setattr(rb, "read_motors", lambda *_a, **_kw: rows)
    reader.collect()
    assert reader.snapshot()["state"] == "stale" and "motors" not in reader.snapshot()
    for key, value in (("id", 12), ("model_number", 1200), ("torque_enabled", True), ("hardware_error", 300)):
        with pytest.raises(ValueError):
            rb.motor_rows([{**rows[0], key: value}, *rows[1:]])


@pytest.mark.skipif(not hasattr(socket, "SO_PEERCRED"), reason="Linux UDS peer credentials")
def test_commissioning_socket_requires_authenticated_core_and_never_acknowledges_motion(tmp_path):
    fence = NativePolicyFence(PINS, tmp_path / "journal")
    class Sample:
        def snapshot(self):
            return {"arm_id": "arm_b", "basis": "readonly_motor_registers", "state": "unavailable"}
    def request(body, uid):
        left, right = socket.socketpair()
        with left, right:
            left.sendall(json.dumps(body).encode()+b"\n")
            return handle(right, {"core_uid": uid, "arm_id": "arm_b"}, fence, Sample())
    try:
        assert "hardware_readback" not in request({"op":"status"}, os.getuid()+1)
        status = request({"op":"status"}, os.getuid())
        assert status["hardware_readback"] == Sample().snapshot() and status["ready"] is False
        assert not request({"op":"lease","owner_session_id":status["owner_session_id"],
                            "not_after_monotonic_ns":time.monotonic_ns()+1_000_000,"grant":grant()}, os.getuid())["accepted"]
        assert request({"op":"hold","reason":"operator"}, os.getuid()) == {
            "accepted":False, "reason":"motor_hold_unconfirmed"}
    finally:
        fence.close()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="requires Linux fdinfo flock evidence")
def test_readback_requires_live_b_handoff_lock_descriptions(tmp_path, monkeypatch):
    import fcntl
    import native_policy_readback as rb
    monkeypatch.setenv("ROSY_OMX_HOME", str(tmp_path))
    with (tmp_path/"session.lock").open("a") as cell, (tmp_path/"session-arm_b.lock").open("a") as arm:
        fcntl.flock(cell, fcntl.LOCK_SH)
        fcntl.flock(arm, fcntl.LOCK_EX)
        monkeypatch.setenv(rb.HELD_ENV, f"arm_b:{cell.fileno()}:{arm.fileno()}")
        rb.check_inherited_locks()
        fcntl.flock(arm, fcntl.LOCK_UN)
        with pytest.raises(PermissionError):
            rb.check_inherited_locks()
        monkeypatch.setenv(rb.HELD_ENV, f"arm_s:{cell.fileno()}:{arm.fileno()}")
        with pytest.raises(PermissionError):
            rb.check_inherited_locks()
