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


def guarded(min_confidence=0.35):
    owner, guard = DrivableSteer(min_confidence=min_confidence), RouteBridge()
    owner._ctx = dict(fresh=True, guide=True, here=36.5, ahead=-68.8)
    owner._route_bridge = guard
    owner._test_stamp = 0.0
    return owner, guard


def step(owner, guard, yaw=0.0, x=0.0, info=None, error=None, confidence=None):
    owner._test_stamp += 0.125
    pose = (x, 0.0, yaw)
    return guard.step(error, confidence, copy.deepcopy(STALLED if info is None else info), pose, owner,
        source_pose=pose, current_stamp=owner._test_stamp, observation_stamp=owner._test_stamp)


def spend(owner, guard):
    for i in range(8):
        step(owner, guard, i * 0.1)


@pytest.mark.parametrize('min_confidence', [0.2, 0.35, 0.55])
def test_recorded_closed_recentre_aligns_to_observed_left_floor_with_zero_linear_confidence(min_confidence):
    owner, guard = guarded(min_confidence)
    error, confidence, info = step(owner, guard)
    assert error == -PIVOT_ERROR
    assert confidence == owner._pivot_confidence
    assert info['strategy'] == 'drivable_recentre_pivot_left'
    assert info.get('reason') is None


def test_the_full_steer_does_not_let_the_future_right_exit_cancel_observed_left_alignment(monkeypatch):
    import control.sensing.perception.drivable.drivable_steer as steer_module
    from test_drivable_steer import G, HALF, XO, _lane

    raw = {k: copy.deepcopy(v) for k,v in STALLED.items()
           if k not in ('strategy', 'reason', 'recentre_first', 'guide_deg', 'exit_from_route_memory')}
    raw.update(exit='left', exit_point_m={'left': (0.183, 0.089)})
    monkeypatch.setattr(steer_module, 'way_target', lambda *a, **k: copy.deepcopy(raw))
    owner = DrivableSteer()
    owner._side = 'right'
    owner._route_exit = ('right', (0.1375, -0.0585), (0.0, 0.0, 0.0))
    for stamp, yaw in enumerate((0.0, 0.1, 0.2), 1):
        pose = (0.0, 0.0, yaw)
        error, confidence, info = owner.update(_lane(HALF, -HALF), stamp / 8, G, XO, HALF,
            pose, pose, guide_deg=-68.8, guide_here_deg=36.5, observed_only=True, current_stamp=stamp / 8)
        assert (error, confidence, info['strategy']) == (
            -PIVOT_ERROR, owner._pivot_confidence, 'drivable_recentre_pivot_left')


def test_repeated_future_right_guides_do_not_renew_the_same_alignment_yaw_budget():
    owner, guard = guarded()
    for yaw in (0.0, 0.1, 0.2, 0.3, 0.4, 0.5):
        assert step(owner, guard, yaw)[0] == -PIVOT_ERROR
    for yaw in (0.6, 0.7, 0.7, 0.7):
        error, confidence, info = step(owner, guard, yaw)
        assert error is None and confidence is None
        assert info['reason'] == 'recentre_alignment_spent'


def test_a_brief_open_frame_without_translation_cannot_rearm_a_spent_alignment():
    owner, guard = guarded()
    spend(owner, guard)
    opened = dict(strategy='drivable_centre', ahead_m=0.25, target_m=(0.25, 0.0),
                  centre_path_m=[(0.14, 0.0), (0.3, 0.0)])
    assert step(owner, guard, 0.7, info=opened, error=0.1, confidence=0.6)[:2] == (0.1, 0.6)
    assert step(owner, guard, 0.7)[2]['reason'] == 'recentre_alignment_spent'
    for i in range(1, 17):
        step(owner, guard, 0.7, i * 0.01, info=opened, error=0.1, confidence=0.6)
    assert step(owner, guard, 0.7, 0.16)[0] == -PIVOT_ERROR


def test_alignment_counts_turns_across_the_yaw_wrap_and_does_not_refund_oscillation():
    owner, guard = guarded()
    for yaw in (math.pi - 0.05, -math.pi + 0.05) * 3:
        assert step(owner, guard, yaw)[0] == -PIVOT_ERROR
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
    assert guard.step(None, None, copy.deepcopy(STALLED), pose, owner, source_pose=(0.0, 0.0, 0.0),
        current_stamp=0.125, observation_stamp=0.125)[0] is None


def test_steer_reset_cannot_rearm_a_spent_alignment_without_observed_progress():
    owner, guard = guarded()
    spend(owner, guard)
    owner.reset()
    assert step(owner, guard, 0.7)[2]['reason'] == 'recentre_alignment_spent'


def test_odometry_jump_is_not_progress_that_refills_the_alignment():
    owner, guard = guarded()
    spend(owner, guard)
    opened = dict(strategy='drivable_centre', ahead_m=0.25, target_m=(0.25, 0.0),
                  centre_path_m=[(0.14, 0.0), (0.3, 0.0)])
    step(owner, guard, 0.7, BRIDGE_MAX_M + 0.01, info=opened, error=0.1, confidence=0.6)
    assert step(owner, guard, 0.7, BRIDGE_MAX_M + 0.01)[0] is None


def test_source_frame_direction_is_expressed_at_the_current_pose_before_alignment():
    owner, guard = guarded()
    owner._ctx['here'] = -23.5
    error, confidence, info = guard.step(None, None, copy.deepcopy(STALLED), (0.0, 0.0, math.pi / 3), owner,
        source_pose=(0.0, 0.0, 0.0), current_stamp=1.5, observation_stamp=0.0)
    assert (error, confidence, info['strategy']) == (
        PIVOT_ERROR, owner._pivot_confidence, 'drivable_recentre_pivot_right')
    assert info['target_m'] is None and info['target_now_m'] is None


def test_an_unspent_alignment_cannot_resume_after_an_odometry_epoch_reset():
    owner, guard = guarded()
    step(owner, guard)
    owner.reset()
    assert step(owner, guard)[2]['reason'] == 'recentre_alignment_odometry'


def test_clock_rollback_cannot_recharge_a_spent_alignment():
    owner, guard = guarded()
    spend(owner, guard)
    owner._test_stamp = -1.0
    assert step(owner, guard, 0.7)[0] is None
    owner._test_stamp = 2.0
    assert step(owner, guard, 0.7, BRIDGE_MAX_M + 0.01)[0] is None


def test_an_alignment_pivot_cannot_commit_a_forward_expected_path():
    from control.sensing.perception.learned.expected_path import ExpectedPath

    owner, guard = guarded()
    path = ExpectedPath(0.0925)
    for i in range(5):
        error, confidence, info = step(owner, guard)
        view = path.update((0.0, 0.0, 0.0), i / 8, info)
        assert error is not None and confidence == owner._pivot_confidence
        assert info['target_m'] is None and info['target_now_m'] is None
        assert not view['committed'] and view['path_m'] is None


def test_an_observation_flip_holds_instead_of_reversing_the_alignment():
    owner, guard = guarded()
    step(owner, guard)
    owner._ctx['here'] = -36.5
    flipped = dict(STALLED, near_centre_m=(0.159, -0.101), target_m=(0.111, -0.104),
                   seen_exit='right', exit_reach_m={'right': 0.186},
                   exit_point_m={'right': (0.183, -0.089)})
    error, confidence, info = step(owner, guard, info=flipped)
    assert error is None and confidence is None
    assert info['reason'] == 'recentre_alignment_changed'


def test_a_stale_source_mask_cannot_start_alignment():
    owner, guard = guarded()
    pose = (0.0, 0.0, 0.0)
    assert guard.step(None, None, copy.deepcopy(STALLED), pose, owner, source_pose=pose,
        current_stamp=2.0, observation_stamp=0.0)[0] is None


def test_source_and_current_pose_cannot_jump_without_elapsed_time():
    owner, guard = guarded()
    assert guard.step(None, None, copy.deepcopy(STALLED), (0.02, 0.0, 0.0), owner,
        source_pose=(0.0, 0.0, 0.0), current_stamp=0.125, observation_stamp=0.125)[0] is None


# sim-4766cfbf88-4dc846, source camera 173.750, decision 173.875.
# A future right pivot was already latched while the observed local opening stayed left.
LATCHED = dict(STALLED, strategy='drivable_pivot_right', reason=None,
    target_m=(0.122, 0.117), near_centre_m=(0.163, 0.098),
    exit='right', exit_point_m={'left': (0.190, 0.094)},
    exit_reach_m={'left': 0.202}, guide_deg=-80.2)
LATCHED.pop('recentre_first')
LATCHED.pop('exit_from_route_memory')


def test_an_opposing_latched_pivot_uses_the_same_observed_alignment_budget():
    owner, guard = guarded()
    owner._ctx.update(here=25.3, ahead=-80.2)
    error, confidence, info = step(owner, guard, info=LATCHED, error=PIVOT_ERROR,
                                    confidence=owner._pivot_confidence)
    assert (error, confidence, info['strategy']) == (
        -PIVOT_ERROR, owner._pivot_confidence, 'drivable_recentre_pivot_left')
    for i in range(1, 8):
        step(owner, guard, i * 0.1, info=LATCHED, error=PIVOT_ERROR,
             confidence=owner._pivot_confidence)
    off_line = dict(LATCHED, strategy='drivable_off_line_left', straddle='left')
    assert step(owner, guard, 0.7, info=off_line, error=-PIVOT_ERROR,
                confidence=owner._pivot_confidence)[2]['strategy'] == 'drivable_off_line_left'
    # Losing the narrow near-centre trigger cannot restore the old right latch or refill the episode.
    narrowed = dict(LATCHED, near_centre_m=(0.163, 0.01))
    error, confidence, info = step(owner, guard, 0.7, info=narrowed, error=PIVOT_ERROR,
                                   confidence=owner._pivot_confidence)
    assert error is None and confidence is None
    assert info['reason'] == 'recentre_alignment_spent'


@pytest.mark.parametrize('change', [dict(front_blocked_m=0.114), dict(straddle='left'),
    dict(crosswalk_hold=True), dict(pivot_limit=True), dict(strategy='drivable_turn_right'),
    dict(strategy='drivable_pivot_left')])
def test_alignment_does_not_replace_protected_or_nonopposing_candidates(change):
    owner, guard = guarded()
    raw = dict(LATCHED, **change)
    assert step(owner, guard, info=raw, error=PIVOT_ERROR,
                confidence=owner._pivot_confidence)[2]['strategy'] == raw['strategy']


def test_recorded_local_left_floor_can_override_a_right_latch_in_the_full_steer(monkeypatch):
    import control.sensing.perception.drivable.drivable_steer as steer_module
    from test_drivable_steer import G, HALF, XO, _lane

    raw = {k: copy.deepcopy(v) for k, v in LATCHED.items()
           if k not in ('strategy', 'reason', 'guide_deg')}
    raw['exit'] = 'left'
    monkeypatch.setattr(steer_module, 'way_target', lambda *a, **k: copy.deepcopy(raw))
    owner = DrivableSteer()
    owner._pivot = owner._side = 'right'
    owner._pivot_yaw = 0.0
    for i in range(3):
        pose = (0.0, 0.0, i * 0.05)
        error, confidence, info = owner.update(_lane(HALF, -HALF), (i + 1) / 8,
            G, XO, HALF, pose, pose, guide_deg=-80.2, guide_here_deg=25.3,
            observed_only=True, current_stamp=(i + 1) / 8)
        assert (error, confidence, info['strategy']) == (
            -PIVOT_ERROR, owner._pivot_confidence, 'drivable_recentre_pivot_left')


def test_losing_the_observed_opening_does_not_restore_the_opposing_raw_pivot():
    owner, guard = guarded()
    step(owner, guard, info=LATCHED, error=PIVOT_ERROR, confidence=owner._pivot_confidence)
    missing = dict(LATCHED, seen_exit=None)
    error, confidence, info = step(owner, guard, info=missing, error=PIVOT_ERROR,
                                   confidence=owner._pivot_confidence)
    assert error is None and confidence is None
    assert info['reason'] == 'recentre_alignment_unobserved'


def test_continuing_alignment_uses_the_original_budget_when_the_near_offset_shrinks():
    owner, guard = guarded()
    owner._ctx.update(here=25.3, ahead=-80.2)
    step(owner, guard, info=LATCHED, error=PIVOT_ERROR, confidence=owner._pivot_confidence)
    limit = guard._alignment['limit']
    near = dict(LATCHED, near_centre_m=(0.180, 0.02))
    assert step(owner, guard, 0.1, info=near, error=PIVOT_ERROR,
                confidence=owner._pivot_confidence)[0] == -PIVOT_ERROR
    assert guard._alignment['limit'] == limit


# Connected centre geometry from source50.375 / decision50.500 of sim-00e9913f29-26f127.
CURVED = dict(strategy='drivable_turn_right', reason=None, straddle=None,
    ahead_m=0.202, target_m=(0.250, 0.001), target_now_m=(0.213, -0.100),
    seen_exit='right', exit_reach_m={'right': 0.290}, exit_point_m={'right': (0.221, -0.110)},
    centre_path_m=[(0.139118,0.000202),(0.143981,0.000211),(0.148844,-0.015655),
        (0.153707,-0.018822),(0.158570,-0.022342),(0.163433,-0.026216),
        (0.168295,-0.029531),(0.173158,-0.033791),(0.178021,-0.038558),
        (0.182884,-0.042347),(0.187747,-0.046941),(0.192610,-0.051081),
        (0.197472,-0.056405),(0.202335,-0.061947),(0.207198,-0.067156),
        (0.212061,-0.072583),(0.216924,-0.078747),(0.221787,-0.084488),
        (0.226649,-0.091732),(0.231512,-0.099006),(0.236375,-0.107034),
        (0.241238,-0.114457),(0.246101,-0.122774),(0.250964,-0.131153),
        (0.255826,-0.139869),(0.260689,-0.149197),(0.265552,-0.159526),
        (0.270415,-0.171455),(0.275278,-0.181671),(0.280141,-0.197114),
        (0.285003,-0.208417),(0.289866,-0.228514)])


def drive_curve(owner, guard, info, *, here=-12.7, ahead=-62.9):
    owner._ctx.update(here=here, ahead=ahead)
    for i in range(1, 17):
        assert step(owner, guard, 0.7, i * 0.01, info=info, error=0.1, confidence=0.6)[:2] == (0.1, 0.6)
    owner._ctx.update(here=36.5, ahead=-68.8)


def test_observed_curved_progress_ends_the_old_episode_before_a_new_corner():
    owner, guard = guarded()
    spend(owner, guard)
    drive_curve(owner, guard, CURVED)
    assert guard._alignment is None
    assert step(owner, guard, 0.7, 0.16)[0] == -PIVOT_ERROR


@pytest.mark.parametrize('change', [dict(exit_from_route_memory=True), dict(exit_from_guide=True),
    dict(exit_from_memory=True), dict(seen_exit=None), dict(target_now_m=(0.21, 0.15)), dict(target_now_m=(0.14, 0.0)),
    dict(exit_point_m={'right': (0.22, 0.15)}), dict(centre_path_m=[(0.14, 0), (0.30, -0.20)]),
    dict(centre_path_m=[(0.14, 0), (0.13, 0), (0.30, -0.20)]),
    dict(centre_path_m=[(0.14, 0), (math.nan, 0), (0.30, -0.20)])])
def test_unmeasured_or_disconnected_turns_do_not_end_the_alignment_episode(change):
    owner, guard = guarded()
    spend(owner, guard)
    drive_curve(owner, guard, dict(CURVED, **change))
    assert step(owner, guard, 0.7, 0.16)[2]['reason'] == 'recentre_alignment_spent'


def test_an_observed_curve_cannot_repair_an_uncertain_odometry_episode():
    owner, guard = guarded()
    spend(owner, guard)
    owner.reset()
    drive_curve(owner, guard, CURVED)
    assert guard._alignment is not None and guard._alignment['uncertain']
    assert step(owner, guard, 0.7, 0.16)[0] is None


def test_a_curve_captured_before_leaving_the_origin_cannot_end_the_episode():
    owner, guard = guarded()
    spend(owner, guard)
    owner._ctx.update(here=-12.7, ahead=-62.9)
    for i in range(1, 17):
        owner._test_stamp += 0.125
        x, source_x = i * 0.01, max(0.0, i * 0.01 - 0.03)
        info = dict(CURVED, target_now_m=(0.213 + source_x - x, -0.100))
        guard.step(0.1, 0.6, info, (x, 0.0, 0.7), owner, source_pose=(source_x, 0.0, 0.7),
            current_stamp=owner._test_stamp, observation_stamp=owner._test_stamp - 0.5)
    assert guard._alignment is not None and not guard._alignment['uncertain']


def test_a_connected_tight_bend_is_measured_along_the_path_instead_of_the_forward_axis():
    # sim-68725ef0f4-ea9db8 decision64.875: 0.308m of path, but only 0.202m of forward x.
    tight = dict(CURVED, strategy='drivable_turn_left', seen_exit='left',
        target_now_m=(0.183, 0.085), exit_point_m={'left': (0.190, 0.094)},
        exit_reach_m={'left': 0.202}, centre_path_m=[
            (0.139118,0.023854),(0.141141,0.024605),(0.143164,0.026972),(0.145187,0.028914),
            (0.147210,0.031462),(0.149233,0.034073),(0.151255,0.036439),(0.153278,0.038806),
            (0.155301,0.041442),(0.157324,0.044333),(0.159347,0.048040),(0.161370,0.051875),
            (0.163392,0.056185),(0.165415,0.059730),(0.167438,0.063614),(0.169461,0.066492),
            (0.171484,0.069873),(0.173507,0.073779),(0.175529,0.077968),(0.177552,0.083528),
            (0.179575,0.089905),(0.181598,0.096323),(0.183621,0.102244),(0.185644,0.107810),
            (0.187667,0.116845),(0.189689,0.124678),(0.191712,0.131490),(0.193735,0.141343),
            (0.195758,0.148732),(0.197781,0.155587),(0.199804,0.165471),(0.201826,0.174916)])
    owner, guard = guarded()
    spend(owner, guard)
    drive_curve(owner, guard, tight, here=14.4, ahead=67.5)
    assert guard._alignment is None
    assert step(owner, guard, 0.7, 0.16)[0] == -PIVOT_ERROR


def test_pixel_zigzags_cannot_inflate_a_short_observed_path_into_episode_completion():
    owner, guard = guarded()
    spend(owner, guard)
    noisy = dict(CURVED, target_now_m=(0.195, -0.010), exit_point_m={'right': (0.190, -0.010)},
        exit_reach_m={'right': 0.210},
        centre_path_m=[(0.139 + i * 0.002, -0.020 if i % 2 else 0.0) for i in range(32)])
    drive_curve(owner, guard, noisy)
    assert step(owner, guard, 0.7, 0.16)[2]['reason'] == 'recentre_alignment_spent'
