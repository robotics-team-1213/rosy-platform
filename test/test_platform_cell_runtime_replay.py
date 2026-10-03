"""Real Cell/Action ledgers and analytic Skill execution; ROS/sensors are ports."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
for relative in ("contracts/skill/src", "middleware/skills/api/src", "middleware/skills/manipulation/src",
                 "integrations/robots/omx/src", "middleware/apps/device/omx/adapter",
                 "middleware/apps/device/omx/adapter/test", "operations/fleet/test", "operations/execution/src"):
    sys.path.insert(0, str(ROOT / relative))

from fleet.server.cell_job_store import CellJobStore
from fleet.server.step_dispatcher import StepJobDispatcher as CellJobDispatcher
from fleet.server.cell_goal_evidence import attach_goal_predicates
from rosy.execution.site.item_pose import ItemPoseTolerance
from omx_adapter.journal_identity import journal_identity
from fleet.server.task_store import FleetTaskStore
from fleet.server.mission_store import MissionStore
from fleet.server.cell_goal_evidence_registry import CellGoalProducer, CellGoalRegistry
from fleet.server.cell_goal_evidence_service import CellGoalEvidenceService
from fleet.server.goal_evidence_store import GoalEvidenceStore
from omx_adapter.action_api import ActionApi
from omx_adapter.action_runner import ActionRunner
from omx_adapter.action_store import ActionStore
from omx_adapter.command_owner import TrajectoryCommand
from omx_adapter.gripper_contract import GripperObservation
from omx_adapter.kinematics import OmxKinematics
from omx_adapter.local_stop import LocalStopController
from omx_adapter.pose_plan import CellPlanningProfile
from rosy.integrations.robots.omx.transfer_provider import create_omx_cell_transfer_phase_factory
from test_cell_job_store import _submission
from test_omx_action_api import FakeDriver
from test_omx_pick_place_runner import _event, _GoalPort
from test_omx_pose_plan import _request, _state, _planner
from test_cell_goal_evidence_api import _evidence


def _goal_tolerance():
    return ItemPoseTolerance.from_mapping(yaml.safe_load(
        (ROOT / "deploy/robot/omx/sim/item_pose_goal.yaml").read_text(encoding="utf-8")))


class LocalTransport:
    def __init__(self, path, tasks, counters, *, lose_reply=False, rearm=False,
                 accepted_cell="c" * 64, accepted_items=None):
        self.counters, self.lose_reply = counters, lose_reply
        accepted_items = accepted_items if accepted_items is not None else {("a" * 64, "box"): {
            "grasp_width_m": .03, "grasp_depth_m": .01, "height_m": .03,
        }}
        self.store = ActionStore(path)
        self.driver = FakeDriver()
        stop = LocalStopController(path, workcell_id="omx_01", instance_id="omx_01_control")
        current = lambda epoch, generation: (epoch, generation) == (
            tasks.dispatch_control()["authority_epoch"], tasks.dispatch_control()["generation"])
        if rearm:
            control = tasks.dispatch_control()
            stop.rearm(authority_epoch=control["authority_epoch"], dispatch_generation=control["generation"],
                       operator_confirmed=True, fleet_fence_current=current)
        kin = OmxKinematics.load()
        profile = CellPlanningProfile.load(ROOT / "deploy/robot/omx/sim/cell_profile.yaml")
        state = [_state(kin, profile)]
        port = _GoalPort()
        self.port = port
        self.executions = {}
        self.planning_errors = []

        def succeed(command, goal, callback):
            counters["commands"].append((command.command_id, command.phase_id, goal))
            callback(_event("GOAL_ACCEPTED", command, command.phase_id, goal, 1))
            state[0] = replace(state[0], sequence=state[0].sequence + 1,
                               joint_positions=dict(command.positions), observed_at_monotonic_s=100.5)
            callback(_event("TERMINAL_RESULT", command, command.phase_id, goal, 2, status=4, result_code=0))

        port.on_submit = succeed

        def create(grant, recorder):
            def readback():
                released = port.submissions[-1][0].phase_id == "release"
                return GripperObservation(grant.workcell_id, grant.instance_id, "readback", 8 if released else 7,
                    100.5, "OPEN" if released else "CLOSED", not released,
                    None if released else grant.cell_transfer.item, grant.dispatch_generation)

            factory = create_omx_cell_transfer_phase_factory(
                profile=profile, planner=_planner(kin, accepted=accepted_cell, items=accepted_items),
                execution_state=lambda: state[0],
                accepted_item_geometry=lambda recipe, item: accepted_items.get((recipe, item)),
                command_for_phase=lambda accepted, phase: TrajectoryCommand(
                    workcell_id=accepted.workcell_id, instance_id=accepted.instance_id,
                    command_id=f"{accepted.action_id}-{phase.phase_id}", session_id="session-1", owner="rule_based",
                    positions=dict(zip(phase.joint_names, phase.points[-1].positions)),
                    duration_s=phase.points[-1].time_from_start_s, source_state_sequence=phase.source_state_sequence,
                    calibration_revision=phase.calibration_revision, joint_names=phase.joint_names,
                    trajectory_points=phase.points, phase_id=phase.phase_id),
                goal_port=port, submission_fence=stop, phase_gate=lambda accepted, phase: True,
                current_fence=current, gripper_readback=readback, monotonic=lambda: 100.5,
                gripper_sensor_revision="readback")
            try:
                execution = factory(grant, recorder)
            except Exception as exc:
                self.planning_errors.append(exc)
                raise
            self.executions[grant.action_id] = execution
            return execution

        self.runner = ActionRunner(self.store, self.driver, workcell_id="omx_01", instance_id="omx_01_control",
            principal_for_peer=lambda uid: "fleet-owner", allowed_peer_uids={1001}, current_fence=current,
            capability_current=lambda grant: grant.config_revision == "cell-config-v1", submission_fence=stop,
            phase_runner_factories={"CELL_TRANSFER": create}, enabled=True)
        self.api = ActionApi(self.runner, identity={"simulation": True, "workcell_id": "omx_01",
            "instance_id": "omx_01_control", "journal_id": journal_identity(path)})

    def owner_identity(self, instance_id):
        response = self.api.dispatch({"version": 2, "operation": "GetOwnerIdentity"}, peer_uid=1001)
        assert response["status"] == 200
        return response["identity"]

    def submit(self, grant):
        self.counters["submits"].append(grant)
        response = self.api.dispatch({"version": 2, "operation": "SubmitAction",
                                      "grant": grant.model_dump(mode="json")}, peer_uid=1001)
        assert response["status"] == 200, response
        if response["receipt"]["state"] not in {"ACCEPTED", "RUNNING"}:
            return response["receipt"]
        for _ in range(4):
            self.executions[grant.action_id].advance()
        assert self.store.get_action(grant.action_id)["state"] == "SUCCEEDED"
        if self.lose_reply:
            raise TimeoutError("completed local Action receipt was lost")
        return self.get(grant)

    def get(self, grant):
        self.counters["gets"].append((grant.action_id, grant.attempt_id))
        response = self.api.dispatch({"version": 2, "operation": "GetAction", "action_id": grant.action_id},
                                     peer_uid=1001)
        assert response["status"] == 200, response
        return response["receipt"]


@pytest.mark.parametrize("lose_reply,expire", [(False, False), (True, False), (True, True)])
def test_actual_cell_two_ledgers_reopen_and_require_independent_goal(tmp_path, lose_reply, expire):
    site_path, local_path = tmp_path / "fleet.sqlite3", tmp_path / "omx.sqlite3"
    tasks = FleetTaskStore(site_path)
    MissionStore(site_path)
    control = tasks.rearm_dispatch(expected_generation=tasks.dispatch_control()["generation"], actor_id="operator-1")
    jobs = CellJobStore(site_path)
    submission = _submission()
    submission["cell_digest"] = "c" * 64
    request = _request()
    for step in submission["steps"]:
        inputs = step["inputs"]
        for field, name in (("home_pose_base", "home"), ("source_pose_base", "pick"), ("destination_pose_base", "place")):
            pose = getattr(request, name)
            inputs[field] = {"x_m": pose.x, "y_m": pose.y, "z_m": pose.z, "yaw_rad": pose.yaw}
        inputs.update(source_approach_z_base_m=request.pick_approach_z,
                      destination_approach_z_base_m=request.place_approach_z, carry_z_base_m=request.carry_z)
    attach_goal_predicates(submission, {"box": {"grasp_depth_m": .01, "height_m": .03}},
                           _goal_tolerance())
    jobs.create(mission_id="cell-replay", proposal_principal_id="cell-service", request_key="request-1",
                request_digest="d" * 64, submission=submission)
    jobs.admit("cell-replay", actor_id="operator-1", expected_generation=control["generation"])
    counters = {"submits": [], "gets": [], "commands": []}
    transport = LocalTransport(local_path, tasks, counters, lose_reply=lose_reply, rearm=True)
    dispatcher = CellJobDispatcher(jobs, tasks, transport, {"omx_01": "omx_01_control"},
                                   grant_revisions={"omx_01_control": {"capability_revision": "cell-transfer-v1",
                                   "config_revision": "cell-config-v1"}}, deployment_profile="simulation")
    assert dispatcher.dispatch_next()["state"] == ("HOLD" if lose_reply else "ACTION_SUCCEEDED")
    first = counters["submits"][0]
    assert len(counters["commands"]) == 4
    if lose_reply:
        jobs, tasks = CellJobStore(site_path), FleetTaskStore(site_path)
        transport = LocalTransport(local_path, tasks, counters)
        dispatcher = CellJobDispatcher(jobs, tasks, transport, {"omx_01": "omx_01_control"},
            grant_revisions={"omx_01_control": {"capability_revision": "cell-transfer-v1",
                                   "config_revision": "cell-config-v1"}}, deployment_profile="simulation",
            now=(lambda: first.expires_at + timedelta(seconds=1)) if expire else None)
    dispatcher.dispatch_next()
    assert len(counters["submits"]) == 1 and len(counters["commands"]) == 4
    assert jobs.get("cell-replay")["steps"][1]["status"] == "WAITING"
    assert tasks.resource_claims(resource_kind="workcell", resource_id="omx_01")[0]["phase"] == "CLAIMED"
    registry = CellGoalRegistry((CellGoalProducer(producer_id="gazebo-pose", token="pose-secret",
        workcell_id="omx_01", instance_id="omx_01_control", recipe_sha256="a" * 64, cell_sha256="c" * 64,
        evaluator_revisions=("placement-v1",), max_age_s=5, valid_until=datetime(2030, 1, 1, tzinfo=timezone.utc)),))
    goals = CellGoalEvidenceService(jobs, registry, GoalEvidenceStore(site_path))
    for index in range(2):
        grant = counters["submits"][index]
        receipt = transport.get(grant)
        completed = datetime.fromisoformat(receipt["observed_at"]).timestamp()
        observed = max(completed + .01, first.expires_at.timestamp() + 1 if expire else completed + .01)
        evidence = _evidence(grant, observed - .01)
        evidence["recipe_sha256"] = "a" * 64
        for field, pose in (("model_pose_base", grant.cell_transfer.place),
                            ("initial_model_pose_base", grant.cell_transfer.pick)):
            evidence[field] = {"x_m": pose.x, "y_m": pose.y, "z_m": pose.z - .005,
                               "roll_rad": 0., "pitch_rad": 0., "yaw_rad": pose.yaw}
        goals.now = lambda: observed + .01
        result = goals.submit(token="pose-secret", mission_id="cell-replay", raw_evidence=evidence)
        assert result["state"] == ("READY" if index == 0 else "GOAL_CONFIRMED")
        assert goals.submit(token="pose-secret", mission_id="cell-replay", raw_evidence=evidence)["created"] is False
        if index == 0:
            dispatcher.now = lambda: datetime.now(timezone.utc)
            outcome = dispatcher.dispatch_next()
            if lose_reply:
                assert outcome["state"] == "HOLD"
                assert len(counters["commands"]) == 4
                assert transport.store.get_action(first.action_id)["state"] == "SUCCEEDED"
                assert jobs.get("cell-replay")["steps"][1]["status"] == "HOLD"
                assert jobs.get("cell-replay")["steps"][1]["result"]["device_reason"] == "STOP_GENERATION_FENCED"
                assert counters["submits"][1].cell_transfer.step_index == 1
                assert counters["submits"][1].attempt_id != first.attempt_id
                assert tasks.resource_claims(resource_kind="workcell", resource_id="omx_01")
                assert tasks.resource_claims(resource_kind="pallet", resource_id="pallet-1")
                return
            local = transport.store.get_action(counters["submits"][-1].action_id)
            assert outcome["state"] == "ACTION_SUCCEEDED", {
                "outcome": outcome, "local": (local["state"], local["reason"]),
                "phases": [(row["phase_id"], row["state"]) for row in
                           transport.store.action_phases(counters["submits"][-1].action_id)],
            }
    assert len(counters["commands"]) == 8 and len(counters["submits"]) == 2
    assert tasks.resource_claims(resource_kind="workcell", resource_id="omx_01") == []
    assert tasks.resource_claims(resource_kind="pallet", resource_id="pallet-1") == []
    assert transport.driver.submissions == []
    reopened_jobs = CellJobStore(site_path)
    reopened = LocalTransport(local_path, FleetTaskStore(site_path), counters)
    for grant in counters["submits"]:
        assert reopened.get(grant)["state"] == "SUCCEEDED"
        assert reopened_jobs.get("cell-replay")["steps"][grant.cell_transfer.step_index]["status"] == "GOAL_CONFIRMED"
    assert len(counters["commands"]) == 8 and reopened.executions == {}
