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
