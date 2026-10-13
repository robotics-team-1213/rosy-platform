from datetime import datetime, timedelta, timezone

import pytest

from core_common.protocol.schemas import FleetActionGrant
from omx_adapter.action_runner import action_grant_digest
from omx_adapter.manipulation_plan import (
    JointTrajectoryPoint,
    ManipulationPlanningProfile,
    PlannedMotionPhase,
    ResolvedObjectPose,
    ResolvedPickPlacePlan,
    RgbdObservation,
    validate_pick_place_plan,
)


JOINTS = ("joint1", "joint2", "joint3", "joint4", "joint5")
PHASES = ("approach", "grasp", "transfer", "release")


def grant():
    now = datetime.now(timezone.utc)
    source = {
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
        "source_evidence": source,
        "destination_evidence": {**source, "object_id": "tray-1"},
        "capability_revision": "pick-place-v1", "config_revision": "cfg-1",
        "observation_revision": "obs-1", "authority_epoch": 2,
        "dispatch_generation": 8, "issued_at": now,
        "expires_at": now + timedelta(seconds=15),
    }
    value["request_digest"] = action_grant_digest(value)
    return FleetActionGrant.model_validate(value)


def observation(**changes):
    values = {
        "observation_id": "obs-1", "camera_identity": "cam-1",
        "optical_frame_id": "cam_optical", "rgb_frame_sha256": "b" * 64,
        "depth_frame_sha256": "c" * 64, "calibration_revision": "cal-1",
        "transform_revision": "tf-1", "capture_time_ns": 1_760_000_000_000_000_000,
        "rgb_capture_time_ns": 1_760_000_000_000_000_000,
        "depth_capture_time_ns": 1_760_000_000_000_000_000,
        "received_at_monotonic_s": 12.0,
    }
    values.update(changes)
    return RgbdObservation(**values)


def pose(identity, translation=(0.1, 0.0, 0.2), **changes):
    values = {
        "object_id": identity, "observation_id": "obs-1",
        "camera_identity": "cam-1", "optical_frame_id": "cam_optical",
        "rgb_frame_sha256": "b" * 64, "depth_frame_sha256": "c" * 64,
        "capture_time_ns": 1_760_000_000_000_000_000,
        "calibration_revision": "cal-1", "transform_revision": "tf-1",
        "workspace_frame_id": "omx_base", "translation_m": translation,
        "orientation_xyzw": (0.0, 0.0, 0.0, 1.0),
        "covariance_6x6": tuple(0.0 if i % 7 else 1e-6 for i in range(36)),
        "position_stddev_m": 0.001,
    }
    values.update(changes)
    return ResolvedObjectPose(**values)


def phase(phase_id, ordinal, **changes):
    values = {
        "phase_id": phase_id, "ordinal": ordinal, "joint_names": JOINTS,
        "points": (JointTrajectoryPoint(
            time_from_start_s=0.5, positions=(0.1, 0.2, 0.3, 0.4, 0.5),
        ),),
        "start_state_positions": (0.0, 0.0, 0.0, 0.0, 0.0),
        "source_state_sequence": 9, "calibration_revision": "cal-1",
        "transform_revision": "tf-1", "planning_scene_revision": "scene-1",
    }
    values.update(changes)
    return PlannedMotionPhase(**values)


def planning_profile(**changes):
    values = {
        "workcell_id": "omx-1", "instance_id": "omx-1-control",
        "workspace_frame_id": "omx_base", "workspace_min_m": (-0.4, -0.4, 0.0),
        "workspace_max_m": (0.4, 0.4, 0.6), "joint_names": JOINTS,
        "calibration_revision": "cal-1", "transform_revision": "tf-1",
        "planning_scene_revision": "scene-1", "max_observation_age_s": 0.5,
        "max_position_stddev_m": 0.005, "max_rgb_depth_skew_ns": 5_000_000,
    }
    values.update(changes)
    return ManipulationPlanningProfile(**values)


def plan(**changes):
    values = {
        "source_pose": pose("block-1"), "destination_pose": pose("tray-1"),
        "phases": tuple(phase(name, index) for index, name in enumerate(PHASES)),
        "planner_revision": "planner-1", "planning_scene_revision": "scene-1",
        "calibration_revision": "cal-1", "transform_revision": "tf-1",
        "source_state_sequence": 9, "planned_at_monotonic_s": 12.1,
    }
    values.update(changes)
    return ResolvedPickPlacePlan(**values)


def test_plan_requires_fresh_rgbd_evidence_matching_grant_and_workcell_profile():
    validate_pick_place_plan(
        plan(), grant(), observation(), planning_profile(), now_monotonic_s=12.2,
    )


@pytest.mark.parametrize("pose_changes, message", [
    ({"observation_id": "old-observation"}, "observation"),
    ({"object_id": "other-object"}, "object identity"),
    ({"workspace_frame_id": "camera_optical"}, "workspace frame"),
    ({"translation_m": (0.5, 0.0, 0.2)}, "workspace bounds"),
    ({"position_stddev_m": 0.02}, "uncertainty"),
])
def test_plan_rejects_pose_not_proven_for_grant_or_accepted_workspace(pose_changes, message):
    with pytest.raises(ValueError, match=message):
        invalid = plan(source_pose=pose("block-1", **pose_changes))
        validate_pick_place_plan(
            invalid, grant(), observation(), planning_profile(), now_monotonic_s=12.2,
        )


@pytest.mark.parametrize("observation_changes, message", [
    ({"depth_frame_sha256": "invalid"}, "depth_frame_sha256"),
    ({"depth_capture_time_ns": 1_760_000_000_100_000_000}, "synchronized"),
    ({"camera_identity": "other-camera"}, "camera identity"),
    ({"calibration_revision": "old-cal"}, "calibration revision"),
    ({"received_at_monotonic_s": 11.0}, "stale"),
])
def test_plan_rejects_unsynchronized_or_stale_local_rgbd_evidence(observation_changes, message):
    with pytest.raises(ValueError, match=message):
        validate_pick_place_plan(
            plan(), grant(), observation(**observation_changes), planning_profile(),
            now_monotonic_s=12.2,
        )


@pytest.mark.parametrize("phase_names", [
    ("approach", "grasp", "release", "transfer"),
    ("approach", "grasp", "transfer", "transfer"),
    ("approach", "grasp", "transfer"),
])
def test_plan_requires_exactly_four_ordered_motion_phases(phase_names):
    with pytest.raises(ValueError, match="phases"):
        plan(phases=tuple(phase(name, i) for i, name in enumerate(phase_names)))


@pytest.mark.parametrize("changes, message", [
    ({"translation_m": (float("nan"), 0.0, 0.2)}, "finite"),
    ({"orientation_xyzw": (0.0, 0.0, 0.0, 0.0)}, "unit quaternion"),
    ({"covariance_6x6": (0.0,) * 35}, "36"),
    ({"position_stddev_m": -0.1}, "positive"),
])
def test_object_pose_requires_finite_well_formed_uncertainty(changes, message):
    with pytest.raises(ValueError, match=message):
        pose("block-1", **changes)
