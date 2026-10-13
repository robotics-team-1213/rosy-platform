"""D-592 drivable steering math: error sign, angular sign and clamp, stop conditions,
rightmost branch, LiDAR guard. No robot, no model: synthetic label images."""
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import drivable_steer as ds  # noqa: E402
from control.sensing.perception.learned.manifest import ClassSpec  # noqa: E402

CLASSES = (ClassSpec(0, "background", "background"), ClassSpec(1, "lane_left", "lane_marking"),
           ClassSpec(2, "lane_right", "lane_marking"), ClassSpec(3, "crosswalk", "ignore"),
           ClassSpec(4, "speed_bump", "ignore"), ClassSpec(5, "drivable", "drivable"))
LIM = ds.Limits()


def road(left, right, h=240, w=320):
    """Drivable between columns [left, right), lane_left / lane_right lines 6 px wide beside it."""
    lab = np.zeros((h, w), np.int64)
    lab[:, left:right] = 5
    lab[:, max(left - 6, 0):left] = 1
    lab[:, right:min(right + 6, w)] = 2
    return lab


def test_centred_road_has_near_zero_error_and_no_turn():
    target, fraction = ds.near_target(road(100, 220), CLASSES)
    error = ds.lateral_error(ds.pick_branch(target)[0])
    assert fraction > 0.3 and abs(error) < 0.03
    v, w, reason = ds.command(fraction, error, 0.1, True, 1.0, LIM)
    assert reason is None and v == LIM.linear and abs(w) < 0.02


def test_road_right_of_centre_gives_positive_error_and_right_turn():
    target, fraction = ds.near_target(road(200, 310), CLASSES)
    error = ds.lateral_error(ds.pick_branch(target)[0])
    assert error > 0.3
    _, w, reason = ds.command(fraction, error, 0.1, True, 1.0, LIM)
    assert reason is None and w < 0                     # negative angular = clockwise = right


def test_road_left_of_centre_turns_left():
    target, fraction = ds.near_target(road(10, 120), CLASSES)
    error = ds.lateral_error(ds.pick_branch(target)[0])
    assert error < -0.3
    assert ds.command(fraction, error, 0.1, True, 1.0, LIM)[1] > 0


def test_inner_line_half_counts_as_drivable():
    lab = road(100, 220)
    target, _ = ds.near_target(lab, CLASSES)
    row = target[-1]
    assert row[97:100].all() and not row[94]            # inner half of lane_left (cols 94..99)
    assert row[220:223].all() and not row[225]          # inner half of lane_right (cols 220..225)


def test_angular_is_clamped():
    for e in (1.0, -1.0):
        w = ds.command(0.5, e, 0.1, True, 1.0, ds.Limits(gain=5.0))[1]
        assert math.isclose(abs(w), 0.4)


def test_stop_conditions_send_zero():
    cases = {"time_cap": (0.5, 0.0, 0.1, True, 60.0), "stale": (0.5, 0.0, 0.51, True, 1.0),
             "guard": (0.5, 0.0, 0.1, False, 1.0), "drivable_low": (0.05, 0.0, 0.1, True, 1.0)}
    for reason, args in cases.items():
        assert ds.command(*args, LIM) == (0.0, 0.0, reason)
    assert ds.command(0.5, None, 0.1, True, 1.0, LIM) == (0.0, 0.0, "drivable_low")
    assert ds.command(0.5, 0.0, None, True, 1.0, LIM) == (0.0, 0.0, "stale")


def test_no_drivable_gives_no_error():
    target, fraction = ds.near_target(np.zeros((240, 320), np.int64), CLASSES)
    assert fraction == 0.0 and ds.lateral_error(target) is None


def test_split_region_follows_the_rightmost_branch():
    target = np.zeros((96, 320), bool)
    target[:, 20:80] = True
    target[:, 240:300] = True
    branch, n = ds.pick_branch(target)
    assert n == 2 and ds.lateral_error(branch) > 0.5
    assert ds.lateral_error(target) < 0.05               # the centroid of both would go straight


def scan(returns_by_deg, n=360, rest=1.5):
    ranges = [rest] * n
    for deg, r in returns_by_deg.items():
        ranges[(deg + 180) % n] = r
    return {"ranges": ranges, "angle_min": -math.pi, "angle_increment": 2 * math.pi / n,
            "range_min": 0.05, "range_max": 12.0}


def test_guard_passes_clear_and_refuses_close_obstacle():
    ok, detail = ds.guard_check(scan({}), 0.03, 180.0)
    assert ok, detail
    ok, detail = ds.guard_check(scan({d: 0.10 for d in range(-10, 11)}), 0.03, 0.0)
    assert not ok and detail["gap_m"] is not None and detail["gap_m"] < detail["need_m"]
