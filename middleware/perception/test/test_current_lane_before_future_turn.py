"""A future junction cannot pull a visible current-lane candidate the other way.

The positive fixture is decision geometry from e434's second lap at 91.125 s,
not a full-mask replay. The same-source SIM remains the behavioral acceptance.
"""
import copy
import math

import numpy as np
import pytest

from control.sensing.perception.drivable.drivable_steer import DrivableSteer
from control.sensing.perception.drivable.route_guard import RouteBridge


SOURCE = (-0.43166082062904765, 0.1921595023595398, -2.8951015454313076)
CURRENT = (-0.43610298998410557, 0.19107928933970564, -2.9113121660113865)
RECORDED = dict(strategy='drivable_turn_right', reason=None, target_m=(0.238, 0.066),
    target_now_m=(0.179, -0.081), ahead_m=0.186, near_centre_m=(0.162, 0.0),
    exit='right', seen_exit='right', exit_reach_m={'left': 0.186, 'right': 0.194},
    exit_point_m={'left': (0.183, 0.089), 'right': (0.186, -0.09)},
    straddle=None, both=False)


def candidate(info=None, *, context=None, source=SOURCE, current=CURRENT, stamp=91.125, observed=91.0, edges=()):
    owner = DrivableSteer()
    owner._ctx = {**dict(guide=True, fresh=True, here=9.556876300408135, ahead=-75.08783022157792),
                  **(context or {})}
    owner._edges = list(edges)
    info = copy.deepcopy(RECORDED if info is None else info)
    error = owner.pursuit_error(*RECORDED['target_now_m'], 0.6)
    output = RouteBridge().step(error, 0.6, info, current, owner, source_pose=source,
                               current_stamp=stamp, observation_stamp=observed)
    return output, owner, error


def test_recorded_current_lane_target_wins_over_the_future_opposite_arc():
    (error, confidence, info), owner, old_error = candidate()
    assert old_error > 0
    assert error < 0 and confidence == 0.6
    assert info['strategy'] == 'drivable_centre' and info['future_turn_deferred']
    assert info['target_now_m'][0] > 0 and info['target_now_m'][1] > 0


def test_current_lane_selection_rejects_a_remembered_boundary_crossing():
    edges = [(0.1, float(y)) for y in np.linspace(-0.15, 0.15, 100)]
    (error, _, info), _, old_error = candidate(source=(0., 0., 0.), current=(0., 0., 0.), edges=edges)
    assert error == old_error and not info.get('future_turn_deferred')


@pytest.mark.parametrize('evidence', [
    {'exit_near': {'right': True}},
    {'exit_near': {'left': True}, 'exit_from_route_memory': True},
])
def test_an_admitted_route_junction_is_not_a_future_turn(evidence):
    # 4d0 SIM89.125/89.625: current near junction, then its bounded observed point.
    (error, confidence, info), _, old_error = candidate(dict(RECORDED, **evidence))
    assert error == old_error and confidence == .6
    assert info['strategy'] == 'drivable_turn_right'
    assert not info.get('future_turn_deferred')


def test_full_steer_defers_the_recorded_opposite_future_turn(monkeypatch):
    import control.sensing.perception.drivable.drivable_steer as module
    raw = {k: v for k, v in RECORDED.items() if k not in ('strategy', 'reason', 'target_now_m')}
    raw.update(edges_m=[], near_edges_m={}, centre_path_m=[])
    monkeypatch.setattr(module, 'way_target', lambda *args: copy.deepcopy(raw))
    owner = DrivableSteer()
    error, confidence, info = owner.update(np.ones((240, 320), bool), 91.0, None, 0.033, 0.0925,
        SOURCE, CURRENT, observed_only=True, current_stamp=91.125, guide_fresh=True,
        guide_here_deg=9.556876300408135, guide_deg=-75.08783022157792, guide_pivot_ok=False)
    assert error < 0 and confidence > owner._pivot_confidence
    assert info['strategy'] == 'drivable_centre' and info['future_turn_deferred']


@pytest.mark.parametrize('change', [
    {'strategy': 'drivable_pivot_right'}, {'strategy': 'drivable_off_line_left', 'straddle': 'left'},
    {'front_blocked_m': 0.1}, {'crosswalk_hold': True}, {'pivot_limit': True},
    {'ahead_m': 0.1}, {'near_centre_m': (0.162, 0.08)}, {'target_m': (0.2, -0.06)},
    {'target_m': (0.12, 0.06)}, {'target_m': None}, {'target_m': (math.nan, 0.06)},
])
def test_current_lane_selection_does_not_replace_inadmissible_or_protected_candidates(change):
    raw = dict(RECORDED, **change)
    (error, confidence, info), _, old_error = candidate(raw)
    assert error == old_error and confidence == 0.6
    assert not info.get('future_turn_deferred')


@pytest.mark.parametrize('context', [
    {'guide': False}, {'fresh': False}, {'here': None}, {'here': math.nan},
    {'ahead': None}, {'here': -75.0}, {'ahead': 10.0},
])
def test_a_current_lane_choice_requires_distinct_fresh_current_direction(context):
    (error, _, info), _, old_error = candidate(context=context)
    assert error == old_error and not info.get('future_turn_deferred')


@pytest.mark.parametrize('values', [
    {'source': None}, {'current': None}, {'stamp': 93.0}, {'stamp': 90.9},
    {'current': (2.0, 0.0, 0.0)},
])
def test_current_lane_selection_requires_source_current_odometry_and_fresh_observation(values):
    (error, _, info), _, old_error = candidate(**values)
    assert error == old_error and not info.get('future_turn_deferred')
