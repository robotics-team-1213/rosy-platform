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


def pose(height=.054, pitch_deg=12., roll_deg=-1.):
    return {'height_above_board_m': height, 'pitch_rad': math.radians(pitch_deg), 'roll_rad': math.radians(roll_deg)}


def test_view_gate_is_2mm_015deg_03deg():
    m = module()
    assert (m.VIEW_HEIGHT_TOL_M, m.VIEW_PITCH_TOL_DEG, m.VIEW_ROLL_TOL_DEG) == (.002, .15, .3)
    assert m.compare_views(pose(), pose(height=.0555), 0)['view_consistency_pass']
    for other in (pose(height=.0565), pose(pitch_deg=12.2), pose(roll_deg=-.6)):
        assert not m.compare_views(pose(), other, 0)['view_consistency_pass']


PLACEMENTS = [pose(.054+d, 12.+p, -1.+r) for d, p, r in
              ((0, 0, 0), (.0004, .03, .05), (-.0003, -.04, -.06), (.0002, .02, .1), (-.0002, -.01, -.08))]


def test_placement_bands_are_the_across_placement_ci95():
    m = module()
    fit = m.placement_fit(PLACEMENTS, board_elevation_m=.006)
    n = len(PLACEMENTS)
    heights = np.array([p['height_above_board_m'] for p in PLACEMENTS])+.006
    assert fit['values']['height_m'] == pytest.approx(heights.mean())
    assert fit['values']['pitch_rad'] == pytest.approx(np.mean([p['pitch_rad'] for p in PLACEMENTS]))
    assert fit['uncertainty']['height_m'] == pytest.approx(2.78*heights.std(ddof=1)/math.sqrt(n))
    pitches = np.degrees([p['pitch_rad'] for p in PLACEMENTS])
    assert fit['uncertainty']['pitch_deg'] == pytest.approx(2.78*pitches.std(ddof=1)/math.sqrt(n))
    assert fit['consistency_pass'] and fit['placements'] == n


def test_reseat_spread_widens_the_band():
    m = module()
    plain = m.placement_fit(PLACEMENTS, board_elevation_m=.006)
    reseated = m.placement_fit(PLACEMENTS, board_elevation_m=.006, reseats=[pose(.0555, 12.4, -1.)])
    mean_pitch = math.degrees(plain['values']['pitch_rad'])
    assert reseated['uncertainty']['pitch_deg'] == pytest.approx((12.4-min(mean_pitch, 12.4))/2)
    assert reseated['uncertainty']['pitch_deg'] > plain['uncertainty']['pitch_deg']
    assert reseated['uncertainty']['height_m'] > plain['uncertainty']['height_m']
    # The re-seat spread widens the band; the values stay the placement mean.
    assert reseated['values'] == plain['values']


def test_fewer_than_five_placements_or_unknown_elevation_are_refused():
    m = module()
    with pytest.raises(ValueError, match='5 placements'):
        m.placement_fit(PLACEMENTS[:4], board_elevation_m=.006)
    with pytest.raises(ValueError, match='elevation'):
        m.placement_fit(PLACEMENTS, board_elevation_m=None)


def test_spread_beyond_the_view_gate_fails_consistency():
    m = module()
    assert not m.placement_fit([*PLACEMENTS[:4], pose(.0575)], board_elevation_m=.006)['consistency_pass']


def test_store_writes_a_camera_profile_candidate_geometry_error_reads(tmp_path):
    import sys
    m = module()
    root = Path(__file__).resolve().parents[3]
    sys.path[:0] = [str(root/'contracts'/'foundation'), str(root/'middleware'/'perception')]
    from core_common.calibration_store import CalibrationStore, check_values
    from control.sensing.perception.lane_containment import geometry_error
    fit = m.placement_fit(PLACEMENTS, board_elevation_m=.006)
    systematic = m.systematic_from_truth(fit, TRUTH)
    record_id = m.store_candidate(CalibrationStore(tmp_path), 'rosy-x', fit, systematic=systematic,
                                  sessions=['p1'], extra={'k': 1})
    store = CalibrationStore(tmp_path)
    rec = store.load('rosy-x', 'camera_profile', record_id)
    assert rec['method'] == 'camera_board/1'
    assert set(rec['values']) == {'pitch_rad', 'roll_rad', 'height_m'}
    assert set(rec['intervals']['uncertainty']) == {'pitch_deg', 'roll_deg', 'height_m'}
    assert rec['intervals']['fit_step'] == {'pitch_deg': 0., 'roll_deg': 0., 'height_m': 0.}
    assert check_values('camera_profile', rec['values']) is None
    assert store.current('rosy-x', 'camera_profile') is None  # a candidate, never accepted here
    profile = {**rec['values'], 'detector_lateral_px': 3.}
    pitch, height, roll, _px = geometry_error(profile, rec['intervals'])
    assert rec['intervals']['systematic'] == systematic
    # No grid floor; the systematic term from the truth check is added to the scatter band.
    assert pitch == pytest.approx(math.radians(fit['uncertainty']['pitch_deg']+systematic['pitch_deg']))
    assert height == pytest.approx(fit['uncertainty']['height_m']+systematic['height_m'])


# Independent truth check (tape-measured lens height, known-geometry target): value, tolerance.
TRUTH = {'pitch_deg': (12.3, .05), 'roll_deg': (-1.3, .05), 'height_m': (.0617, .0005)}


def test_board_bound_covers_truth_once_the_systematic_term_is_included():
    # The synthetic board run read 0.3 deg / 1.7 mm off truth with scatter bands far smaller.
    m = module()
    fit = m.placement_fit(PLACEMENTS, board_elevation_m=.006)
    sysm = m.systematic_from_truth(fit, TRUTH)
    for key, scale in (('pitch_deg', math.degrees(1)), ('roll_deg', math.degrees(1)), ('height_m', 1.)):
        value = fit['values']['height_m' if key == 'height_m' else key.replace('_deg', '_rad')]*scale
        truth, _tol = TRUTH[key]
        assert fit['uncertainty'][key] < abs(value-truth)  # scatter alone misses it
        assert fit['uncertainty'][key]+sysm[key] >= abs(value-truth)
        assert sysm[key] == pytest.approx(abs(value-truth)+TRUTH[key][1])


def test_store_refuses_without_an_independent_truth_check(monkeypatch, tmp_path):
    m = module()
    monkeypatch.setattr(m, 'ROBOT_INSTALL', tmp_path/'absent')
    argv = [a for i in range(5) for a in ('--placement', f'p{i}.png')]
    with pytest.raises(SystemExit):
        m.main([*argv, '--camera-profile', 'p.yaml', '--square-mm', '17', '--board-elevation-mm', '6',
                '--store', 'rosy-x', '--output', str(tmp_path/'o.json')])


def test_board_fit_refuses_to_run_on_a_robot(monkeypatch, tmp_path):
    m = module()
    monkeypatch.setattr(m, 'ROBOT_INSTALL', tmp_path)  # exists: looks like a robot
    with pytest.raises(SystemExit):
        m.main(['--placement', 'a.png', '--camera-profile', 'p.yaml', '--square-mm', '17', '--output', 'o.json'])
