"""Short current-lane alignment needs connected source-mask support."""
import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from control.sensing.perception.drivable.drivable_steer import DrivableSteer
from test_drivable_exit_admission import G, POSE, raw
from test_observed_recentre_alignment import guarded, step


@pytest.mark.parametrize('fixture,target,count,here,guide', [
    ('drivable_local_floor_20261020.json', (.223, -.091), 20, -17.77, 53.5),
    ('drivable_near_floor_20261020.json', (.227, -.09), 42, -18.56, 42.37),
])
@pytest.mark.parametrize('yaw', [0., -.05])
def test_recorded_screen_edge_floor_bounds_the_opposing_guide_alignment(fixture, target, count, here, guide, yaw):
    from control.sensing.perception.drivable.drivable_steer import way_target
    doc = json.loads((Path(__file__).parent / 'fixtures' / fixture).read_text())
    way = np.zeros(doc['shape'], bool)
    for row, runs in enumerate(doc['way_runs']):
        for start, end in runs:
            way[row, start:end] = True
    assert hashlib.sha256(np.packbits(way).tobytes()).hexdigest() == doc['packbits_sha256']
    raw_info = way_target(way, G, .03317, .0925)
    assert raw_info['target_m'] == target
    floor = raw_info['local_floor_m']
    assert len(floor) == count and .16 < floor[-1][0] < .18
    owner = DrivableSteer()
    first = owner.update(way, 1., G, .03317, .0925, POSE, POSE,
        guide_here_deg=here, guide_deg=guide, observed_only=True, current_stamp=1.125)[2]
    error, confidence, info = owner.update(way, 1., G, .03317, .0925, POSE, (0., 0., yaw),
        guide_here_deg=here, guide_deg=guide, observed_only=True, current_stamp=1.25)
    assert (error, confidence, info['strategy']) == (.5, .35, 'drivable_recentre_pivot_right')
    assert info['alignment_used_rad'] == pytest.approx(abs(yaw), abs=.0001)
    assert info['alignment_limit_rad'] == first['alignment_limit_rad']


@pytest.mark.parametrize('memory', [False, True])
@pytest.mark.parametrize('guide', [30., 53.])
def test_opposite_observation_keeps_its_side_and_falls_through_to_explicit_guide(monkeypatch, memory, guide):
    import control.sensing.perception.drivable.drivable_steer as module
    observation = raw()
    observation.update(target_m=(.15, -.1), ahead_m=0., exit=None, seen_exit=None,
                       exit_near={}, exit_point_m={}, exit_reach_m={})
    monkeypatch.setattr(module, 'way_target', lambda *args: copy.deepcopy(observation))
    owner = DrivableSteer()
    if memory:
        owner._memory = ('right', POSE)
    error, confidence, info = owner.update(np.ones((240, 320), bool), 1., G, .03317, .0925, POSE, POSE,
                                         guide_here_deg=-18., guide_deg=guide)
    assert info.get('exit_from_guide')
    assert not info.get('exit_from_target') and not info.get('exit_from_memory')
    assert info['exit_point_m'] == {}
    assert (error, confidence, info['strategy']) == (-.5, .35, 'drivable_pivot_left')


def support(way=None, rows=None, cols=None):
    from control.sensing.perception.drivable.target import _floor_prefix
    rows = np.array([6, 7, 8, 9] if rows is None else rows)
    cols = np.array([2, 3, 4, 5] if cols is None else cols)
    xs = np.array([.17, .16, .15, .14])
    return _floor_prefix(np.ones((10, 10), bool) if way is None else way,
                         rows, cols, xs, np.array([-.08] * 4))


def test_guide_look_checks_the_target_in_current_coordinates(monkeypatch):
    import control.sensing.perception.drivable.drivable_steer as module
    observation = raw()
    observation.update(target_m=(.15, .02), ahead_m=0., exit=None, seen_exit=None,
                       exit_near={}, exit_point_m={}, exit_reach_m={})
    monkeypatch.setattr(module, 'way_target', lambda *args: copy.deepcopy(observation))
    error, confidence, info = DrivableSteer().update(np.ones((240, 320), bool), 1., G, .03317, .0925,
        POSE, (0., 0., .2), guide_here_deg=-18., guide_deg=30., current_stamp=1.25)
    assert info.get('exit_from_guide')
    assert (error, confidence, info['strategy']) == (-.5, .35, 'drivable_pivot_left')


@pytest.mark.parametrize('memory', [False, True])
def test_synthetic_exits_cannot_drive_to_a_target_that_turned_opposite_after_capture(monkeypatch, memory):
    import control.sensing.perception.drivable.drivable_steer as module
    observation = raw()
    observation.update(target_m=(.15, .1), ahead_m=0., exit=None, seen_exit=None,
                       exit_near={}, exit_point_m={}, exit_reach_m={})
    monkeypatch.setattr(module, 'way_target', lambda *args: copy.deepcopy(observation))
    owner = DrivableSteer()
    if memory:
        owner._memory = ('left', POSE)
    error, confidence, info = owner.update(np.ones((240, 320), bool), 1., G, .03317, .0925,
        POSE, (0., 0., .8), guide_here_deg=0., guide_deg=30., current_stamp=2.)
    assert not info.get('exit_from_target')
    assert info.get('exit_from_memory' if memory else 'exit_from_guide')
    assert (error, confidence, info['strategy']) == (-.5, .35, 'drivable_pivot_left')


def test_floor_prefix_preserves_actual_raw_points_without_interpolation():
    assert support() == [(.14, -.08), (.15, -.08), (.16, -.08), (.17, -.08)]


def test_offscreen_clip_is_reprojected_and_cannot_jump_to_other_floor_or_use_only_distant_floor():
    from control.sensing.perception.drivable.target import _local_floor
    way = np.ones((240, 320), bool)
    rows, xs, centre = np.arange(236, 240), np.array([.17, .16, .15, .14]), np.full(4, -.2)
    points = _local_floor(way, rows, xs, centre, G, .18)
    assert len(points) == 4 and all(-.1 < y < 0. for _, y in points)
    assert _local_floor(way, rows, xs + .04, centre, G, .18) == []
    way[239, 319] = False
    assert _local_floor(way, rows, xs, centre, G, .18) == []


def test_connected_far_floor_does_not_remove_the_verified_near_alignment_region():
    from control.sensing.perception.drivable.target import _local_floor
    way, rows = np.ones((240, 320), bool), np.arange(234, 240)
    points = _local_floor(way, rows, np.array([.3, .2, .17, .16, .15, .14]), np.full(6, -.2), G, .18)
    assert [x for x, _ in points] == [.14, .15, .16, .17]


@pytest.mark.parametrize('hole', [(8, 4), (9, 5), (8, 6)])
def test_floor_prefix_rejects_a_hole_in_centres_or_the_connecting_segment(hole):
    way = np.ones((10, 10), bool)
    way[hole] = False
    cols = [2, 3, 7, 5] if hole == (8, 6) else None
    assert len(support(way, cols=cols)) < 4


@pytest.mark.parametrize('rows,cols', [([3, 7, 8, 9], None), (None, [2, 3, 4, 10])])
def test_floor_prefix_stops_at_missing_rows_or_outside_mask(rows, cols):
    assert len(support(rows=rows, cols=cols)) < 4


def local_info(points=None):
    return dict(strategy='drivable_pivot_left', target_m=(.223, -.091), ahead_m=0.,
        near_centre_m=(.157, -.082), seen_exit=None, exit='left', exit_reach_m={},
        exit_point_m={}, centre_path_m=[], straddle=None,
        local_floor_m=[(.148, -.079), (.15, -.08), (.16, -.08), (.167, -.078)] if points is None else points)


def test_verified_local_floor_aligns_before_the_opposite_future_pivot():
    owner, guard = guarded()
    owner._ctx.update(here=-18., ahead=53.)
    error, confidence, info = step(owner, guard, info=local_info(), error=-.5, confidence=.35)
    assert (error, confidence, info['strategy']) == (.5, .35, 'drivable_recentre_pivot_right')
    assert 0. < info['alignment_limit_rad'] < .5


def test_local_floor_alignment_cannot_renew_its_budget_without_progress():
    owner, guard = guarded()
    owner._ctx.update(here=-18., ahead=53.)
    for i in range(7):
        result = step(owner, guard, yaw=-i * .1, info=local_info(), error=-.5, confidence=.35)
    assert result[0] is None and result[2]['reason'] == 'recentre_alignment_spent'


@pytest.mark.parametrize('points', [[], [(.14, -.08)] * 3,
    [(.14, -.08), (.15, -.08), (.17, -.08), (.19, -.08)],
    [(.14, -.08), (.15, .08), (.16, -.08), (.17, -.08)]])
def test_unproved_or_long_or_opposing_floor_cannot_start_local_alignment(points):
    owner, guard = guarded()
    owner._ctx.update(here=-18., ahead=53.)
    assert step(owner, guard, info=local_info(points), error=-.5, confidence=.35)[2]['strategy'] == 'drivable_pivot_left'


def test_short_source_floor_must_remain_short_in_current_coordinates():
    owner, guard = guarded()
    owner._ctx.update(here=-18., ahead=53.)
    assert guard.step(-.5, .35, local_info(), (-.014, 0., 0.), owner, source_pose=POSE,
        current_stamp=.15, observation_stamp=0.)[2]['strategy'] == 'drivable_pivot_left'


def test_a_current_roi_cannot_skip_a_first_point_behind_the_robot():
    owner, guard = guarded()
    owner._ctx.update(here=-18., ahead=53.)
    assert guard.step(-.5, .35, local_info(), (.15, 0., 0.), owner, source_pose=POSE,
        current_stamp=1.5, observation_stamp=0.)[2]['strategy'] == 'drivable_pivot_left'
