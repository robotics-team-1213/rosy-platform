"""Fast unit layer for the station camera SIM: rendered marker -> observed relative pose, no HTTP or ledgers.

The slow pipeline test only reaches these transforms after minutes of SIM time; a render or calibration slip
shows up here in milliseconds. Real HTTP, lifespan, contact and measured-stop contracts stay in the pipeline tests.
"""
import math

import pytest

from core_common.protocol.station_charging import Pose2D, StationObservation
from test_station_camera_pipeline import pipeline_sources  # noqa: F401  (sys.path for rosy_vision)


def _calibration():
    from rosy_vision.station_observation import StationCameraCalibration
    return StationCameraCalibration(station_id='charger-1', source_id='station-camera',
        source_epoch='camera-boot', revision='mount-1', marker_id=7, marker_side_m=0.1,
        marker_mount=Pose2D(x=0., y=0., yaw=math.pi/2),
        image_to_station=(0.001, 0., -0.3, 0., -0.001, 0.3, 0., 0., 1.),
        plane='robot_marker', lens_rectified=True, approved=True, uncertainty_m=0.002, uncertainty_rad=0.005)


def _template():
    return StationObservation.model_validate(dict(
        robot_id='robot-1', station_id='charger-1', session_id='charge-1', boot_id='robot-boot',
        odom_epoch='0', map_id='floor', map_revision='map-1', pose_revision=1,
        source_id='station-camera', source_epoch='camera-boot', calibration_revision='mount-1',
        sequence=1, captured_at=100., valid_until=100.25, frame='base_link', pose=None,
        uncertainty_m=0.002, uncertainty_rad=0.005, visible=False))


def _render(x, y, yaw):
    # Same plant->pixel convention as the pipeline test's render().
    import cv2
    import numpy as np
    from rosy_vision.detect import generate_marker_image
    canvas = np.full((600, 600), 255, dtype=np.uint8)
    cx, cy = round(300+x*1000), round(300-y*1000)
    canvas[cy-50:cy+50, cx-50:cx+50] = generate_marker_image(7, 100)
    canvas = cv2.warpAffine(canvas, cv2.getRotationMatrix2D((cx, cy), math.degrees(yaw), 1.), (600, 600), borderValue=255)
    ok, encoded = cv2.imencode('.jpg', canvas)
    assert ok
    return encoded.tobytes()


@pytest.mark.parametrize('pose', [(-0.10, 0.015, 0.04), (0.1, 0., 0.), (-0.2, -0.05, -0.08), (0., 0.03, 0.1)])
def test_rendered_marker_observes_station_relative_to_robot(pipeline_sources, pose):  # noqa: F811
    from rosy_vision.station_observation import observe_jpeg
    x, y, yaw = pose
    seen = observe_jpeg(_render(x, y, yaw), calibration=_calibration(), template=_template())
    c, s = math.cos(yaw), math.sin(yaw)
    assert seen.visible
    assert seen.pose.x == pytest.approx(-c*x - s*y, abs=0.003)
    assert seen.pose.y == pytest.approx(s*x - c*y, abs=0.003)
    assert seen.pose.yaw == pytest.approx(-yaw, abs=0.02)


def test_blank_frame_is_lost_not_guessed(pipeline_sources):  # noqa: F811
    from rosy_vision.station_observation import observe_jpeg
    import cv2
    import numpy as np
    ok, blank = cv2.imencode('.jpg', np.full((600, 600), 255, dtype=np.uint8))
    assert ok
    lost = observe_jpeg(blank.tobytes(), calibration=_calibration(), template=_template())
    assert not lost.visible and lost.pose is None
