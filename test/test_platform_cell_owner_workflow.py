"""Actual owner composition advances durable Cell workflow; ROS remains a test port."""
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/products/omx/adapter/test"))
from test_platform_cell_owner_assembly import _build, _docs, _grant, _submit
from test_omx_pose_plan import _state
from test_omx_pick_place_runner import _GoalPort, _event
from omx_adapter.kinematics import OmxKinematics
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


def _running_owner(tmp_path, *, release_fault=False, delayed=False):
    port = _GoalPort()
    holder = {}
    commands = []
    pending = []
    def readback(grant):
        owner = holder["owner"]
        state = owner.runtime.latest_joint_state
        released = port.submissions[-1][0].phase_id == "release"
        return GripperObservation(grant.workcell_id, grant.instance_id,
            "omx-sim-gripper-joint-position-v2", state.sequence, state.received_at,
            "OPEN" if released else "CLOSED", not released,
            None if released else "box", grant.dispatch_generation + (1 if released and release_fault else 0))
    owner, _ = _build(tmp_path, goal_port_factory=lambda runtime: port, gripper_readback=readback)
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
    owner.stop.rearm(authority_epoch=2, dispatch_generation=8, operator_confirmed=True,
                     fleet_fence_current=lambda epoch, generation: True)
    recipe, cell = _docs()
    c = owner.acceptance.accept_cell(cell, actor_id="operator-1")["cell_sha256"]
    r = owner.acceptance.accept_recipe(recipe, actor_id="operator-1")["recipe_sha256"]
    grant = _grant(owner, c, r)
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
