"""Actual owner composition advances durable Cell workflow; ROS remains a test port."""
from pathlib import Path
import sys
from types import SimpleNamespace
import threading

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/products/omx/adapter/test"))
from test_platform_cell_owner_assembly import _build, _docs, _grant, _submit
from test_omx_pose_plan import _state
from test_omx_pick_place_runner import _GoalPort, _event
from omx_adapter.kinematics import OmxKinematics
from omx_adapter.action_runner import action_grant_digest
from fleet.server.task_store import FleetTaskStore
from omx_adapter.gripper_contract import GripperObservation
from rosy_agent.omx_cell_owner import sim_gripper_observation


def test_sim_readback_uses_grant_generation_and_distinguishes_open_from_contact(tmp_path):
    owner, _ = _build(tmp_path)
    recipe, cell = _docs()
    c = owner.acceptance.accept_cell(cell, actor_id="operator-1")["cell_sha256"]
    r = owner.acceptance.accept_recipe(recipe, actor_id="operator-1")["recipe_sha256"]
    grant = _grant(owner, c, r)
    for q, expected, held in ((owner.profile.gripper_open, "OPEN", False),
                             (owner.profile.gripper_contact_for_width(.03), "CLOSED", True)):
        state = SimpleNamespace(sequence=15, received_at=100., positions={owner.profile.gripper_joint: q})
        evidence = sim_gripper_observation(owner, state, grant)
        assert evidence.owner_generation == 8
        assert evidence.state == expected and evidence.object_present is held
        assert evidence.object_id == ("box" if held else None)


def _running_owner(tmp_path, *, release_fault=False, delayed=False, fleet_fence_current=None,
                   fence_identity=(2, 8), on_release_readback=None):
    port = _GoalPort()
    holder = {}
    commands = []
    pending = []
    def readback(grant):
        owner = holder["owner"]
        state = owner.runtime.latest_joint_state
        released = port.submissions[-1][0].phase_id == "release"
        if released and on_release_readback is not None:
            on_release_readback()
        return GripperObservation(grant.workcell_id, grant.instance_id,
            "omx-sim-gripper-joint-position-v2", state.sequence, state.received_at,
            "OPEN" if released else "CLOSED", not released,
            None if released else "box", grant.dispatch_generation + (1 if released and release_fault else 0))
    overrides = {} if fleet_fence_current is None else {"fleet_fence_current": fleet_fence_current}
    owner, _ = _build(tmp_path, goal_port_factory=lambda runtime: port, gripper_readback=readback, **overrides)
    holder["owner"] = owner
    snapshot = _state(OmxKinematics.load(), owner.profile)
    owner.runtime.latest_joint_state = SimpleNamespace(sequence=snapshot.sequence,
        positions=snapshot.joint_positions, received_at=100.)
    def succeed(command, goal, callback):
        commands.append(command.phase_id)
        callback(_event("GOAL_ACCEPTED", command, command.phase_id, goal, 1))
        if delayed:
            pending.append((command, goal, callback))
            return
        previous = owner.runtime.latest_joint_state
        owner.runtime.latest_joint_state = SimpleNamespace(sequence=previous.sequence+1,
            positions=dict(command.positions), received_at=100.)
        callback(_event("TERMINAL_RESULT", command, command.phase_id, goal, 2, status=4, result_code=0))
    port.on_submit = succeed
    epoch, generation = fence_identity
    owner.stop.rearm(authority_epoch=epoch, dispatch_generation=generation, operator_confirmed=True,
                     fleet_fence_current=lambda epoch, generation: True)
    recipe, cell = _docs()
    c = owner.acceptance.accept_cell(cell, actor_id="operator-1")["cell_sha256"]
    r = owner.acceptance.accept_recipe(recipe, actor_id="operator-1")["recipe_sha256"]
    grant = _grant(owner, c, r)
    value = grant.model_dump(mode="json")
    value.update(authority_epoch=epoch, dispatch_generation=generation)
    value["request_digest"] = action_grant_digest(value)
    grant = type(grant).model_validate(value)
    response = _submit(owner, grant)
    assert response["status"] == 200 and response["receipt"]["state"] in {"ACCEPTED", "RUNNING"}
    assert commands == ["approach"]
    return owner, grant, port, commands, pending


@pytest.mark.parametrize("release_fault", [False, True])
def test_built_owner_sequences_four_phases_and_requires_release_evidence(tmp_path, release_fault):
    owner, grant, port, commands, _ = _running_owner(tmp_path, release_fault=release_fault)
    for _ in range(5):
        owner.advance_pending()
    assert commands == ["approach", "grasp", "transfer", "release"]
    assert owner.store.get_action(grant.action_id)["state"] == ("HOLD" if release_fault else "SUCCEEDED")
    for _ in range(3):
        owner.advance_pending()
    assert len(commands) == 4


def test_pending_phase_and_late_success_after_cancel_never_start_next_phase(tmp_path):
    from datetime import datetime, timezone
    owner, grant, port, commands, pending = _running_owner(tmp_path, delayed=True)
    for _ in range(3):
        owner.advance_pending()
    assert commands == ["approach"]
    cancel = owner.action_api.dispatch({"version": 2, "operation": "CancelAction",
        "action_id": grant.action_id, "attempt_id": grant.attempt_id, "reason": "SITE_STOP",
        "requested_at": datetime.now(timezone.utc).isoformat()}, peer_uid=1001)
    assert cancel["status"] == 200
    assert owner.store.get_action(grant.action_id)["state"] == "HOLD"
    command, goal, callback = pending[0]
    callback(_event("TERMINAL_RESULT", command, command.phase_id, goal, 2, status=4, result_code=0))
    for _ in range(3):
        owner.advance_pending()
    assert commands == ["approach"]
    assert owner.store.get_action(grant.action_id)["state"] == "HOLD"


def test_restart_keeps_local_stop_closed_and_does_not_restore_execution(tmp_path):
    owner, grant, port, commands, pending = _running_owner(tmp_path, delayed=True)
    reopened, _ = _build(tmp_path)
    for _ in range(3):
        reopened.advance_pending()
    assert commands == ["approach"]
    assert reopened._executions == {}
    assert not reopened.stop.is_open(authority_epoch=grant.authority_epoch,
                                     dispatch_generation=grant.dispatch_generation)
    assert reopened.store.get_action(grant.action_id)["state"] == "ACCEPTED"


@pytest.mark.parametrize("failure", [False, 1, "unavailable"])
def test_live_fleet_fence_loss_cancels_exact_goal_and_closes_local_stop(tmp_path, failure):
    current = {"value": True}
    def fleet_fence(epoch, generation):
        assert (epoch, generation) == (2, 8)
        if current["value"] == "unavailable":
            raise OSError("Fleet state unavailable")
        return current["value"]
    owner, grant, port, commands, pending = _running_owner(
        tmp_path, delayed=True, fleet_fence_current=fleet_fence)
    current["value"] = failure
    owner.advance_pending()
    assert port.cancelled == [pending[0][1]]
    assert owner.store.get_action(grant.action_id)["state"] == "HOLD"
    assert not owner.stop.is_open(authority_epoch=2, dispatch_generation=8)
    command, goal, callback = pending[0]
    callback(_event("TERMINAL_RESULT", command, command.phase_id, goal, 2, status=4, result_code=0))
    owner.advance_pending()
    assert commands == ["approach"] and owner._executions == {}


def test_fleet_fence_changes_after_rearm_rejects_before_action_journaling(tmp_path):
    current = {"value": True}
    owner, _ = _build(tmp_path, fleet_fence_current=lambda epoch, generation: current["value"])
    owner.stop.rearm(authority_epoch=2, dispatch_generation=8, operator_confirmed=True,
                     fleet_fence_current=lambda epoch, generation: True)
    recipe, cell = _docs()
    c = owner.acceptance.accept_cell(cell, actor_id="operator-1")["cell_sha256"]
    r = owner.acceptance.accept_recipe(recipe, actor_id="operator-1")["recipe_sha256"]
    grant = _grant(owner, c, r)
    current["value"] = False
    assert _submit(owner, grant)["status"] == 403
    assert owner.store.get_action(grant.action_id) is None


@pytest.mark.parametrize("restart", [False, True])
@pytest.mark.parametrize("pending_phase", [False, True])
def test_actual_fleet_stop_or_restart_fences_owner_and_never_advances(tmp_path, restart, pending_phase):
    fleet = FleetTaskStore(tmp_path / "fleet.sqlite3")
    opened = fleet.rearm_dispatch(expected_generation=0, actor_id="operator-1")
    def current_fence(epoch, generation):
        control = fleet.dispatch_control()
        return (control["dispatch_enabled"] and control["authority_epoch"] == epoch
                and control["generation"] == generation)
    owner, grant, port, commands, pending = _running_owner(
        tmp_path / "owner", delayed=pending_phase, fleet_fence_current=current_fence,
        fence_identity=(opened["authority_epoch"], opened["generation"]))
    if restart:
        stopped = fleet.close_dispatch_for_startup()
        assert stopped["authority_epoch"] > grant.authority_epoch
    else:
        stopped = fleet.trip_stop_latch(actor_id="operator-1")
        assert stopped["generation"] > grant.dispatch_generation
    if pending_phase:
        owner.advance_pending()
        assert port.cancelled == [pending[0][1]]
    else:
        # Exercise the final next-phase submission guard separately from the owner timer.
        owner._executions[grant.action_id][1].advance()
    assert commands == ["approach"]
    assert owner.store.get_action(grant.action_id)["state"] == "HOLD"
    assert not owner.stop.is_open(authority_epoch=grant.authority_epoch,
                                  dispatch_generation=grant.dispatch_generation)
    owner.advance_pending()
    assert owner._executions == {}


def test_workflow_tick_does_not_hold_stop_lock_while_waiting_for_callback(tmp_path, monkeypatch):
    owner, grant, port, commands, pending = _running_owner(tmp_path, delayed=True)
    execution = owner._executions[grant.action_id][1]
    advance = execution.advance
    entered, checked = threading.Event(), threading.Event()
    observed = {}
    def wrapped_advance():
        entered.set()
        observed["callback_completed"] = checked.wait(2)
        return advance()
    def callback_readback():
        if entered.wait(2):
            owner.runner.current_fence(grant.authority_epoch, grant.dispatch_generation)
            checked.set()
    monkeypatch.setattr(execution, "advance", wrapped_advance)
    callback = threading.Thread(target=callback_readback, daemon=True)
    callback.start()
    try:
        owner.advance_pending()
    finally:
        callback.join(3)
    assert not callback.is_alive()
    assert observed["callback_completed"]


def test_fleet_revocation_during_release_readback_cannot_report_success(tmp_path):
    gate = {"open": True}
    owner, grant, port, commands, pending = _running_owner(
        tmp_path, fleet_fence_current=lambda epoch, generation: gate["open"],
        on_release_readback=lambda: gate.update(open=False))
    for _ in range(5):
        owner.advance_pending()
    assert commands == ["approach", "grasp", "transfer", "release"]
    assert owner.store.get_action(grant.action_id)["state"] == "HOLD"
    assert not owner.stop.is_open(authority_epoch=2, dispatch_generation=8)
