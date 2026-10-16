"""D-780 through the built cell owner: PHASE_WAIT barriers, coordinator roles and liveness HOLD.
ROS is the same fake goal port the single-arm workflow tests use."""

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "middleware/devices/omx/adapter/test"))
from test_platform_cell_owner_assembly import FLEET_UID, FakeRuntime, _docs, _grant, _settings, _submit  # noqa: E402
from test_omx_pose_plan import _state  # noqa: E402
from test_omx_pick_place_runner import _GoalPort, _event  # noqa: E402
from omx_adapter.action_runner import action_grant_digest  # noqa: E402
from omx_adapter.gripper_contract import GripperObservation  # noqa: E402
from omx_adapter.kinematics import OmxKinematics  # noqa: E402
from rosy_agent.omx_cell_owner import build_cell_owner  # noqa: E402

COORDINATOR_UID = 2002
BARRIERS = [
    {"barrier_id": "both_ready", "before_first_phase": True, "coupling_after": "loose", "max_wait_s": 60.0},
    {"barrier_id": "both_grasped", "after_phase": "grasp", "coupling_after": "tight", "max_wait_s": 60.0},
]


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _owner(tmp_path, *, coordinator=True, liveness_s=30.0):
    port, holder, commands = _GoalPort(), {}, []

    def readback(grant):
        state = holder["owner"].runtime.latest_joint_state
        released = port.submissions[-1][0].phase_id == "release"
        return GripperObservation(grant.workcell_id, grant.instance_id, "omx-sim-gripper-joint-position-v2",
                                  state.sequence, state.received_at, "OPEN" if released else "CLOSED",
                                  not released, None if released else "box", grant.dispatch_generation)

    settings = _settings(tmp_path)
    if coordinator:
        settings = replace(settings, coordinator_peer_uids=frozenset({COORDINATOR_UID}),
                           coordinator_liveness_s=liveness_s)
    owner = build_cell_owner(
        settings, runtime_factory=FakeRuntime, goal_port_factory=lambda runtime: port,
        http_app_factory=lambda runtime: "http-app", refuse_second_owner=lambda: None,
        gripper_readback=readback, fleet_fence_current=lambda epoch, generation: True)
    holder["owner"] = owner
    snapshot = _state(OmxKinematics.load(), owner.profile)
    owner.runtime.latest_joint_state = SimpleNamespace(sequence=snapshot.sequence,
                                                       positions=snapshot.joint_positions, received_at=100.)

    def succeed(command, goal, callback):
        commands.append(command.phase_id)
        callback(_event("GOAL_ACCEPTED", command, command.phase_id, goal, 1))
        previous = owner.runtime.latest_joint_state
        owner.runtime.latest_joint_state = SimpleNamespace(sequence=previous.sequence + 1,
                                                           positions=dict(command.positions), received_at=100.)
        callback(_event("TERMINAL_RESULT", command, command.phase_id, goal, 2, status=4, result_code=0))

    port.on_submit = succeed
    owner.stop.rearm(authority_epoch=2, dispatch_generation=8, operator_confirmed=True,
                     fleet_fence_current=lambda epoch, generation: True)
    return owner, port, commands


def _pair_grant(owner, barriers=BARRIERS):
    recipe, cell = _docs()
    c = owner.acceptance.accept_cell(cell, actor_id="operator-1")["cell_sha256"]
    r = owner.acceptance.accept_recipe(recipe, actor_id="operator-1")["recipe_sha256"]
    value = _grant(owner, c, r).model_dump(mode="json")
    value.update(arm_role="left", pair_id="pair-1", partner_instance_id="omx_cell_sim_02", coupling="tight")
    value["cell_transfer"]["barriers"] = barriers
    value["request_digest"] = action_grant_digest(value)
    return type(_grant(owner, c, r)).model_validate(value)


def _coordinator(owner, document):
    return owner.action_api.dispatch(document, peer_uid=COORDINATOR_UID)


def _release(owner, grant, barrier_id):
    return _coordinator(owner, {
        "version": 2, "operation": "ReleaseBarrier", "action_id": grant.action_id, "pair_id": "pair-1",
        "barrier_id": barrier_id, "authority_epoch": 2, "dispatch_generation": 8,
        "partner_arrival": {"instance_id": "omx_cell_sim_02", "action_id": "a-2", "arrived_at": "t"}})


def test_one_arm_owner_has_no_barrier_surface_and_refuses_a_barrier_plan_unjournaled(tmp_path):
    owner, port, commands = _owner(tmp_path, coordinator=False)
    assert owner.barriers is None and owner.settings.coordinator_peer_uids == frozenset()
    response = owner.action_api.dispatch({"version": 2, "operation": "GetBarrier"}, peer_uid=FLEET_UID)
    assert (response["status"], response["error"]["code"]) == (404, "UNKNOWN_OPERATION")
    grant = _pair_grant(owner)
    refused = _submit(owner, grant)
    assert (refused["status"], refused["error"]["code"]) == (409, "BARRIERS_UNSUPPORTED")
    assert owner.store.get_action(grant.action_id) is None and commands == []


def test_barriers_wait_without_a_goal_and_advance_after_coordinator_release(tmp_path):
    owner, port, commands = _owner(tmp_path)
    grant = _pair_grant(owner)
    receipt = _submit(owner, grant)["receipt"]
    assert receipt["state"] == "SUBMITTING" and commands == []
    for _ in range(3):
        owner.advance_pending()
    assert commands == []
    view = _coordinator(owner, {"version": 2, "operation": "GetBarrier"})["actions"][0]
    assert [item["state"] for item in view["barriers"]] == ["waiting", "not_reached"]
    assert _release(owner, grant, "both_ready")["status"] == 200
    for _ in range(4):
        owner.advance_pending()
    assert commands == ["approach", "grasp"]  # held at both_grasped, no goal in flight
    view = _coordinator(owner, {"version": 2, "operation": "GetBarrier", "action_id": grant.action_id})["action"]
    assert [item["state"] for item in view["barriers"]] == ["released", "waiting"] and view["moved"] is True
    assert _release(owner, grant, "both_grasped")["status"] == 200
    for _ in range(5):
        owner.advance_pending()
    assert commands == ["approach", "grasp", "transfer", "release"]
    assert owner.store.get_action(grant.action_id)["state"] == "SUCCEEDED"


def test_coordinator_silence_in_a_tight_segment_holds_with_coordinator_source(tmp_path):
    owner, port, commands = _owner(tmp_path, liveness_s=0.5)
    clock = Clock()
    owner.barriers.monotonic = owner.barriers.journal.monotonic = clock
    grant = _pair_grant(owner)
    _submit(owner, grant)
    _release(owner, grant, "both_ready")
    for _ in range(4):
        owner.advance_pending()
    _release(owner, grant, "both_grasped")
    clock.t += 0.4
    owner.advance_pending()
    assert commands[-1] == "transfer"
    clock.t += 1.0
    owner.advance_pending()
    snapshot = owner.stop.snapshot(workcell_id="omx_cell_sim", instance_id="omx_cell_sim_01")
    assert (snapshot.source.value, snapshot.reason) == ("coordinator", "PARTNER_LINK_LOST")
    assert owner.store.get_action(grant.action_id)["state"] == "HOLD"
    assert owner._executions == {}
    owner.advance_pending()
    assert commands[-1] == "transfer"


def test_before_first_phase_timeout_fails_the_action_without_stopping_the_owner(tmp_path):
    owner, port, commands = _owner(tmp_path)
    clock = Clock()
    owner.barriers.monotonic = owner.barriers.journal.monotonic = clock
    grant = _pair_grant(owner)
    _submit(owner, grant)
    owner.advance_pending()
    clock.t += 61
    owner.advance_pending()
    action = owner.store.get_action(grant.action_id)
    assert (action["state"], action["reason"]) == ("FAILED", "BARRIER_TIMEOUT") and commands == []
    assert owner.stop.is_open(authority_epoch=2, dispatch_generation=8)


def test_built_owner_enforces_the_coordinator_operation_matrix(tmp_path):
    owner, port, commands = _owner(tmp_path)
    grant = _pair_grant(owner)
    refused = _coordinator(owner, {"version": 2, "operation": "SubmitAction", "grant": grant.model_dump(mode="json")})
    assert (refused["status"], refused["error"]["code"]) == (403, "COORDINATOR_NOT_ALLOWED")
    assert owner.store.get_action(grant.action_id) is None
    identity = {"workcell_id": "omx_cell_sim", "instance_id": "omx_cell_sim_01"}
    assert _coordinator(owner, {"version": 1, "operation": "GetOwnerState", **identity})["status"] == 200
    assert _coordinator(owner, {"version": 1, "operation": "GetStopState", **identity})["status"] == 200
    recover = {"version": 1, "operation": "RecoverOwner", **identity, "authority_epoch": 2,
               "dispatch_generation": 8, "operator_confirmed": True, "observed_sequence": 1, "actor_id": "op"}
    assert _coordinator(owner, recover)["error"]["code"] == "COORDINATOR_NOT_ALLOWED"
    fleet_release = owner.action_api.dispatch({"version": 2, "operation": "ReleaseBarrier"}, peer_uid=FLEET_UID)
    assert (fleet_release["status"], fleet_release["error"]["code"]) == (403, "COORDINATOR_PEER_REQUIRED")
    _submit(owner, grant)
    stop = _coordinator(owner, {"version": 1, "operation": "StopLocal", **identity, "authority_epoch": 2,
                                "dispatch_generation": 8, "reason": "PARTNER_FAILED",
                                "requested_at": datetime.now(timezone.utc).isoformat()})
    assert stop["status"] == 200 and stop["snapshot"]["source"] == "coordinator"
    assert stop["snapshot"]["reason"] == "PARTNER_FAILED"
    assert not owner.stop.is_open(authority_epoch=2, dispatch_generation=8)
    # The Action waiting at its first barrier had no goal to cancel; the stop ended it at once.
    action = owner.store.get_action(grant.action_id)
    assert (action["state"], action["reason"]) == ("FAILED", "STOP_FENCED_AT_BARRIER")


def test_settings_default_to_a_one_arm_workcell(tmp_path):
    settings = _settings(tmp_path)
    assert settings.coordinator_peer_uids == frozenset() and settings.coordinator_liveness_s == 2.0
    with pytest.raises(ValueError):
        _owner(tmp_path / "bad", liveness_s=0.1)


def _fleet_stop(owner):
    return owner.action_api.dispatch({
        "version": 1, "operation": "StopLocal", "workcell_id": "omx_cell_sim", "instance_id": "omx_cell_sim_01",
        "authority_epoch": 2, "dispatch_generation": 8, "reason": "operator stop",
        "requested_at": datetime.now(timezone.utc).isoformat()}, peer_uid=FLEET_UID)


@pytest.mark.parametrize("cancel_raises", [False, True])
def test_fleet_stop_through_the_built_owner_ends_a_first_barrier_wait(tmp_path, cancel_raises):
    owner, port, commands = _owner(tmp_path)
    grant = _pair_grant(owner)
    _submit(owner, grant)
    if cancel_raises:
        def broken(**_kwargs):
            raise RuntimeError("cancel fanout failed")
        owner.runner.cancel_unresolved = broken
    assert _fleet_stop(owner)["status"] == 200
    action = owner.store.get_action(grant.action_id)
    assert (action["state"], action["reason"]) == ("FAILED", "STOP_FENCED_AT_BARRIER") and commands == []


def test_fleet_stop_through_the_built_owner_holds_an_arm_waiting_after_it_moved(tmp_path):
    owner, port, commands = _owner(tmp_path)
    grant = _pair_grant(owner)
    _submit(owner, grant)
    _release(owner, grant, "both_ready")
    for _ in range(4):
        owner.advance_pending()
    assert commands == ["approach", "grasp"]
    assert _fleet_stop(owner)["status"] == 200
    action = owner.store.get_action(grant.action_id)
    assert (action["state"], action["reason"]) == ("HOLD", "STOP_FENCED_AT_BARRIER")
    owner.advance_pending()
    assert commands == ["approach", "grasp"]
