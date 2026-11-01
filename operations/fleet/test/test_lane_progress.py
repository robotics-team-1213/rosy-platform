"""D-941 2: lane-progress gap, leader choice across the loop seam, follower speed."""
import pytest

from fleet.lane_progress import MIN_GAP_M, TARGET_GAP_M, Loop, follower_speed, leaders
from fleet.site_map import SiteMap


def square():
    corners = {"A": (0, 0), "B": (1, 0), "C": (1, 1), "D": (0, 1)}
    order = ["A", "B", "C", "D", "A"]
    return SiteMap.model_validate({
        "schema": "rosy.site_map/1", "map_id": "loop_test",
        "places": [{"id": k, "name": k, "x": x, "y": y} for k, (x, y) in corners.items()],
        "edges": [{"id": f"{a}{b}", "from": a, "to": b, "polyline": [corners[a], corners[b]],
                   "direction": "one_way", "width_m": 0.1, "speed_cap_mps": 0.15}
                  for a, b in zip(order, order[1:])]})


def test_progress_and_gap_wrap_around_the_loop():
    loop = Loop(square(), ["AB", "BC", "CD", "DA"])
    assert loop.perimeter == pytest.approx(4.0)
    s, off = loop.project(0.5, 0.02)
    assert s == pytest.approx(0.5) and off == pytest.approx(0.02)
    assert loop.project(0.0, 0.5)[0] == pytest.approx(3.5)
    assert loop.gap(0.2, 3.8) == pytest.approx(0.4)          # leader just past the seam


def test_each_robot_follows_the_one_directly_ahead():
    loop = Loop(square(), ["AB", "BC", "CD", "DA"])
    got = leaders(loop, {"a": 0.2, "b": 3.8, "c": 2.0})
    assert got["b"] == ("a", pytest.approx(0.4))
    assert got["a"] == ("c", pytest.approx(1.8)) and got["c"][0] == "b"
    assert leaders(loop, {"solo": 1.0}) == {}


def test_follower_speed_adds_the_leader_speed_and_respects_cap_and_min_gap():
    assert follower_speed(0.1, TARGET_GAP_M, 0.15) == pytest.approx(0.1)   # at the target: match
    assert follower_speed(0.1, TARGET_GAP_M + 1.0, 0.15) == 0.15            # far behind: lane cap
    assert follower_speed(0.1, TARGET_GAP_M - 0.3, 0.15) < 0.1              # too close: slower
    assert follower_speed(0.0, MIN_GAP_M - 0.01, 0.15) == 0.0               # inside stop gap
    assert follower_speed(0.0, 0.3, 0.15) == 0.0                            # never reverses


def test_a_broken_loop_is_refused():
    with pytest.raises(ValueError, match="breaks"):
        Loop(square(), ["AB", "CD"])
