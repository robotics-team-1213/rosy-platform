"""Metric pose fitting, rejection and floor-height provenance."""
import importlib.util
import math
from pathlib import Path

import cv2
import numpy as np
import pytest


def module():
    spec = importlib.util.spec_from_file_location('camera_board', Path(__file__).resolve().parents[1]/'camera_board.py')
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def projected(square=.017, pitch_deg=12):
    shape = (9, 6)
    obj = np.zeros((54, 3), np.float64)
    obj[:, :2] = np.mgrid[0:9, 0:6].T.reshape(-1, 2)*square
    pitch = math.radians(pitch_deg)
    rotation = np.array([[1, 0, 0], [0, -math.sin(pitch), -math.cos(pitch)],
                         [0, math.cos(pitch), -math.sin(pitch)]])
    rv, _ = cv2.Rodrigues(rotation)
    centre = np.array([.06, -.2, .054])
    tv = -rotation@centre
    k = np.array([[281.6, 0, 160], [0, 281.6, 120], [0, 0, 1]], float)
    pixels, _ = cv2.projectPoints(obj, rv, tv, k, None)
    return shape, pixels.reshape(-1, 2), k


def test_known_print_scale_recovers_height_and_pitch():
    shape, points, k = projected()
    result = module().fit_corners(points, shape, k, .017)
    assert result['height_above_board_m'] == pytest.approx(.054, abs=1e-6)
    assert result['pitch_rad'] == pytest.approx(math.radians(12), abs=1e-6)
    assert result['rmse_px'] < 1e-4


def test_bad_corners_and_unknown_print_scale_are_rejected():
    shape, points, k = projected()
    points[20] += [20, -15]
    with pytest.raises(ValueError):
        module().fit_corners(points, shape, k, .017)
    with pytest.raises(ValueError):
        module().fit_corners(points, shape, k, math.nan)


def test_board_thickness_is_not_silently_floor_calibration():
    fit = {'height_above_board_m': .054, 'pitch_rad': .21, 'roll_rad': .01}
    result = module().compare_views(fit, fit, None)
    assert result['height_above_floor_m'] is None
    assert result['applied'] is False
    assert 'board_elevation_unknown' in result['reasons']
    known = module().compare_views(fit, fit, .01)
    assert known['height_above_floor_m'] == pytest.approx(.064)
    assert known['status'] == 'candidate' and known['applied'] is False


def test_independent_view_disagreement_is_not_a_pass():
    a = {'height_above_board_m': .054, 'pitch_rad': .21, 'roll_rad': .01}
    b = dict(a, height_above_board_m=.08, pitch_rad=.28)
    result = module().compare_views(a, b, 0)
    assert not result['view_consistency_pass']
    assert 'view_geometry_disagrees' in result['reasons']


@pytest.mark.parametrize('bad', [np.eye(2), np.diag([-1., 281.6, 1.]), np.diag([281.6, 0., 1.])])
def test_invalid_intrinsics_rejected_before_pose_solver(bad):
    shape, points, _ = projected()
    with pytest.raises(ValueError, match='intrinsics'):
        module().fit_corners(points, shape, bad, .017)


def test_upward_camera_is_not_reported_as_downward():
    shape, points, k = projected(pitch_deg=-5)
    with pytest.raises(ValueError, match='outside floor-camera range'):
        module().fit_corners(points, shape, k, .017)
