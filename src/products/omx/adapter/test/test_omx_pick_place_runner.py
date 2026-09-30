from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from core_common.protocol.schemas import FleetActionGrant
from omx_adapter.action_runner import DriverSubmission, action_grant_digest
from omx_adapter.action_store import ActionStore
from omx_adapter.command_owner import TrajectoryCommand
from omx_adapter.local_stop import LocalStopBlocked
from omx_adapter.manipulation_plan import (
    JointTrajectoryPoint,
    PlannedMotionPhase,
    ResolvedObjectPose,
    ResolvedPickPlacePlan,
)
from omx_adapter.phase_recorder import ActionPhaseRecorder
from omx_adapter.pick_place_runner import PickPlaceRunner
from omx_adapter.ros_goal_contract import RosGoalEvent


JOINTS = ("joint1", "joint2", "joint3", "joint4", "joint5")
PHASE_NAMES = ("approach", "grasp", "transfer", "release")


def _grant():
    now = datetime.now(timezone.utc)
    evidence = {
        "object_id": "block-1", "observation_id": "obs-1",
        "frame_sha256": "b" * 64, "camera_identity": "cam-1",
        "optical_frame_id": "cam_optical", "calibration_revision": "cal-1",
        "transform_revision": "tf-1", "capture_time_ns": 1_760_000_000_000_000_000,
        "selector_kind": "point", "image_bbox_xyxy": [1, 2, 3, 4],
    }
    value = {
        "mission_id": "mission-1", "step_id": "step-1",
        "action_id": "action-1", "attempt_id": "attempt-1",
        "request_digest": "0" * 64, "workcell_id": "omx-1",
        "instance_id": "omx-1-control", "action_kind": "PICK_PLACE",
        "source_evidence": evidence,
        "destination_evidence": {**evidence, "object_id": "tray-1"},
        "capability_revision": "pick-place-v1", "config_revision": "cfg-1",
        "observation_revision": "obs-1", "authority_epoch": 2,
        "dispatch_generation": 8, "issued_at": now,
        "expires_at": now + timedelta(seconds=30),
    }
    value["request_digest"] = action_grant_digest(value)
    return FleetActionGrant.model_validate(value)


def _plan():
    covariance = tuple(0.0 if index % 7 else 1e-6 for index in range(36))

    def pose(object_id):
        return ResolvedObjectPose(
            object_id=object_id, observation_id="obs-1", camera_identity="cam-1",
            optical_frame_id="cam_optical", rgb_frame_sha256="b" * 64,
            depth_frame_sha256="c" * 64, capture_time_ns=1_760_000_000_000_000_000,
            calibration_revision="cal-1", transform_revision="tf-1",
            workspace_frame_id="omx_base", translation_m=(0.1, 0.0, 0.2),
            orientation_xyzw=(0.0, 0.0, 0.0, 1.0), covariance_6x6=covariance,
            position_stddev_m=0.001,
        )

    point = JointTrajectoryPoint(
        time_from_start_s=0.5, positions=(0.1, 0.2, 0.3, 0.4, 0.5),
    )
    phases = tuple(PlannedMotionPhase(
        phase_id=name, ordinal=index, joint_names=JOINTS, points=(point,),
        source_state_sequence=9, calibration_revision="cal-1",
        transform_revision="tf-1", planning_scene_revision="scene-1",
    ) for index, name in enumerate(PHASE_NAMES))
    return ResolvedPickPlacePlan(
        source_pose=pose("block-1"), destination_pose=pose("tray-1"),
        phases=phases, planner_revision="planner-1",
        planning_scene_revision="scene-1", calibration_revision="cal-1",
        transform_revision="tf-1", source_state_sequence=9,
        planned_at_monotonic_s=12.1,
    )


class _Fence:
    def __init__(self, *, open_=True):
        self.open = open_

    def run_if_open(self, *, operation, **_kwargs):
        if not self.open:
            raise LocalStopBlocked("closed")
        return operation()


class _GoalPort:
    def __init__(self):
        self.submissions = []
        self.cancelled = []
        self.on_submit = None
        self.cancel_response = None

    def submit(self, command, *, on_goal_event):
        goal_id = str(uuid4())
        self.submissions.append((command, goal_id))
        if self.on_submit is not None:
            self.on_submit(command, goal_id, on_goal_event)
        return DriverSubmission(accepted=True, driver_goal_id=goal_id)

    def cancel_goal(self, driver_goal_id):
        self.cancelled.append(driver_goal_id)
        return self.cancel_response


def _harness(tmp_path, *, fence=None):
    grant = _grant()
    store = ActionStore(tmp_path / "phase-runner.sqlite3")
    store.create_action(
        workcell_id=grant.workcell_id, instance_id=grant.instance_id,
        principal_id="fleet-uid-1001", request_key=grant.action_id,
        action_id=grant.action_id, action_kind=grant.action_kind,
        configuration_revision=grant.config_revision,
        observation_id=grant.observation_revision,
        owner_generation=grant.dispatch_generation,
        payload=grant.model_dump(mode="json"),
    )
    store.begin_submission(
        grant.action_id, expected_generation=grant.dispatch_generation,
        attempt_id=grant.attempt_id,
    )
    recorder = ActionPhaseRecorder(
        store, action_id=grant.action_id, attempt_id=grant.attempt_id,
    )
    port = _GoalPort()
    runner = PickPlaceRunner(
        recorder, grant, _plan(), command_for_phase=lambda phase: TrajectoryCommand(
            workcell_id=grant.workcell_id, instance_id=grant.instance_id,
            command_id=f"command-{phase.phase_id}", session_id="session-1",
            owner="moveit", positions=dict(zip(JOINTS, phase.points[-1].positions)),
            duration_s=phase.points[-1].time_from_start_s,
            source_state_sequence=phase.source_state_sequence,
            calibration_revision=phase.calibration_revision,
            joint_names=phase.joint_names, trajectory_points=phase.points,
            phase_id=phase.phase_id,
        ),
        goal_port=port, submission_fence=fence or _Fence(),
        current_fence=lambda epoch, generation: (epoch, generation) == (2, 8),
    )
    return store, recorder, port, runner


def _event(kind, command, phase, goal, sequence, **kwargs):
    return RosGoalEvent(
        kind=kind, command_id=command.command_id, phase_id=phase,
        goal_id=goal, observed_at_monotonic_s=12.2, sequence=sequence, **kwargs,
    )


def test_first_phase_journals_acceptance_then_correlated_terminal_without_autoadvance(tmp_path):
    store, recorder, port, runner = _harness(tmp_path)

    def events(command, goal, callback):
        callback(_event("GOAL_ACCEPTED", command, "approach", goal, 1))
        callback(_event("RUNNING_FEEDBACK", command, "approach", goal, 2,
                        feedback_sequence=1))
        callback(_event("TERMINAL_RESULT", command, "approach", goal, 3,
                        status=4, result_code=0))

    port.on_submit = events
    result = runner.start()

    assert result["action"]["state"] == "ACCEPTED"
    assert recorder.phases()[0]["state"] == "SUCCEEDED"
    assert len(port.submissions) == 1
    runner.advance()
    assert len(port.submissions) == 2
    assert recorder.phases()[1]["state"] == "ACCEPTED"
    assert store.get_action("action-1")["state"] == "RUNNING"


def test_wrong_goal_uuid_high_sequence_cannot_suppress_real_feedback(tmp_path):
    _, recorder, port, runner = _harness(tmp_path)

    def events(command, goal, callback):
        callback(_event("RUNNING_FEEDBACK", command, "approach", str(uuid4()), 90,
                        feedback_sequence=1))
        callback(_event("RUNNING_FEEDBACK", command, "approach", goal, 1,
                        feedback_sequence=1))

    port.on_submit = events
    runner.start()

    assert recorder.phases()[0]["state"] == "RUNNING"


def test_cancel_targets_exact_goal_and_ack_is_not_terminal_result(tmp_path):
    _, recorder, port, runner = _harness(tmp_path)
    runner.start()
    command, goal = port.submissions[0]
    port.cancel_response = None

    runner.cancel_current()

    assert port.cancelled == [goal]
    assert recorder.phases()[0]["state"] == "CANCEL_REQUESTED"
    assert recorder.phases()[0]["cancel_acknowledged"] is None
    assert runner.on_ros_goal_event(_event(
        "CANCEL_ACK", command, "approach", goal, 1, cancel_acknowledged=True,
    ))
    assert recorder.phases()[0]["state"] == "CANCEL_REQUESTED"
    assert recorder.phases()[0]["cancel_acknowledged"] is True


def test_stop_fence_failure_holds_attempt_without_sending_goal(tmp_path):
    store, recorder, port, runner = _harness(tmp_path, fence=_Fence(open_=False))

    receipt = runner.start()

    assert receipt == {"reason": "STOP_GENERATION_FENCED"}
    assert port.submissions == []
    assert store.get_action("action-1")["state"] == "HOLD"
    assert recorder.phases()[0]["state"] == "UNKNOWN"


def test_unknown_acceptance_is_held_and_never_retried(tmp_path):
    _, recorder, port, runner = _harness(tmp_path)
    port.submit = lambda *_args, **_kwargs: DriverSubmission(accepted=None)

    first = runner.start()
    with pytest.raises(RuntimeError, match="phase journal is not empty"):
        runner.start()

    assert first["action"]["state"] == "UNKNOWN"
    assert recorder.parent()["state"] == "HOLD"
    assert recorder.phases()[0]["state"] == "UNKNOWN"
