"""Map an ER 2 selector to exactly one object in its source camera frame."""

import hashlib
from dataclasses import dataclass

import pytest

from fleet.ai.candidate import ImageObservation, ImageTransform, PickPlaceProposalCandidate
from fleet.ai.selector_bridge import (
    TargetResolutionError,
    resolve_pick_place_candidate,
)


@dataclass(frozen=True)
class CameraFrameMetadata:
    camera_identity: str
    optical_frame_id: str
    calibration_revision: str
    capture_time_ns: int
    width: int
    height: int
    sequence: int
    received_at: float
    frame_sha256: str
    observation_id: str
    transform_revision: str


@dataclass(frozen=True)
class ObjectCandidate:
    observation_id: str
    object_id: str
    label: str
    descriptors: tuple[str, ...]
    bbox_xyxy: tuple[float, float, float, float]


def _candidate(*, target=None, destination=None, transform=None, camera="overhead-01"):
    frame = b"camera frame for selector bridge"
    mapping = transform or ImageTransform.identity(source_width=640, source_height=480)
    image = ImageObservation(
        observation_id="obs-44",
        camera_id=camera,
        frame_id="overhead_optical",
        observed_at="2025-10-09T08:53:20Z",
        image_bytes=frame,
        image_transform=mapping,
        calibration_revision="cal-3",
        transform_revision="tf-5",
    )
    return PickPlaceProposalCandidate.from_function_call(
        request_id="proposal-1",
        interaction_id="interaction-1",
        call_id="call-1",
        name="propose_pick_place",
        arguments={
            "target": target or {"label": "red block", "point_yx_1000": [300, 300]},
            "destination": destination or {
                "label": "green tray", "box_yxyx_1000": [500, 500, 900, 900]
            },
        },
        instruction="Put the red block in the green tray.",
        observation=image,
        model_id="gemini-robotics-er-2-preview",
    ), hashlib.sha256(frame).hexdigest()


def _observation(*, width=640, height=480, digest=None, observation_id="obs-44",
                 camera="overhead-01", frame="overhead_optical", received_at=10.0,
                 calibration="cal-3", transform="tf-5", capture_time_ns=1760000000000000000):
    return CameraFrameMetadata(
        camera_identity=camera,
        optical_frame_id=frame,
        calibration_revision=calibration,
        capture_time_ns=capture_time_ns,
        width=width,
        height=height,
        sequence=44,
        received_at=received_at,
        frame_sha256=digest or "a" * 64,
        observation_id=observation_id,
        transform_revision=transform,
    )


def _objects(observation_id="obs-44"):
    return [
        ObjectCandidate(observation_id, "block-1", "red block", (), (180, 130, 205, 155)),
        ObjectCandidate(observation_id, "tray-1", "green tray", (), (300, 220, 600, 460)),
    ]


def test_normalized_yx_point_and_box_resolve_source_pixel_evidence():
    candidate, digest = _candidate()
    result = resolve_pick_place_candidate(
        candidate,
        _observation(digest=digest),
        _objects(),
        now=10.1,
        max_frame_age_s=0.5,
    )
    assert result.source.object_id == "block-1"
    assert result.destination.object_id == "tray-1"
    assert result.source.image_bbox_xyxy == (180.0, 130.0, 205.0, 155.0)
    assert result.source.frame_sha256 == digest
    assert result.destination.observation_id == result.source.observation_id == "obs-44"


def test_crop_resize_and_quarter_rotation_are_inverted_before_resolution():
    transform = ImageTransform(
        source_width=640,
        source_height=480,
        crop_xyxy=(100, 40, 500, 440),
        model_width=400,
        model_height=400,
        rotation_quadrants_clockwise=1,
    )
    # The source center remains the model center after crop, resize and rotation.
    candidate, digest = _candidate(
        transform=transform,
        target={"label": "red block", "point_yx_1000": [500, 500]},
        destination={"label": "green tray", "box_yxyx_1000": [500, 500, 900, 900]},
    )
    result = resolve_pick_place_candidate(
        candidate,
        _observation(digest=digest),
        [
            ObjectCandidate("obs-44", "block-1", "red block", (), (290, 230, 310, 250)),
            ObjectCandidate("obs-44", "tray-1", "green tray", (), (380, 160, 490, 240)),
        ],
        now=10.1,
        max_frame_age_s=0.5,
    )
    assert result.source.object_id == "block-1"
    assert result.destination.object_id == "tray-1"


@pytest.mark.parametrize(
    "observation_kwargs,object_observation_id,error",
    [
        ({"observation_id": "other-frame"}, "obs-44", "observation"),
        ({"camera": "other-camera"}, "obs-44", "camera"),
        ({"frame": "other-optical"}, "obs-44", "frame"),
        ({"calibration": "other-cal"}, "obs-44", "calibration"),
        ({"transform": "other-tf"}, "obs-44", "transform"),
        ({"capture_time_ns": 1760000001000000000}, "obs-44", "capture"),
        ({}, "other-frame", "observation"),
        ({"received_at": 9.0}, "obs-44", "stale"),
    ],
)
def test_mismatched_stale_or_cross_observation_data_is_rejected(
    observation_kwargs, object_observation_id, error
):
    candidate, digest = _candidate()
    observation_kwargs = {**observation_kwargs, "digest": digest}
    with pytest.raises((ValueError, TargetResolutionError), match=error):
        resolve_pick_place_candidate(
            candidate,
            _observation(**observation_kwargs),
            _objects(object_observation_id),
            now=10.1,
            max_frame_age_s=0.5,
        )


def test_ambiguous_labels_and_out_of_frame_points_are_rejected():
    candidate, digest = _candidate(target={"label": "red block", "point_yx_1000": [1000, 1000]})
    with pytest.raises(ValueError, match="source observation"):
        resolve_pick_place_candidate(
            candidate, _observation(digest=digest), _objects(), now=10.1, max_frame_age_s=0.5
        )

    candidate, digest = _candidate()
    ambiguous = _objects() + [
        ObjectCandidate("obs-44", "block-2", "red block", (), (190, 140, 200, 150))
    ]
    with pytest.raises(TargetResolutionError, match="ambiguous"):
        resolve_pick_place_candidate(
            candidate, _observation(digest=digest), ambiguous, now=10.1, max_frame_age_s=0.5
        )


def test_label_must_match_the_spatially_selected_object():
    candidate, digest = _candidate(target={"label": "blue block", "point_yx_1000": [500, 500]})
    with pytest.raises(ValueError, match="label"):
        resolve_pick_place_candidate(
            candidate, _observation(digest=digest), _objects(), now=10.1, max_frame_age_s=0.5
        )
