"""DNC-007 dock tag detection — ArUco classical CV, synthetic fixtures only.

A dock tag is detected with ``cv2.aruco`` (no YOLO) and converted to a
robot-frame relative pose. An unknown tag id or a missing tag is None, never
a guess — a lost dock must read as lost (DNC-004).
"""

import math

import cv2
import numpy as np
import pytest

import dock_scene
from control.sensing.dock_tag import (
    DockTagObservation,
    DockTagSpec,
    detect_dock_tag,
)

SPEC = DockTagSpec(tag_id=7, size_m=0.10, revision="dock-tag-v1")
# Pinhole fixture: fx=fy=600, centre 320x240, no distortion.
CAMERA_MATRIX = np.array([[600.0, 0.0, 320.0],
                          [0.0, 600.0, 240.0],
                          [0.0, 0.0, 1.0]])
DIST = np.zeros(5)


def _marker_canvas(marker_px: int = 200, canvas_wh: tuple[int, int] = (640, 480)) -> np.ndarray:
    """White canvas with one fronto-parallel tag dead centre."""
    marker = dock_scene.marker_image(SPEC.tag_id, marker_px)
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
    marker = dock_scene.marker_image(42, 200)
    canvas = np.full((480, 640, 3), 255, dtype=np.uint8)
    canvas[140:340, 220:420] = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)
    assert detect_dock_tag(canvas, SPEC, CAMERA_MATRIX, DIST) is None


def test_bad_spec_fails_closed():
    with pytest.raises(ValueError):
        DockTagSpec(tag_id=7, size_m=0.0, revision="dock-tag-v1")
    with pytest.raises(ValueError):
        DockTagSpec(tag_id=-1, size_m=0.10, revision="dock-tag-v1")


# --- Stage-3 parking wedge: camera extrinsics and the tag's own yaw --------
#
# dock_scene ray-casts the declared Gazebo camera (320x180, pitch 25 deg,
# optical centre 0.0602 m high, 0.034 m ahead of base_link) against the
# inclined wedge tag. With a CameraMount the observation is the tag centre
# in base_link and the yaw of the tag's inward axis (0 when squarely faced),
# not the bearing.


from control.sensing.dock_tag import CameraMount  # noqa: E402

WEDGE_SPEC = DockTagSpec(tag_id=dock_scene.TAG_ID, size_m=dock_scene.TAG_SIZE_M)
MOUNT = CameraMount(height_m=dock_scene.HEIGHT_M, pitch_rad=dock_scene.PITCH_RAD,
                    x_offset_m=dock_scene.CAM_X)


def _wedge(pose):
    return detect_dock_tag(dock_scene.render(pose), WEDGE_SPEC,
                           dock_scene.CAMERA_MATRIX, dock_scene.DIST, mount=MOUNT)


def test_at_the_spot_the_wedge_tag_is_placed_in_base_link():
    obs = _wedge(dock_scene.SPOT)
    x, y, yaw = dock_scene.truth(dock_scene.SPOT)
    assert obs is not None and obs.tag_id == 7
    assert obs.x == pytest.approx(x, abs=0.004)
    assert obs.y == pytest.approx(y, abs=0.002)
    assert obs.yaw == pytest.approx(yaw, abs=math.radians(1.0))
    assert obs.range_m == pytest.approx(math.hypot(obs.x, obs.y))


@pytest.mark.parametrize("pose", [
    (-1.00, 0.020, 0.0),
    (-1.00, -0.020, math.radians(5.0)),
    (-1.03, 0.015, math.radians(-3.0)),
    (-1.05, 0.010, math.radians(-5.0)),
    (-1.08, -0.025, math.radians(6.0)),
    (-1.10, -0.020, math.radians(4.0)),
    (-1.10, 0.030, math.radians(-8.0)),
])
def test_off_axis_poses_recover_position_and_the_tags_own_yaw(pose):
    """Within the approach's envelope: x/y within a few mm, yaw within 1.5
    deg. The yaw is the tag's orientation (from rvec), not the bearing: at
    a lateral offset with the robot parallel to the dock axis the bearing is
    several degrees, the yaw zero."""
    obs = _wedge(pose)
    x, y, yaw = dock_scene.truth(pose)
    assert obs is not None, pose
    assert obs.x == pytest.approx(x, abs=0.005)
    assert obs.y == pytest.approx(y, abs=0.004)
    assert obs.yaw == pytest.approx(yaw, abs=math.radians(1.5))


def test_the_yaw_is_orientation_not_bearing():
    pose = (-1.0, 0.025, 0.0)
    obs = _wedge(pose)
    bearing = math.atan2(obs.y, obs.x)
    assert abs(bearing) > math.radians(4.0)
    assert obs.yaw == pytest.approx(0.0, abs=math.radians(1.0))


def test_without_a_mount_the_wedge_reads_as_the_old_bearing_contract():
    """The DNC-007 path is unchanged: no mount, camera-frame range and a
    bearing yaw (which ignores the 25 deg pitch and the 0.034 m offset)."""
    frame = dock_scene.render(dock_scene.SPOT)
    old = detect_dock_tag(frame, WEDGE_SPEC, dock_scene.CAMERA_MATRIX, dock_scene.DIST)
    new = detect_dock_tag(frame, WEDGE_SPEC, dock_scene.CAMERA_MATRIX, dock_scene.DIST,
                          mount=MOUNT)
    assert old.yaw == pytest.approx(math.atan2(old.y, old.x))
    assert new.x - old.x == pytest.approx(dock_scene.CAM_X, abs=0.02)


def test_the_flipped_ippe_solution_is_never_chosen():
    """IPPE returns two poses for a small oblique square; the wrong one has
    the face normal pointing down into the floor. The tag stands on the
    floor facing up, so only the upward normal can be it."""
    for pose in [(-1.0, 0.0, 0.0), (-1.0, 0.02, 0.0), (-1.1, -0.02, math.radians(4.0))]:
        obs = _wedge(pose)
        assert obs is not None
        assert obs.yaw == pytest.approx(dock_scene.truth(pose)[2], abs=math.radians(1.5))


def test_from_the_spur_entry_the_wedge_is_out_of_view():
    """The camera sees nothing above ~2 cm at the entry's range: the tag's
    top is cut and nothing is reported (the manager creeps on odometry)."""
    assert _wedge(dock_scene.ENTRY) is None
    assert _wedge((-1.10, 0.0, 0.0)) is not None


def test_a_bad_mount_fails_closed():
    with pytest.raises(ValueError):
        CameraMount(height_m=0.0, pitch_rad=0.4)
    with pytest.raises(ValueError):
        CameraMount(height_m=0.06, pitch_rad=float("nan"))


# --- OpenCV API generations ------------------------------------------------
#
# The ROS box (Ubuntu 24.04, apt python3-opencv 4.6.0) has the pre-4.7
# aruco API: no ArucoDetector, parameters from DetectorParameters_create(),
# detection through the free function detectMarkers(). There a bare
# DetectorParameters() wraps a null pointer and setting any field on it
# segfaults the interpreter — dock_observer_node died with exit -11 at
# import in all three Gazebo missions. The host has OpenCV >= 4.7.


class _NullPointerParameters:
    """4.6's bare DetectorParameters(): touching a field is a native crash,
    modelled here as an exception so the test survives it."""

    def __setattr__(self, name, value):
        raise AssertionError("DetectorParameters() is a null pointer before OpenCV 4.7")


class _LegacyAruco:
    """cv2.aruco as OpenCV 4.6 exposes it, delegating to the host's own."""

    DICT_4X4_50 = cv2.aruco.DICT_4X4_50
    CORNER_REFINE_SUBPIX = cv2.aruco.CORNER_REFINE_SUBPIX
    getPredefinedDictionary = staticmethod(cv2.aruco.getPredefinedDictionary)
    DetectorParameters = _NullPointerParameters

    def __init__(self):
        self.calls = []

    @staticmethod
    def DetectorParameters_create():
        create = getattr(cv2.aruco, "DetectorParameters_create", None)
        return create() if create is not None else cv2.aruco.DetectorParameters()

    def detectMarkers(self, image, dictionary, parameters=None):
        self.calls.append(parameters)
        if not hasattr(cv2.aruco, "ArucoDetector"):   # this host is itself pre-4.7
            return cv2.aruco.detectMarkers(image, dictionary, parameters=parameters)
        return cv2.aruco.ArucoDetector(dictionary, parameters).detectMarkers(image)


def test_the_pre_4_7_aruco_api_detects_with_subpixel_corners():
    from control.sensing.dock_tag import _marker_detector

    legacy = _LegacyAruco()
    detect = _marker_detector(legacy)
    frame = cv2.cvtColor(_marker_canvas(), cv2.COLOR_BGR2GRAY)
    _, ids, _ = detect(frame)
    assert ids is not None and [int(i) for i in ids.flatten()] == [SPEC.tag_id]
    assert len(legacy.calls) == 1
    assert legacy.calls[0].cornerRefinementMethod == cv2.aruco.CORNER_REFINE_SUBPIX


def test_the_current_aruco_api_detects_with_subpixel_corners():
    from control.sensing.dock_tag import _detector_parameters, _marker_detector

    assert _detector_parameters(cv2.aruco).cornerRefinementMethod \
        == cv2.aruco.CORNER_REFINE_SUBPIX
    _, ids, _ = _marker_detector(cv2.aruco)(cv2.cvtColor(_marker_canvas(), cv2.COLOR_BGR2GRAY))
    assert [int(i) for i in ids.flatten()] == [SPEC.tag_id]


def test_the_module_imports_in_a_fresh_interpreter():
    """A native crash at import (exit -11) kills the node before it logs a
    line; in-process imports cannot see it, a child interpreter can."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    package_root = str(Path(__file__).resolve().parents[1])
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [package_root] + [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p])
    result = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", "import control.sensing.dock_tag"],
        env=env, capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, (result.returncode, result.stderr[-2000:])
