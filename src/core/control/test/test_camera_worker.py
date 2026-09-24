from __future__ import annotations

import numpy as np
import pytest

from control.sensing.camera_worker import (
    CameraFrame,
    CameraPreprocessProfile,
    CameraPreprocessWorker,
)


def _classifier(image, *, floor_hsv):
    return {
        "quality": {"valid": True, "reason": "usable"},
        "floor_hsv": (1.0, 2.0, 3.0),
        "shape_seen": tuple(image.shape),
        "floor_seen": floor_hsv,
    }


def test_profile_rejects_unbounded_device_capture_values():
    with pytest.raises(ValueError):
        CameraPreprocessProfile(width=7)
    with pytest.raises(ValueError):
        CameraPreprocessProfile(fps=0.1)
    with pytest.raises(ValueError):
        CameraPreprocessProfile(rotate_deg=45)
    with pytest.raises(ValueError):
        CameraPreprocessProfile(revision=" bad")


def test_worker_rotates_frame_and_carries_profile_revision():
    image = np.zeros((8, 12, 3), dtype=np.uint8)
    image[0, 0] = (1, 2, 3)
    worker = CameraPreprocessWorker(
        CameraPreprocessProfile(width=12, height=8, rotate_deg=90,
                                revision="camera-cal-7"),
        classifier=_classifier,
        memory_reader=lambda: 1234,
    )

    processed = worker.process(CameraFrame(0, 100.0, image))

    assert processed.pixels.shape == (12, 8, 3)
    assert processed.result["shape_seen"] == (12, 8, 3)
    assert processed.result["floor_seen"] is None
    assert processed.telemetry.profile_revision == "camera-cal-7"
    assert processed.telemetry.image_size == (8, 12)
    assert processed.telemetry.memory_bytes == 1234


def test_worker_accounts_gaps_and_holds_out_of_order_frames():
    calls = []

    def classifier(image, *, floor_hsv):
        calls.append(1)
        return {"quality": {"valid": True, "reason": "usable"}, "floor_hsv": None}

    worker = CameraPreprocessWorker(
        CameraPreprocessProfile(width=8, height=8), classifier=classifier)
    frame = np.zeros((8, 8, 3), dtype=np.uint8)
    first = worker.process(CameraFrame(10, 0.0, frame))
    skipped = worker.process(CameraFrame(13, 0.0, frame))
    old = worker.process(CameraFrame(12, 0.0, frame))

    assert first.telemetry.dropped_frames == 0
    assert skipped.telemetry.dropped_frames == 2
    assert old.telemetry.dropped_frames == 3
    assert old.telemetry.quality_reason == "out_of_order_frame"
    assert len(calls) == 2


def test_invalid_frame_is_reported_as_camera_unavailable():
    worker = CameraPreprocessWorker(
        CameraPreprocessProfile(width=8, height=8), classifier=_classifier)
    processed = worker.process(CameraFrame(0, 0.0, np.zeros((4, 4), dtype=np.uint8)))

    assert processed.telemetry.quality_valid is False
    assert processed.telemetry.quality_reason == "invalid_image"
    assert processed.result["quality"]["valid"] is False


def test_wrong_resolution_and_classifier_failure_fail_closed():
    worker = CameraPreprocessWorker(
        CameraPreprocessProfile(width=8, height=8), classifier=lambda *_args, **_kwargs: 3)
    wrong_size = worker.process(
        CameraFrame(0, 0.0, np.zeros((10, 8, 3), dtype=np.uint8)))
    bad_callback = worker.process(
        CameraFrame(1, 0.0, np.zeros((8, 8, 3), dtype=np.uint8)))

    assert wrong_size.telemetry.quality_reason == "resolution_mismatch"
    assert bad_callback.telemetry.quality_reason == "classifier_error"


def test_latency_budget_fails_closed():
    ticks = iter([10.0, 10.2])
    worker = CameraPreprocessWorker(
        CameraPreprocessProfile(max_latency_ms=100.0),
        classifier=_classifier,
        monotonic=lambda: next(ticks),
    )
    frame = np.zeros((8, 8, 3), dtype=np.uint8)

    processed = worker.process(CameraFrame(0, 0.0, frame))

    assert processed.telemetry.processing_latency_ms == pytest.approx(200.0)
    assert processed.telemetry.quality_reason == "latency_budget_exceeded"
    assert processed.result["quality"]["valid"] is False


def test_telemetry_is_secret_free_and_json_ready():
    worker = CameraPreprocessWorker(
        CameraPreprocessProfile(width=8, height=8),
        classifier=_classifier,
        memory_reader=lambda: None,
    )
    telemetry = worker.process(
        CameraFrame(2, 100.0, np.zeros((8, 8, 3), dtype=np.uint8))
    ).telemetry.as_dict()

    assert telemetry["frame_id"] == 2
    assert telemetry["image_size"] == [8, 8]
    assert "path" not in str(telemetry)
    assert "token" not in str(telemetry)
