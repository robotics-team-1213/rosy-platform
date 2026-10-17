"""Startup must use the canonical stop latch and retain exact cancellation identity."""
from datetime import datetime, timezone
import sys
import threading
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "deploy/robot/omx"))


def fixture(tmp_path, *, fence=None, cancel_error=False):
    from test_platform_cell_owner_assembly import _build, FLEET_UID
    from g2_startup_gate import StartupCommandGate
    owner, _ = _build(tmp_path)
    events, calls = {}, []
    owner.runner.enabled = False
    target = {name: 0.1 for name in owner.runtime.owner.config.joint_names}
    owner.runtime.submit = lambda command: calls.append(("submit", command.command_id)) or NS(accepted=True)

    def cancel(**kwargs):
        calls.append(("cancel", kwargs))
        if cancel_error:
            raise RuntimeError("cancel transport unavailable")
        return NS(reason="cancel_requested", cancel_outcome="call_returned")

    owner.runtime.cancel = cancel
    owner.action_api.stop_api.cancel_active = lambda uid: calls.append(("fleet_cancel", uid)) or []

    def record(name, value):
        if name in events:
            raise FileExistsError(name)
        events[name] = value
        calls.append(("record", name))

    gate = StartupCommandGate(owner, target=target, expected_actor="g2-sim-approver",
                              fleet_fence_current=fence or (lambda epoch, generation: True), record=record)
    owner.stop.rearm(authority_epoch=3, dispatch_generation=8, operator_confirmed=True,
                     fleet_fence_current=lambda epoch, generation: True)
    request = {**gate.challenge, "actor_id": "g2-sim-approver", "authority_epoch": 3,
               "dispatch_generation": 8}
    command = NS(command_id="startup-1", session_id=owner.runtime.owner.session_id,
                 workcell_id=owner.settings.workcell_id, instance_id=owner.settings.instance_id,
                 owner="pilot_sim", positions=target)

    def stop():
        return owner.action_api.dispatch({"version": 1, "operation": "StopLocal",
            "workcell_id": owner.settings.workcell_id, "instance_id": owner.settings.instance_id,
            "authority_epoch": 3, "dispatch_generation": 8,
            "requested_at": datetime.now(timezone.utc).isoformat(), "reason": "startup stop"}, peer_uid=FLEET_UID)

    return NS(owner=owner, gate=gate, request=request, command=command, calls=calls, events=events, stop=stop)


def test_rearm_alone_never_authorizes_startup(tmp_path):
    f = fixture(tmp_path)
    with pytest.raises(PermissionError):
        f.gate.submit(f.command)
    assert not any(row[0] == "submit" for row in f.calls)


@pytest.mark.parametrize("field,value", [("nonce", "other"), ("owner_session_id", "old"),
    ("actor_id", "anonymous"), ("target_sha256", "0" * 64), ("dispatch_generation", 7)])
def test_authorization_binds_challenge_actor_target_and_live_generation(tmp_path, field, value):
    f = fixture(tmp_path)
    with pytest.raises((PermissionError, ValueError)):
        f.gate.authorize({**f.request, field: value})
    assert not any(row[0] == "submit" for row in f.calls)


def test_intent_and_exact_identity_precede_one_fenced_submission(tmp_path):
    f = fixture(tmp_path)
    f.gate.authorize(f.request)
    f.gate.submit(f.command)
    assert f.calls.index(("record", "startup-submit-intent")) < f.calls.index(("submit", "startup-1"))
    assert f.events["startup-submit-intent"]["command_id"] == "startup-1"
    with pytest.raises(PermissionError):
        f.gate.submit(f.command)
    assert [row for row in f.calls if row[0] == "submit"] == [("submit", "startup-1")]


def test_stop_before_submit_prevents_goal(tmp_path):
    f = fixture(tmp_path)
    f.gate.authorize(f.request)
    assert f.stop()["status"] == 200
    with pytest.raises(PermissionError):
        f.gate.submit(f.command)
    assert not any(row[0] == "submit" for row in f.calls)


@pytest.mark.parametrize("cancel_error", [False, True])
def test_stop_before_acceptance_cancels_exact_command_and_still_fans_out(tmp_path, cancel_error):
    f = fixture(tmp_path, cancel_error=cancel_error)
    f.gate.authorize(f.request)
    f.gate.submit(f.command)  # No GOAL_ACCEPTED or result has arrived.
    response = f.stop()
    assert response["status"] == 200 and response["snapshot"]["state"] == "LOCAL_LATCHED"
    assert ("cancel", {"command_id": "startup-1", "owner": "pilot_sim"}) in f.calls
    assert any(row[0] == "fleet_cancel" for row in f.calls)
    with pytest.raises(PermissionError):
        f.gate.complete(lambda: pytest.fail("stop must prevent seat release or runner enable"))
    assert f.owner.runner.enabled is False


def test_generation_changes_during_settling_block_completion_and_cancel(tmp_path):
    current = [True]
    f = fixture(tmp_path, fence=lambda epoch, generation: current[0])
    f.gate.authorize(f.request)
    f.gate.submit(f.command)
    current[0] = False
    with pytest.raises(PermissionError):
        f.gate.assert_current()
    assert ("cancel", {"command_id": "startup-1", "owner": "pilot_sim"}) in f.calls
    with pytest.raises(PermissionError):
        f.gate.complete(lambda: pytest.fail("stale generation must stay HOLD"))


def test_completion_rechecks_live_fence_before_releasing_admission(tmp_path):
    f = fixture(tmp_path)
    f.gate.authorize(f.request)
    f.gate.submit(f.command)
    assert f.gate.complete(lambda: "settled-and-reconciled") == "settled-and-reconciled"


def test_blocked_diagnostic_recording_cannot_delay_any_stop_cancel(tmp_path):
    f = fixture(tmp_path)
    f.gate.authorize(f.request)
    f.gate.submit(f.command)
    entered, release = threading.Event(), threading.Event()
    original_record = f.gate.record
    def record(name, value):
        if name.startswith("startup-cancel"):
            entered.set()
            assert release.wait(timeout=3)
        original_record(name, value)
    f.gate.record = record
    stopped = threading.Thread(target=f.stop)
    stopped.start()
    try:
        assert entered.wait(timeout=2)
        assert ("cancel", {"command_id": "startup-1", "owner": "pilot_sim"}) in f.calls
        assert any(row[0] == "fleet_cancel" for row in f.calls)
    finally:
        release.set()
        stopped.join(timeout=3)
    assert not stopped.is_alive()


def test_prepare_home_without_explicit_gate_refuses_before_seat_or_goal():
    from test_cell_g2_startup import Fixture
    from g2_startup import prepare_home
    f = Fixture()
    with pytest.raises(PermissionError, match="startup"):
        prepare_home(f, f.profile, {"joint1": .2, "gripper": 1.})
    assert f.calls == []
