"""A straight expected path is republished across a missing drivable frame.

The hypothesis commits only a near-heading centre corridor, steers the near tangent,
and drops on a turn, a straddle, a budget, or a jumped pose. Poses are (x, y, yaw)
in odom; yaw 0 faces +x and left is +y.
"""
import math

import pytest

HALF = 0.0925


def _new():
    from control.sensing.perception.learned.expected_path import ExpectedPath
    return ExpectedPath(HALF)


def _centre(ahead=0.40, strategy="drivable_centre", straddle=None, reason=None):
    return {"ahead_m": ahead, "near_centre_m": (0.20, 0.0),
            "centre_path_m": ((.1, 0.), (.1 + ahead / 2, 0.), (.1 + ahead, 0.)), "strategy": strategy,
            "straddle": straddle, "reason": reason}


def _commit(yaw=0.0, ahead=0.40):
    path = _new()
    view = None
    for index in range(3):
        view = path.update((0.0, 0.0, yaw), index * 0.1, _centre(ahead))
    assert view["committed"] and view["state"] == "live"
    return path


def test_a_gap_breaks_an_uncommitted_streak():
    path = _new()
    path.update((0.0, 0.0, 0.0), 0.0, _centre())
    path.update((0.0, 0.0, 0.0), 0.1, _centre())
    assert path.hold((0.0, 0.0, 0.0), 0.2)["error"] is None
    path.update((0.0, 0.0, 0.0), 0.3, _centre())
    assert not path.update((0.0, 0.0, 0.0), 0.4, _centre())["committed"]


def test_two_centre_frames_do_not_commit():
    path = _new()
    path.update((0.0, 0.0, 0.0), 0.0, _centre())
    view = path.update((0.0, 0.0, 0.0), 0.1, _centre())
    assert not view["committed"]
    assert path.hold((0.0, 0.0, 0.0), 0.2)["error"] is None


def test_three_matching_centre_frames_commit():
    view = None
    path = _new()
    for index in range(3):
        view = path.update((0.0, 0.0, 0.0), index * 0.1, _centre())
    assert view["committed"] and view["state"] == "live"


def test_twelve_degrees_still_joins_the_commit_streak():
    path = _new()
    path.update((0.0, 0.0, 0.0), 0.0, _centre())
    path.update((0.0, 0.0, math.radians(12)), 0.1, _centre())
    assert path.update((0.0, 0.0, math.radians(12)), 0.2, _centre())["committed"]


def test_a_heading_past_twelve_degrees_breaks_the_streak():
    # 20° is 20° from the streak's first heading and only 10° from the previous frame.
    path = _new()
    path.update((0.0, 0.0, 0.0), 0.0, _centre())
    path.update((0.0, 0.0, math.radians(10)), 0.1, _centre())
    assert not path.update((0.0, 0.0, math.radians(20)), 0.2, _centre())["committed"]
    assert not path.update((0.0, 0.0, math.radians(20)), 0.3, _centre())["committed"]
    assert path.update((0.0, 0.0, math.radians(20)), 0.4, _centre())["committed"]


@pytest.mark.parametrize("info", [
    _centre(strategy="drivable_pivot_right"),
    _centre(straddle="left"),
    _centre(strategy="drivable_turn_right"),
    _centre(strategy="drivable_off_line_right"),
    _centre(strategy="drivable_crosswalk_straight"),
    _centre(strategy="none", reason="drivable_closed"),
    _centre(reason="way_beyond_line"),
])
def test_a_forbidden_frame_clears_the_hypothesis(info):
    path = _commit()
    cleared = path.update((0.0, 0.0, 0.0), 1.0, info)
    assert not cleared["committed"]
    held = path.hold((0.0, 0.0, 0.0), 1.1)
    assert held["error"] is None and held["state"] == "dropped"


def test_a_missing_frame_holds_the_near_tangent():
    path = _commit()
    held = path.hold((0.05, 0.0, 0.0), 1.0)
    assert held["state"] == "held" and held["error"] is not None
    assert abs(held["target_m"][1]) < 0.01
    start, end = held["path_m"][0], held["path_m"][-1]
    assert abs(start[1]) < 0.01 and abs(end[1]) < 0.01 and end[0] > start[0]


def test_far_geometry_does_not_replace_the_near_pursuit_target():
    path = _commit()
    before = path.hold((0.05, 0.0, 0.0), 1.0)
    path._path = (*path._path[:-1], (path._path[-1][0], path._path[-1][1] + .20))
    after = path.hold((0.05, 0.0, 0.0), 1.1)
    assert after["error"] == pytest.approx(before["error"])
    assert abs(before["error"]) < 0.01


def test_travel_past_the_segment_or_a_quarter_metre_or_two_and_a_half_seconds_drops():
    short = _commit(ahead=0.15)
    short.hold((0.0, 0.0, 0.0), 1.0)
    assert short.hold((0.14, 0.0, 0.0), 1.1)["state"] == "held"
    short_drop = short.hold((0.15, 0.0, 0.0), 1.2)
    assert short_drop["error"] is None and short_drop["state"] == "dropped"

    capped = _commit(ahead=0.40)
    capped.hold((0.0, 0.0, 0.0), 1.0)
    assert capped.hold((0.24, 0.0, 0.0), 1.1)["state"] == "held"
    cap_drop = capped.hold((0.25, 0.0, 0.0), 1.2)
    assert cap_drop["error"] is None and cap_drop["state"] == "dropped"

    timed = _commit()
    timed.hold((0.0, 0.0, 0.0), 1.0)
    assert timed.hold((0.05, 0.0, 0.0), 2.69)["error"] is not None
    time_drop = timed.hold((0.05, 0.0, 0.0), 2.71)
    assert time_drop["error"] is None and time_drop["state"] == "dropped"


def test_confidence_steps_from_nine_tenths_to_the_half_speed_value():
    path = _commit()
    path.hold((0.0, 0.0, 0.0), 1.0)
    near = path.hold((0.05, 0.0, 0.0), 1.2)
    far = path.hold((0.15, 0.0, 0.0), 1.4)
    assert near["confidence"] == pytest.approx(0.90) and near["s_m"] == pytest.approx(0.05)
    assert far["confidence"] == pytest.approx(0.68) and far["s_m"] == pytest.approx(0.15)
    assert 0.45 < (0.68 - 0.35) / 0.65 < 0.55


def test_one_new_heading_holds_and_three_replace_it():
    path = _commit()
    before = path.hold((0.0, 0.0, 0.0), 1.0)
    bad = path.update((0.0, 0.0, math.radians(20)), 1.1, _centre())
    assert bad["state"] == "held"
    assert path.hold((0.0, 0.0, 0.0), 1.2)["error"] == pytest.approx(before["error"])
    states = [path.update((0.0, 0.0, math.radians(20)), 2.0 + index * 0.1, _centre())["state"]
              for index in range(3)]
    assert states == ["held", "held", "live"]
    followed = path.hold((0.0, 0.0, math.radians(20)), 2.4)
    assert followed["state"] == "held" and abs(followed["target_m"][1]) < 0.01


def test_a_rewound_stamp_or_a_jumped_pose_drops_the_hypothesis():
    rewound = _commit()
    rewound.hold((0.0, 0.0, 0.0), 5.0)
    back = rewound.hold((0.01, 0.0, 0.0), 4.0)
    assert back["error"] is None and back["state"] == "dropped"

    jumped = _commit()
    view = jumped.update((0.26, 0.0, 0.0), 1.0, _centre())
    assert view["state"] == "dropped" and not view["committed"]
    assert not jumped.update((0.26, 0.0, 0.0), 1.1, _centre())["committed"]
    assert not jumped.update((0.26, 0.0, 0.0), 1.2, _centre())["committed"]
    assert jumped.update((0.26, 0.0, 0.0), 1.3, _centre())["committed"]


def _shape_info(curvature=0., lateral=0.):
    points = []
    for index in range(11):
        x = .10 + index * .03
        y = lateral if curvature == 0. else (1. - math.sqrt(1. - (curvature * x) ** 2)) / curvature
        points.append((x, y))
    return dict(_centre(), near_centre_m=(.10, points[0][1]), centre_path_m=points)


def _commit_shape(curvature=0., lateral=0.):
    path = _new()
    for stamp in (0., .1, .2):
        path.update((0., 0., 0.), stamp, _shape_info(curvature, lateral))
    return path


def test_observed_parallel_offset_does_not_rotate_the_lane_tangent():
    centred = _commit_shape()
    offset = _commit_shape(lateral=.03)
    assert offset._heading == pytest.approx(centred._heading, abs=1e-9)
    target = offset.hold((0., 0., 0.), .3)['target_m']
    assert target[1] == pytest.approx(.03)


@pytest.mark.parametrize('curvature', [-1., 1.])
def test_observed_curve_is_preserved_and_uses_pursuit_error(curvature):
    from control.sensing.perception.drivable.drivable_steer import pursuit_error
    held = _commit_shape(curvature).hold((0., 0., 0.), .3)
    tx, ty = held['target_m']
    assert ty * curvature > 0.
    assert tx * tx + (ty - 1. / curvature) ** 2 == pytest.approx(1., abs=.002)
    assert held['error'] == pytest.approx(pursuit_error(tx, ty, held['confidence']))
    assert len(held['path_m']) > 2


def test_cached_observation_cannot_restart_the_total_loss_clock():
    path = _commit_shape()
    view = path.update((0., 0., 0.), 2.7, _shape_info(), observation_stamp=.2,
                       current_pose=(.01, 0., 0.))
    assert view['error'] is None and not view['committed']


def test_returning_to_the_loss_pose_does_not_refund_travel():
    path = _commit_shape()
    view = None
    for index, x in enumerate((.05, 0., .05, 0., .05)):
        view = path.hold((x, 0., 0.), .3 + index * .1)
    assert view['error'] is None and not view['committed']


def test_current_pose_is_distinct_from_cached_source_pose():
    path = _commit_shape()
    held = path.update((0., 0., 0.), .3, _shape_info(), observation_stamp=.2,
                       current_pose=(0., .02, 0.))
    assert held['target_m'][1] == pytest.approx(-.02)


@pytest.mark.parametrize('pose,stamp', [
    ((float('nan'), 0., 0.), .3), ((0., 0., float('inf')), .3),
    ((0., 0., 0.), float('nan')), ((0., 0., math.pi), .3),
])
def test_invalid_or_reset_odometry_discards_observed_geometry(pose, stamp):
    held = _commit_shape().hold(pose, stamp)
    assert held['error'] is None and not held['committed']


def test_shape_exhaustion_or_a_target_behind_the_robot_stops():
    path = _commit_shape()
    held = path.hold((.40, 0., 0.), .3)
    assert held['error'] is None


def test_near_point_without_observed_shape_cannot_commit():
    path = _new()
    info = _centre()
    info.pop('centre_path_m')
    for stamp in (0., .1, .2):
        path.update((0., 0., 0.), stamp, info)
    assert not path._committed


@pytest.mark.parametrize('reason', ['realign', 'creep_heading', 'repeat_failed'])
def test_fresh_refusal_cannot_be_overridden_by_observed_memory(reason):
    path = _commit_shape()
    denied = path.update((0., 0., 0.), .3, dict(_shape_info(), strategy='none', reason=reason))
    assert not denied['committed'] and denied['error'] is None
    assert path.hold((0., 0., 0.), .4)['error'] is None


def test_cached_frames_between_independent_frames_do_not_count_as_new_evidence():
    path = _new()
    info = _shape_info()
    path.update((0., 0., 0.), 0., info, observation_stamp=0.)
    path.update((0., 0., 0.), .05, info, observation_stamp=0.)
    assert not path.update((0., 0., 0.), .1, info, observation_stamp=.1)['committed']
    path.update((0., 0., 0.), .15, info, observation_stamp=.1)
    assert path.update((0., 0., 0.), .2, info, observation_stamp=.2)['committed']


@pytest.mark.parametrize('shape', [None, [(float('nan'), 0.), (.2, 0.)], [(.2, 0.), (.1, 0.)], [(.1, 0.), (.1, 0.)]])
def test_new_invalid_geometry_cannot_reactivate_old_memory(shape):
    path = _commit_shape()
    denied = path.update((0., 0., 0.), .3, dict(_shape_info(), centre_path_m=shape))
    assert not denied['committed'] and denied['error'] is None
    assert path.hold((0., 0., 0.), .4)['error'] is None


@pytest.mark.parametrize('strategy', ['drivable_creep', 'drivable_creep_map', 'drivable_map_bridge', 'drivable_reorient_left'])
def test_non_centre_strategy_cannot_reactivate_old_memory(strategy):
    path = _commit_shape()
    assert not path.update((0., 0., 0.), .3, dict(_shape_info(), strategy=strategy))['committed']
    assert path.hold((0., 0., 0.), .4)['error'] is None
