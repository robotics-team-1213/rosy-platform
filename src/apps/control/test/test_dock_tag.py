"""DNC-007 dock tag detection — ArUco classical CV, synthetic fixtures only.

A dock tag is detected with ``cv2.aruco`` (no YOLO) and converted to a
robot-frame relative pose. An unknown tag id or a missing tag is None, never
a guess — a lost dock must read as lost (DNC-004).
"""

import math

import cv2
import numpy as np
import pytest

from control.sensing.dock_tag import (
    DockTagObservation,
    DockTagSpec,
    detect_dock_tag,
)

DICT = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
SPEC = DockTagSpec(tag_id=7, size_m=0.10, revision="dock-tag-v1")
# Pinhole fixture: fx=fy=600, centre 320x240, no distortion.
CAMERA_MATRIX = np.array([[600.0, 0.0, 320.0],
                          [0.0, 600.0, 240.0],
                          [0.0, 0.0, 1.0]])
DIST = np.zeros(5)


def _marker_canvas(marker_px: int = 200, canvas_wh: tuple[int, int] = (640, 480)) -> np.ndarray:
    """White canvas with one fronto-parallel tag dead centre."""
    marker = (getattr(cv2.aruco, "generateImageMarker", None) or cv2.aruco.drawMarker)(DICT, SPEC.tag_id, marker_px)
    canvas = np.full((canvas_wh[1], canvas_wh[0], 3), 255, dtype=np.uint8)
    x0 = (canvas_wh[0] - marker_px) // 2
    y0 = (canvas_wh[1] - marker_px) // 2
    canvas[y0:y0 + marker_px, x0:x0 + marker_px] = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)
    return canvas


def test_centred_tag_recovers_range_and_zero_bearing():
    frame = _marker_canvas()
    obs = detect_dock_tag(frame, SPEC, CAMERA_MATRIX, DIST)
    assert isinstance(obs, DockTagObservation)
    assert obs.tag_id == SPEC.tag_id
    # Fronto-parallel 200 px tag, fx=600, size 0.10 m -> 0.30 m ahead.
    assert obs.range_m == pytest.approx(0.30, abs=0.02)
    assert obs.x == pytest.approx(0.30, abs=0.02)
    assert obs.y == pytest.approx(0.0, abs=0.01)
    assert obs.yaw == pytest.approx(0.0, abs=0.02)
    assert obs.revision == SPEC.revision


def test_offset_tag_recovers_bearing_sign():
    """Tag right of centre (image +x) means dock is to the robot's right: yaw < 0."""
    frame = _marker_canvas()
    shifted = np.full_like(frame, 255)
    shifted[:, 60:] = frame[:, :580]  # slide the whole scene 60 px right
    obs = detect_dock_tag(shifted, SPEC, CAMERA_MATRIX, DIST)
    assert obs is not None
    assert obs.yaw < 0.0
    # Bearing geometry: atan2(60 px / fx) ≈ 0.0997 rad.
    assert obs.yaw == pytest.approx(-math.atan2(60.0, 600.0), abs=0.02)


def test_empty_frame_is_no_dock_not_a_guess():
    frame = np.full((480, 640, 3), 255, dtype=np.uint8)
    assert detect_dock_tag(frame, SPEC, CAMERA_MATRIX, DIST) is None


def test_unknown_tag_id_is_refused():
    """A tag from another dock family must not parse as ours (SRS: fail-closed)."""
    marker = (getattr(cv2.aruco, "generateImageMarker", None) or cv2.aruco.drawMarker)(DICT, 42, 200)
    canvas = np.full((480, 640, 3), 255, dtype=np.uint8)
    canvas[140:340, 220:420] = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)
    assert detect_dock_tag(canvas, SPEC, CAMERA_MATRIX, DIST) is None


def test_bad_spec_fails_closed():
    with pytest.raises(ValueError):
        DockTagSpec(tag_id=7, size_m=0.0, revision="dock-tag-v1")
    with pytest.raises(ValueError):
        DockTagSpec(tag_id=-1, size_m=0.10, revision="dock-tag-v1")
