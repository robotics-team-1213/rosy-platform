"""Recorded ring_n stall: align to observed floor before a future route bend."""
import copy
import math

import pytest

from control.sensing.perception.drivable.drivable_steer import DrivableSteer, PIVOT_ERROR
from control.sensing.perception.drivable.route_guard import BRIDGE_MAX_M, RouteBridge


# sim-bafb32dc10-0cfcfb, source camera stamp 120.500, decision stamp 120.625.
# The sampled mask and source image are bound in the external matched-snapshot.json.
STALLED = dict(strategy='none', reason='drivable_closed', recentre_first=True,
               target_m=(0.111, 0.104), ahead_m=0.0, near_centre_m=(0.159, 0.101),
               seen_exit='left', exit=None, exit_reach_m={'left': 0.186},
               exit_point_m={'left': (0.183, 0.089), 'right': (0.1375, -0.0585)},
               guide_deg=-68.8, exit_from_route_memory=True, straddle=None, both=False,
               centre_path_m=[], near_edges_m={}, edges_m=[])


def guarded():
    owner, guard = DrivableSteer(), RouteBridge()
    owner._ctx = dict(fresh=True, guide=True, here=36.5, ahead=-68.8)
    owner._route_bridge = guard
    return owner, guard


def step(owner, guard, yaw=0.0, x=0.0, info=None):
    return guard.step(None, None, copy.deepcopy(STALLED if info is None else info), (x, 0.0, yaw), owner)


def test_recorded_closed_recentre_aligns_to_observed_left_floor_with_zero_linear_confidence():
    owner, guard = guarded()
    error, confidence, info = step(owner, guard)
    assert error == -PIVOT_ERROR
    assert confidence == owner._pivot_confidence
    assert info['strategy'] == 'drivable_recentre_pivot_left'
    assert info.get('reason') is None


def test_the_full_steer_does_not_let_the_future_right_exit_cancel_observed_left_alignment(monkeypatch):
    import control.sensing.perception.drivable.drivable_steer as steer_module
    from test_drivable_steer import G, HALF, XO, _lane

    monkeypatch.setattr(steer_module, 'way_target', lambda *a, **k: copy.deepcopy(STALLED))
    owner = DrivableSteer()
    owner._side = 'right'
    owner._route_exit = ('right', (0.1375, -0.0585), (0.0, 0.0, 0.0))
    for stamp, yaw in enumerate((0.0, 0.1, 0.2), 1):
        pose = (0.0, 0.0, yaw)
        error, confidence, info = owner.update(_lane(HALF, -HALF), stamp, G, XO, HALF,
            pose, pose, guide_deg=-68.8, guide_here_deg=36.5, observed_only=True)
        assert (error, confidence, info['strategy']) == (
            -PIVOT_ERROR, owner._pivot_confidence, 'drivable_recentre_pivot_left')


def test_repeated_future_right_guides_do_not_renew_the_same_alignment_yaw_budget():
    owner, guard = guarded()
    for yaw in (0.0, 0.2, 0.4):
        assert step(owner, guard, yaw)[0] == -PIVOT_ERROR
    for yaw in (0.7, 0.7, 0.7, 0.7):
        error, confidence, info = step(owner, guard, yaw)
        assert error is None and confidence is None
        assert info['reason'] == 'recentre_alignment_spent'


def test_a_brief_open_frame_without_translation_cannot_rearm_a_spent_alignment():
    owner, guard = guarded()
    step(owner, guard)
    step(owner, guard, 0.7)
    opened = dict(strategy='drivable_centre', ahead_m=0.25, target_m=(0.25, 0.0))
    assert guard.step(0.1, 0.6, opened, (0.0, 0.0, 0.7), owner)[:2] == (0.1, 0.6)
    assert step(owner, guard, 0.7)[2]['reason'] == 'recentre_alignment_spent'
    guard.step(0.1, 0.6, opened, (BRIDGE_MAX_M + 0.01, 0.0, 0.7), owner)
    assert step(owner, guard, 0.7, BRIDGE_MAX_M + 0.01)[0] == -PIVOT_ERROR


def test_alignment_counts_turns_across_the_yaw_wrap_and_does_not_refund_oscillation():
    owner, guard = guarded()
    assert step(owner, guard, math.pi - 0.05)[0] == -PIVOT_ERROR
    assert step(owner, guard, -math.pi + 0.05)[0] == -PIVOT_ERROR
    assert step(owner, guard, math.pi - 0.05)[0] == -PIVOT_ERROR
    assert step(owner, guard, -math.pi + 0.2)[0] == -PIVOT_ERROR
    assert step(owner, guard, math.pi - 0.05)[2]['reason'] == 'recentre_alignment_spent'


@pytest.mark.parametrize('change', [dict(seen_exit=None), dict(near_centre_m=None),
    dict(target_m=None), dict(front_blocked_m=0.114), dict(exit_reach_m={}),
    dict(near_centre_m=(0.159, -0.101)), dict(pivot_limit=True)])
def test_ambiguous_or_blocked_observations_cannot_start_alignment(change):
    owner, guard = guarded()
    assert step(owner, guard, info=dict(STALLED, **change))[0] is None


@pytest.mark.parametrize('ctx', [dict(fresh=False, guide=True, here=36.5),
    dict(fresh=True, guide=False, here=36.5), dict(fresh=True, guide=True, here=-36.5)])
def test_missing_stale_or_opposing_current_route_context_cannot_start_alignment(ctx):
    owner, guard = guarded()
    owner._ctx = ctx
    assert step(owner, guard)[0] is None


@pytest.mark.parametrize('pose', [None, (0.0, 0.0, math.nan)])
def test_alignment_requires_valid_current_odometry(pose):
    owner, guard = guarded()
    assert guard.step(None, None, copy.deepcopy(STALLED), pose, owner)[0] is None


def test_steer_reset_cannot_rearm_a_spent_alignment_without_observed_progress():
    owner, guard = guarded()
    step(owner, guard)
    step(owner, guard, 0.7)
    owner.reset()
    assert step(owner, guard, 0.7)[2]['reason'] == 'recentre_alignment_spent'
