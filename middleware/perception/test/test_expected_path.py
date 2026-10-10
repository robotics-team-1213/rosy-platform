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
    return {"ahead_m": ahead, "near_centre_m": (0.20, 0.0), "strategy": strategy,
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
    start, end = held["path_m"]
    assert abs(start[1]) < 0.01 and abs(end[1]) < 0.01 and end[0] > start[0]


def test_shifting_the_end_sideways_does_not_change_held_error():
    path = _commit()
    before = path.hold((0.05, 0.0, 0.0), 1.0)
    path.end_m = (path.end_m[0], path.end_m[1] + 0.20)
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
    timed.hold((0.0, 0.0, 0.0), 10.0)
    assert timed.hold((0.05, 0.0, 0.0), 12.49)["error"] is not None
    time_drop = timed.hold((0.05, 0.0, 0.0), 12.51)
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
