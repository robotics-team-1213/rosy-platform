"""Station-local camera geometry and independent map anchors are different measurements."""
import importlib
import importlib.util
import math

import cv2
import numpy as np
import pytest

from core_common.protocol.station_charging import MapPoseEvidence, Pose2D, StationObservation
from rosy_vision.detect import generate_marker_image


def producer():
    name = 'rosy_vision.station_observation'
    assert importlib.util.find_spec(name) is not None, 'station camera producer is not implemented'
    return importlib.import_module(name)


def template(**changes):
    return StationObservation.model_validate(dict(
        robot_id='robot-1', station_id='charger-1', session_id='charge-1', boot_id='robot-boot',
        odom_epoch='odom-1', map_id='floor', map_revision='map-1', pose_revision=1,
        source_id='station-camera', source_epoch='camera-boot', calibration_revision='mount-1',
        sequence=1, captured_at=100.0, valid_until=100.5, frame='base_link', pose=None,
        uncertainty_m=0.002, uncertainty_rad=0.005, visible=False) | changes)


def anchor(**changes):
    return MapPoseEvidence.model_validate(dict(
        robot_id='robot-1', boot_id='robot-boot', odom_epoch='odom-1',
        map_id='floor', map_revision='map-1', captured_at=100.0, valid_until=100.5,
        source_id='ceiling-camera', source_epoch='ceiling-boot', calibration_revision='map-cal',
        pose={'x': 1.0, 'y': 2.0, 'yaw': math.pi / 2},
        uncertainty_m=0.003, uncertainty_rad=0.005) | changes)


def test_relative_pose_and_independent_robot_anchor_locate_moved_station():
    module = producer()
    relative = template(visible=True, pose={'x': 0.3, 'y': 0.1, 'yaw': -0.2})
    result = module.station_map_pose(anchor(), relative, approach_offset_m=0.5)
    assert result.pose.x == pytest.approx(0.9)
    assert result.pose.y == pytest.approx(2.3)
    assert result.pose.yaw == pytest.approx(math.pi / 2 - 0.2)
    assert result.status == 'CANDIDATE'
    assert not result.approach_verified
    assert result.uncertainty_m >= 0.003 + 0.002


@pytest.mark.parametrize('changes', [dict(source_id='station-camera'), dict(captured_at=99.9),
                                    dict(odom_epoch='restarted'), dict(map_revision='other'),
                                    dict(boot_id='other'), dict(robot_id='robot-2')])
def test_dependent_or_unpaired_map_anchor_cannot_confirm_absolute_location(changes):
    module = producer()
    with pytest.raises(ValueError):
        module.station_map_pose(anchor(**changes), template(visible=True, pose={'x': 0.3, 'y': 0.0, 'yaw': 0.0}),
                                approach_offset_m=0.5)


def test_jpeg_marker_uses_station_calibration_and_measured_robot_mount():
    module = producer()
    image = np.full((300, 300), 255, dtype=np.uint8)
    image[100:200, 100:200] = generate_marker_image(7, 100)
    ok, encoded = cv2.imencode('.jpg', image)
    assert ok
    calibration = module.StationCameraCalibration(
        station_id='charger-1', source_id='station-camera', source_epoch='camera-boot', revision='mount-1',
        marker_id=7, marker_side_m=0.1, marker_mount=Pose2D(x=0.02, y=0.0, yaw=math.pi / 2),
        image_to_station=(0.001, 0.0, 0.0, 0.0, -0.001, 0.0, 0.0, 0.0, 1.0),
        plane='robot_marker', lens_rectified=True, approved=True,
        uncertainty_m=0.002, uncertainty_rad=0.005)
    seen = module.observe_jpeg(encoded.tobytes(), calibration=calibration, template=template())
    assert seen.visible
    assert seen.pose.x == pytest.approx(-0.1295, abs=0.003)
    assert seen.pose.y == pytest.approx(0.1495, abs=0.003)
    assert seen.pose.yaw == pytest.approx(0.0, abs=0.02)
    lost = module.observe_jpeg(b'', calibration=calibration, template=template(sequence=2))
    assert not lost.visible and lost.pose is None
    with pytest.raises(ValueError):
        module.observe_jpeg(encoded.tobytes(), calibration=calibration,
                            template=template(calibration_revision='old-cal'))
