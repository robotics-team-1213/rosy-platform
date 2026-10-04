"""DNC-007 ArUco dock detector — lifecycle adapter over `dock_tag` detection.

The detector implements the docking `DockDetector` shape
(`start`/`relative_pose`/`stop`) structurally without importing it: the
manager only calls those methods and reads `range_m`/`x`/`y`, so no
core→control import edge is added (D-64: control imports arrive through the
sensor adapter only). Wiring (factory injection) is a later step.
"""

import math

import cv2
import numpy as np
import pytest

from control.sensing.dock_detector import ArucoDockDetector


def _tag_frame(tag_id: int = 7, marker_px: int = 200) -> np.ndarray:
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    marker = (getattr(cv2.aruco, "generateImageMarker", None) or cv2.aruco.drawMarker)(dictionary, tag_id, marker_px)
    frame = np.full((480, 640, 3), 255, dtype=np.uint8)
    frame[140:340, 220:420] = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)
    return frame


CAMERA_MATRIX = np.array([[600.0, 0.0, 320.0],
                          [0.0, 600.0, 240.0],
                          [0.0, 0.0, 1.0]])
DIST = np.zeros(5)


def _detector(frame, tag_id: int = 7, size_m: float = 0.10) -> ArucoDockDetector:
    return ArucoDockDetector(
        frame_source=lambda: frame,
        tag_id=tag_id, tag_size_m=size_m,
        camera_matrix=CAMERA_MATRIX, dist_coeffs=DIST,
        revision="dock-tag-v1",
    )


def test_started_detector_reports_range_from_a_tag_frame():
    detector = _detector(_tag_frame())
    detector.start(object())
    obs = detector.relative_pose()
    assert obs is not None
    assert obs.range_m == pytest.approx(0.30, abs=0.02)
    assert obs.tag_id == 7
    detector.stop()


def test_unstarted_detector_reports_nothing():
    detector = _detector(_tag_frame())
    assert detector.relative_pose() is None


def test_stopped_detector_reports_nothing():
    detector = _detector(_tag_frame())
    detector.start(object())
    assert detector.relative_pose() is not None
    detector.stop()
    assert detector.relative_pose() is None


def test_empty_frame_is_no_dock():
    detector = _detector(np.full((480, 640, 3), 255, dtype=np.uint8))
    detector.start(object())
    assert detector.relative_pose() is None
    detector.stop()


def test_foreign_tag_is_refused():
    detector = _detector(_tag_frame(tag_id=42))
    detector.start(object())
    assert detector.relative_pose() is None
    detector.stop()


def test_observations_carry_confidence_and_capture_time():
    """The docking manager's loss accounting reads freshness, not frames."""
    now = [1000.0]
    detector = ArucoDockDetector(
        frame_source=lambda: _tag_frame(),
        tag_id=7, tag_size_m=0.10,
        camera_matrix=CAMERA_MATRIX, dist_coeffs=DIST,
        revision="dock-tag-v1", clock=lambda: now[0],
    )
    detector.start(object())
    first = detector.relative_pose()
    assert first is not None
    assert first.at == pytest.approx(1000.0)
    assert 0.0 < first.confidence <= 1.0
    now[0] += 0.5
    second = detector.relative_pose()
    assert second is not None and second.at == pytest.approx(1000.5)
    detector.stop()


def test_missing_tag_size_fails_closed():
    with pytest.raises(ValueError):
        ArucoDockDetector(frame_source=lambda: None, tag_id=7, tag_size_m=0.0,
                          camera_matrix=CAMERA_MATRIX, dist_coeffs=DIST,
                          revision="dock-tag-v1")
