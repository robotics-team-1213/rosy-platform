"""Control sensor provider — dock detector factory (DNC-007, D-138).

The provider port (`rosy.sensor_provider`) is the only control surface CORE
resolves (D-126 S1, D-64). The dock detector rides the same port: no new
static import edge, no new entry point.
"""

import numpy as np
import pytest

from control.sensor_provider import PROVIDER


def _tag_frame() -> np.ndarray:
    import cv2
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    marker = (getattr(cv2.aruco, "generateImageMarker", None) or cv2.aruco.drawMarker)(dictionary, 7, 200)
    frame = np.full((480, 640, 3), 255, dtype=np.uint8)
    frame[140:340, 220:420] = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)
    return frame


CAMERA_MATRIX = np.array([[600.0, 0.0, 320.0],
                          [0.0, 600.0, 240.0],
                          [0.0, 0.0, 1.0]])
DIST = np.zeros(5)


def test_provider_exposes_a_dock_detector_factory():
    assert callable(PROVIDER.make_dock_detector)


def test_factory_builds_a_started_detector_from_a_tag_frame():
    detector = PROVIDER.make_dock_detector(
        tag_id=7, tag_size_m=0.10, frame_source=lambda: _tag_frame(),
        camera_matrix=CAMERA_MATRIX, dist_coeffs=DIST, revision="dock-tag-v1")
    detector.start(object())
    obs = detector.relative_pose()
    assert obs is not None
    assert obs.range_m == pytest.approx(0.30, abs=0.02)
    detector.stop()


def test_factory_refuses_a_tag_without_size():
    with pytest.raises(ValueError):
        PROVIDER.make_dock_detector(
            tag_id=7, tag_size_m=0.0, frame_source=lambda: None,
            camera_matrix=CAMERA_MATRIX, dist_coeffs=DIST, revision="dock-tag-v1")
