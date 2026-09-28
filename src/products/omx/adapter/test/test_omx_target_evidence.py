from dataclasses import replace

import pytest

from omx_adapter.camera_contract import CameraFrameMetadata
from omx_adapter.target_evidence import (
    ObjectCandidate,
    TargetResolutionError,
    TargetSelector,
    resolve_target,
)


def observation(**changes):
    base = CameraFrameMetadata(
        camera_identity="camera-serial-1", optical_frame_id="workcell_camera_optical",
        calibration_revision="cal-v3", capture_time_ns=12_000_000_000,
        width=640, height=480, sequence=4, received_at=20.0,
        frame_sha256="a" * 64, observation_id="obs-4", transform_revision="tf-v7",
    )
    return replace(base, **changes)


def candidate(object_id="object-1", label="red block", bbox=(40, 40, 100, 100), **changes):
    values = dict(observation_id="obs-4", object_id=object_id, label=label,
                  descriptors=(label, "block beside green tray"), bbox_xyxy=bbox)
    values.update(changes)
    return ObjectCandidate(**values)


def test_point_and_label_selector_resolve_one_observed_object_without_pose():
    point = resolve_target(
        observation(), [candidate()],
        TargetSelector("point", (50, 60), observation_id="obs-4"), now=20.1,
        max_frame_age_s=0.5,
    )
    label = resolve_target(
        observation(), [candidate()],
        TargetSelector("label", "RED BLOCK", observation_id="obs-4"), now=20.1,
        max_frame_age_s=0.5,
    )

    assert point.object_id == label.object_id == "object-1"
    assert point.observation_id == "obs-4"
    assert point.frame_sha256 == "a" * 64
    assert point.image_bbox_xyxy == (40.0, 40.0, 100.0, 100.0)
    assert not hasattr(point, "pose")


@pytest.mark.parametrize("selector", [
    TargetSelector("label", "red block", observation_id="obs-4"),
    TargetSelector("relation", "block beside green tray", observation_id="obs-4"),
])
def test_multiple_matching_candidates_are_rejected(selector):
    with pytest.raises(TargetResolutionError, match="ambiguous"):
        resolve_target(observation(), [candidate(), candidate("object-2")], selector,
                       now=20.1, max_frame_age_s=0.5)


def test_stale_observation_is_rejected():
    with pytest.raises(TargetResolutionError, match="stale"):
        resolve_target(observation(), [candidate()],
                       TargetSelector("object_id", "object-1", observation_id="obs-4"),
                       now=21.0, max_frame_age_s=0.5)


def test_selector_cannot_cross_observations_or_crop_coordinate_spaces():
    with pytest.raises(TargetResolutionError, match="observation"):
        resolve_target(observation(), [candidate()],
                       TargetSelector("object_id", "object-1", observation_id="obs-old"),
                       now=20.1, max_frame_age_s=0.5)
    with pytest.raises(ValueError, match="coordinate_space"):
        TargetSelector("point", (50, 60), observation_id="obs-4",
                       coordinate_space="cropped_image_pixels")


def test_missing_frame_or_transform_revision_fails_closed():
    with pytest.raises(TargetResolutionError, match="frame digest"):
        resolve_target(observation(frame_sha256=""), [candidate()],
                       TargetSelector("object_id", "object-1", observation_id="obs-4"),
                       now=20.1, max_frame_age_s=0.5)
    with pytest.raises(TargetResolutionError, match="transform revision"):
        resolve_target(observation(transform_revision=""), [candidate()],
                       TargetSelector("object_id", "object-1", observation_id="obs-4"),
                       now=20.1, max_frame_age_s=0.5)
