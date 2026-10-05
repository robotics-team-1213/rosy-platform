"""Seat and journal admission share one atomic owner-local boundary."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, RLock
from types import SimpleNamespace

import pytest

from omx_adapter.action_store import ActionStore
from omx_adapter.control_seat_admission import ControlSeatAdmission


def setup(tmp_path):
    owner = SimpleNamespace(session_id="session-a", config=SimpleNamespace(
        workcell_id="cell", instance_id="instance"), state="ready")
    clock = [10.0]
    owner_lock = RLock()
    def run_policy(operation):
        with owner_lock:
            return operation(owner.state)
    owner.run_admission_policy = run_policy
    store = ActionStore(tmp_path / "actions.sqlite3")
    admission = ControlSeatAdmission(owner, store, monotonic=lambda: clock[0])
    return owner, store, admission, clock


def test_canonical_owner_final_gate_rejects_a_revoked_queued_command(tmp_path):
    from dataclasses import replace
    from test_omx_command_owner import FakeActionClient, make_config, make_state, make_command
    from omx_adapter.command_owner import ArmCommandOwner
    client = FakeActionClient()
    owner = ArmCommandOwner(replace(make_config(), allowed_owners=("pilot_sim", "rule_based")),
                            client, monotonic=lambda: 10.0, session_id="session-01")
    store = ActionStore(tmp_path / "gate.sqlite3")
    admission = ControlSeatAdmission(owner, store, monotonic=lambda: 10.0)
    owner.bind_control_admission(admission)
    owner.observe_joint_state(make_state(received_at=10.0))
    admission.acquire("token", "seat", ttl_s=10)
    command = replace(make_command(), owner="pilot_sim")
    admission.reserve_pilot("seat", command.command_id)
    admission.release("token", "seat")
    assert owner.submit(command).reason == "control_seat_fenced"
    assert not client.commands


def journal(store):
    return store.create_action(
        workcell_id="cell", instance_id="instance", principal_id="fleet",
        request_key="request", action_id="action", action_kind="CELL_TRANSFER",
        configuration_revision="config", observation_id="", owner_generation=1,
        payload={"cell": "job"})


def test_unresolved_prepared_action_blocks_seat_and_seat_blocks_journal(tmp_path):
    _, store, admission, _ = setup(tmp_path)
    admission.run_action_admission(lambda: journal(store))
    with pytest.raises(PermissionError, match="unresolved"):
        admission.acquire("token", "seat", ttl_s=10)
    _, other, admission, _ = setup(tmp_path / "other")
    admission.acquire("token", "seat", ttl_s=10)
    with pytest.raises(PermissionError, match="seat"):
        admission.run_action_admission(lambda: journal(other))
    assert other.get_action("action") is None


def test_acquire_and_journal_race_have_exactly_one_winner(tmp_path):
    _, store, admission, _ = setup(tmp_path)
    barrier = Barrier(2)
    def compete(operation):
        barrier.wait(timeout=3)
        try:
            operation()
            return True
        except PermissionError:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(compete, lambda: admission.acquire("token", "seat", ttl_s=10))
        second = pool.submit(compete, lambda: admission.run_action_admission(lambda: journal(store)))
        assert sum([first.result(timeout=3), second.result(timeout=3)]) == 1


def test_cancel_request_and_wrong_goal_cannot_release_revoked_seat(tmp_path):
    owner, store, admission, _ = setup(tmp_path)
    admission.acquire("token", "seat", ttl_s=10)
    admission.reserve_pilot("seat", "goal")
    admission.note_goal("goal", "GOAL_ACCEPTED", "ros-goal")
    admission.release("token", "seat")
    admission.note_goal("goal", "CANCEL_ACK", "ros-goal")
    admission.note_goal("goal", "TERMINAL_RESULT", "different-goal")
    with pytest.raises(PermissionError):
        admission.run_action_admission(lambda: journal(store))
    owner.state = "hold"
    admission.note_goal("goal", "TERMINAL_RESULT", "ros-goal")
    with pytest.raises(PermissionError):
        admission.run_action_admission(lambda: journal(store))
    owner.state = "ready"  # Canonical explicit owner recovery already occurred.
    admission.run_action_admission(lambda: journal(store))


def test_expiry_revokes_queued_pilot_and_owner_restart_does_not_clear_it(tmp_path):
    owner, store, admission, clock = setup(tmp_path)
    admission.acquire("token", "seat", ttl_s=10)
    admission.reserve_pilot("seat", "goal")
    clock[0] = 20.0
    assert admission.check_command(SimpleNamespace(owner="pilot_sim", command_id="goal",
                                                  session_id="session-a")) is False
    owner.session_id = "session-b"
    with pytest.raises(PermissionError, match="session"):
        admission.run_action_admission(lambda: journal(store))


def test_cell_runner_without_shared_admission_fails_before_journaling(tmp_path):
    from test_omx_action_api import FakePhaseExecution, _runner
    from test_omx_cell_transfer_runner import _action_runner, _kind
    store, driver, base = _runner(tmp_path)
    runner = _action_runner(store, driver, base, phase_runner_factories={
        "CELL_TRANSFER": lambda grant, recorder: FakePhaseExecution(recorder)}, control_admission=None)
    with pytest.raises(PermissionError, match="shared control admission"):
        runner.submit(_kind("CELL_TRANSFER"), peer_uid=1001)
    assert store.get_action("action-1") is None


def test_http_sessions_claim_and_revoke_shared_admission(tmp_path):
    from fastapi import HTTPException
    from omx_adapter.pilot_sim_api import _Sessions
    _, store, admission, clock = setup(tmp_path)
    sessions = _Sessions("operator-code", clock=lambda: clock[0], control_admission=admission)
    token = sessions.pair("operator-code")
    seat = sessions.acquire(token)
    with pytest.raises(PermissionError):
        admission.run_action_admission(lambda: journal(store))
    admission.reserve_pilot(seat, "pending")
    sessions.release(token, seat)
    with pytest.raises(PermissionError):
        admission.run_action_admission(lambda: journal(store))
    with pytest.raises(HTTPException) as error:
        sessions.acquire(token)
    assert error.value.status_code == 409


def test_pilot_runtime_reserves_before_send_and_revoked_seat_sends_nothing(tmp_path):
    from test_pilot_sim_runtime import Arm, jog
    from omx_adapter.pilot_sim_runtime import PilotSimRuntime
    arm = Arm()
    _, store, admission, _ = setup(tmp_path)
    arm.control_admission = admission
    admission.owner = arm.owner
    admission.session_id = arm.owner.session_id
    arm.owner.run_admission_policy = lambda operation: operation(arm.owner.state)
    admission.acquire("token", "seat", ttl_s=10)
    runtime = PilotSimRuntime(arm)
    runtime.snapshot()
    admission.release("token", "seat")
    assert runtime.submit(jog()).get("reason") == "control_seat_fenced"
    assert not arm.commands


def test_process_restart_retains_pending_pilot_fence(tmp_path):
    owner, store, admission, _ = setup(tmp_path)
    admission.acquire("token", "seat", ttl_s=10)
    admission.reserve_pilot("seat", "pending-before-send")
    owner.session_id = "new-process"
    restarted = ControlSeatAdmission(owner, store, monotonic=lambda: 30)
    with pytest.raises(PermissionError, match="persistent"):
        restarted.run_action_admission(lambda: journal(store))
    with pytest.raises(PermissionError, match="persistent"):
        restarted.acquire("new-token", "new-seat", ttl_s=10)


def test_release_does_not_wait_on_blocking_ros_send_or_unfence_cell(tmp_path):
    from test_omx_command_owner import FakeActionClient, make_config, make_state, make_command
    from omx_adapter.command_owner import ArmCommandOwner
    entered, finish = Event(), Event()
    class BlockingPort(FakeActionClient):
        def send_goal(self, command):
            entered.set()
            assert finish.wait(timeout=5)
            return super().send_goal(command)
    client = BlockingPort()
    owner = ArmCommandOwner(make_config(allowed_owners=("pilot_sim", "rule_based")), client,
                            monotonic=lambda: 100, session_id="session-01")
    store = ActionStore(tmp_path / "blocked.sqlite3")
    admission = ControlSeatAdmission(owner, store, monotonic=lambda: 100)
    owner.bind_control_admission(admission)
    owner.observe_joint_state(make_state())
    admission.acquire("token", "seat", ttl_s=10)
    admission.reserve_pilot("seat", "cmd-1")
    with ThreadPoolExecutor(max_workers=2) as pool:
        sending = pool.submit(owner.submit, make_command(owner="pilot_sim"))
        assert entered.wait(timeout=3)
        releasing = pool.submit(admission.release, "token", "seat")
        try:
            releasing.result(timeout=1)
            assert not admission.check_command(make_command(owner="rule_based"))
        finally:
            finish.set()
        assert sending.result(timeout=3).accepted
    with pytest.raises(PermissionError):
        admission.run_action_admission(lambda: None)
    assert admission._durable.has_pending()


def test_expired_seat_exact_terminal_and_ready_allow_reacquire(tmp_path):
    owner, store, admission, clock = setup(tmp_path)
    admission.acquire("token", "seat", ttl_s=10)
    admission.reserve_pilot("seat", "goal")
    admission.note_goal("goal", "GOAL_ACCEPTED", "ros-goal")
    clock[0] = 21
    admission.expire_seat()
    owner.state = "hold"
    admission.note_goal("goal", "TERMINAL_RESULT", "ros-goal")
    with pytest.raises(PermissionError):
        admission.acquire("token", "new-seat", ttl_s=10)
    owner.state = "ready"
    admission.acquire("token", "new-seat", ttl_s=10)
    assert not admission._durable.has_pending()


def test_runtime_goal_identity_is_durable_and_unknown_send_stays_fenced(tmp_path):
    from uuid import uuid4
    from test_pilot_sim_runtime import Arm, jog, event
    from omx_adapter.pilot_sim_runtime import PilotSimRuntime
    arm = Arm()
    arm.owner.run_admission_policy = lambda operation: operation(arm.owner.state)
    store = ActionStore(tmp_path / "runtime.sqlite3")
    admission = ControlSeatAdmission(arm.owner, store)
    arm.control_admission = admission
    admission.acquire("token", "seat", ttl_s=10)
    runtime = PilotSimRuntime(arm)
    runtime.snapshot()
    runtime.submit(jog())
    ros_goal = str(uuid4())
    runtime.on_goal_event(event("GOAL_ACCEPTED", ros_goal))
    admission.release("token", "seat")
    runtime.cancel_active()
    runtime.on_goal_event(event("CANCEL_ACK", ros_goal, 2, cancel_acknowledged=True))
    with pytest.raises(PermissionError):
        admission.run_action_admission(lambda: None)
    runtime.on_goal_event(event("TERMINAL_RESULT", str(uuid4()), 3, status=5))
    arm.owner.state = "ready"
    with pytest.raises(PermissionError):
        admission.run_action_admission(lambda: None)
    runtime.on_goal_event(event("TERMINAL_RESULT", ros_goal, 4, status=5))
    admission.run_action_admission(lambda: None)
    assert not admission._durable.has_pending()


def test_unknown_send_persists_pending_and_preload_cannot_follow_release(tmp_path):
    from omx_adapter.command_owner import CommandDecision
    from omx_adapter.pilot_sim_runtime import PilotSimRuntime
    from test_pilot_sim_runtime import Arm, jog
    arm = Arm()
    arm.owner.run_admission_policy = lambda operation: operation(arm.owner.state)
    store = ActionStore(tmp_path / "lost-reply.sqlite3")
    admission = ControlSeatAdmission(arm.owner, store)
    arm.control_admission = admission
    admission.acquire("token", "seat", ttl_s=10)
    def lost_reply(command):
        assert admission._durable.has_pending()  # Committed before the send call.
        arm.owner.state = "hold"
        return CommandDecision(False, "hold", "action_submission_failed", command.command_id)
    arm.submit = lost_reply
    runtime = PilotSimRuntime(arm)
    runtime.snapshot()
    assert runtime.submit(jog())["reason"] == "action_submission_failed"
    admission.release("token", "seat")
    arm.owner.state = "ready"
    with pytest.raises(PermissionError):
        admission.run_action_admission(lambda: None)
    with pytest.raises(PermissionError):
        admission.reserve_hold("hold-request", source_command_id="request")
    assert admission._durable.has_pending()


@pytest.mark.parametrize("bad_clock", [float("nan"), float("inf"), 9.0])
def test_clock_failure_cannot_extend_or_dispatch_seat(tmp_path, bad_clock):
    _, _, admission, clock = setup(tmp_path)
    admission.acquire("token", "seat", ttl_s=10)
    clock[0] = bad_clock
    with pytest.raises(PermissionError, match="clock"):
        admission.reserve_pilot("seat", "goal")


def test_canonical_cli_forwards_exact_terminal_to_shared_pilot(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path
    from uuid import uuid4
    from test_pilot_sim_runtime import Arm, jog, event
    from omx_adapter.pilot_sim_runtime import PilotSimRuntime
    repo = Path(__file__).resolve().parents[6]
    monkeypatch.setenv("ROSY_SIM_REPO", str(repo))
    spec = importlib.util.spec_from_file_location("cell_owner_entrypoint", repo / "deploy/robot/omx/run_cell_owner.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    arm = Arm()
    arm.owner.run_admission_policy = lambda operation: operation(arm.owner.state)
    store = ActionStore(tmp_path / "cli.sqlite3")
    admission = ControlSeatAdmission(arm.owner, store)
    arm.control_admission = admission
    admission.acquire("token", "seat", ttl_s=10)
    facade = PilotSimRuntime(arm)
    holder = {"pilot": facade}
    facade.snapshot()
    facade.submit(jog())
    ros_goal = str(uuid4())
    cli.forward_pilot_event(holder, event("GOAL_ACCEPTED", ros_goal))
    admission.release("token", "seat")
    facade.cancel_active()
    cli.forward_pilot_event(holder, event("TERMINAL_RESULT", ros_goal, 2, status=5))
    assert facade.goal("request")["state"] == "CANCELED"
    arm.owner.state = "ready"
    admission.run_action_admission(lambda: None)
    assert not admission._durable.has_pending()


@pytest.mark.parametrize("revoke", ["release", "expiry", "live"])
def test_preload_requires_its_original_live_seat(tmp_path, revoke):
    from dataclasses import replace
    from uuid import uuid4
    from test_pilot_sim_runtime import Arm, event
    from omx_adapter.pilot_sim_runtime import PilotSimRuntime
    arm = Arm()
    arm.owner.run_admission_policy = lambda operation: operation(arm.owner.state)
    clock = [10.0]
    admission = ControlSeatAdmission(arm.owner, ActionStore(tmp_path / "preload.sqlite3"),
                                     monotonic=lambda: clock[0])
    arm.control_admission = admission
    admission.acquire("a", "seat-a", ttl_s=10)
    runtime = PilotSimRuntime(arm, gripper_open=.1, gripper_closed=0.,
                              gripper_velocity=.1, gripper_preload=.01)
    admission.reserve_pilot("seat-a", "request")
    runtime._goals["request"] = {"state": "LOCAL_ACCEPTED"}
    runtime._gripper_goal = ("request", 0.)
    arm.latest_joint_state = replace(arm.latest_joint_state, positions={"joint1": 0., "gripper_joint_1": .07})
    goal = str(uuid4())
    runtime.on_goal_event(event("GOAL_ACCEPTED", goal))
    runtime.on_goal_event(event("TERMINAL_RESULT", goal, 2, status=4, result_code=0))
    assert runtime._hold_pending
    if revoke == "live":
        runtime._issue_hold()
        assert [command.command_id for command in arm.commands] == ["hold-request"]
        return
    if revoke == "release":
        admission.release("a", "seat-a")
        runtime.cancel_active()
    else:
        clock[0] = 21
        admission.expire_seat()
        # Reacquisition can beat the asynchronous watchdog cancellation side effect.
    admission.acquire("b", "seat-b", ttl_s=10)
    runtime._issue_hold()
    assert not arm.commands


def test_wall_expiry_revokes_queued_goal_while_owner_clock_is_paused(tmp_path):
    from omx_adapter.pilot_sim_api import _Sessions
    owner, _, admission, owner_clock = setup(tmp_path)
    wall_clock = [100.0]
    sessions = _Sessions("operator-code", clock=lambda: wall_clock[0], control_admission=admission)
    token = sessions.pair("operator-code")
    seat = sessions.acquire(token)
    admission.reserve_pilot(seat, "queued")
    wall_clock[0] = 111.0
    assert owner_clock[0] == 10.0
    assert sessions.expire_seat()
    assert not admission.check_command(SimpleNamespace(owner="pilot_sim", command_id="queued",
                                                       session_id=owner.session_id))
    with pytest.raises(PermissionError):
        admission.reserve_hold("preload", source_command_id="queued")


def test_delayed_old_seat_cleanup_does_not_cancel_new_seat_goal(tmp_path):
    from test_pilot_sim_runtime import Arm, jog
    from omx_adapter.pilot_sim_runtime import PilotSimRuntime
    arm = Arm()
    arm.owner.run_admission_policy = lambda operation: operation(arm.owner.state)
    admission = ControlSeatAdmission(arm.owner, ActionStore(tmp_path / "cleanup.sqlite3"),
                                     monotonic=lambda: 10.0)
    arm.control_admission = admission
    admission.acquire("a", "seat-a", ttl_s=10)
    admission.release("a", "seat-a")
    admission.acquire("b", "seat-b", ttl_s=10)
    runtime = PilotSimRuntime(arm)
    runtime.snapshot()
    result = runtime.submit(jog().model_copy(update={"seat_id": "seat-b"}))
    assert result["state"] == "LOCAL_ACCEPTED", result
    runtime.cancel_active(seat_id="seat-a")
    assert runtime.goal("request")["state"] == "LOCAL_ACCEPTED"
    assert arm.owner.state == "active"
