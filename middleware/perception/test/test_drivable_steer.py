"""D-597 amendment 2: keep steers to the centre of the drivable way; closed ahead, it turns in
place toward the side the way leaves the view."""
import math
from types import SimpleNamespace

import numpy as np

from control.sensing.perception.learned.drivable_steer import (
    PIVOT_CONFIDENCE, PIVOT_ERROR, DrivableSteer, way_target)

G = SimpleNamespace(height_m=0.0575, pitch_rad=0.195, focal_px=281.6, principal_x=160.0, principal_y=120.0)
XO, HALF = 0.033, 0.0925


def _lane(y_left, y_right, x_max=1.0, shape=(240, 320)):
    """A way of floor y_right..y_left (base_link, left +) out to x_max, drawn row by row."""
    way = np.zeros(shape, bool)
    for row in range(112, shape[0]):
        ray = G.pitch_rad + np.arctan((row - G.principal_y) / G.focal_px)
        if G.height_m / np.tan(ray) + XO > x_max:
            continue
        px_per_m = (G.focal_px * np.sin(G.pitch_rad) + (row - G.principal_y) * np.cos(G.pitch_rad)) / G.height_m
        a, b = G.principal_x - y_left * px_per_m, G.principal_x - y_right * px_per_m
        way[row, max(0, int(round(a))):min(shape[1], int(round(b)) + 1)] = True
    return way


def test_centred_lane_steers_straight():
    t = way_target(_lane(HALF, -HALF), G, XO, HALF)
    assert abs(t["target_m"][1]) < 0.01 and t["both"] and t["ahead_m"] > 0.3


def test_one_unseen_edge_offsets_from_the_seen_edge():
    t = way_target(_lane(0.4, 0.02), G, XO, HALF)
    assert t["target_m"][1] > 0.02 and not t["both"]


def test_closed_ahead_pivots_toward_the_open_side_then_releases():
    steer = DrivableSteer()
    error, confidence, debug = steer.update(_lane(0.5, -HALF, x_max=0.2) | _lane(0.5, 0.04, x_max=0.33), 1, G, XO, HALF)
    assert debug["strategy"] == "drivable_turn_left" and error < 0          # closed at 0.2 m: arc left
    error, confidence, debug = steer.update(_lane(0.5, -HALF, x_max=0.12) | _lane(0.5, 0.04, x_max=0.33), 3, G, XO, HALF)
    assert (error, confidence, debug["strategy"]) == (-PIVOT_ERROR, PIVOT_CONFIDENCE, "drivable_pivot_left")
    error, confidence, debug = steer.update(_lane(HALF, -HALF), 2, G, XO, HALF)
    assert debug["strategy"] == "drivable_centre" and abs(error) < 0.2


def test_wall_corner_border_near_the_robot_loses_to_the_far_open_side():
    # wall ahead at 0.33 m; on the right a wall closes the floor beyond 0.15 m, on the left it runs on
    way = _lane(0.5, -0.5, x_max=0.15) | _lane(0.5, -0.03, x_max=0.33)
    assert way_target(way, G, XO, HALF)["exit"] == "left"


def test_odometry_moves_the_target_into_the_current_pose():
    steer = DrivableSteer()
    way = _lane(HALF, -HALF)
    straight, _, _ = steer.update(way, 1, G, XO, HALF, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    steer.reset()
    turned, _, _ = steer.update(way, 1, G, XO, HALF, (0.0, 0.0, 0.0), (0.0, 0.0, 0.3))
    assert turned > straight + 0.05      # turned left since the frame: the same point now lies right


def test_a_lidar_wall_beyond_the_model_view_closes_the_way():
    way = _lane(0.5, -HALF)                 # open straight ahead in the camera, wide to the left
    error, confidence, debug = DrivableSteer().update(way, 1, G, XO, HALF, wall_ahead_m=0.18)
    assert debug["ahead_m"] < 0.14 and debug["strategy"] == "drivable_pivot_left", debug


def test_a_closed_corner_turns_toward_the_opening_seen_on_the_way_in():
    steer = DrivableSteer()
    steer.update(_lane(0.5, -HALF, x_max=0.33), 1, G, XO, HALF, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    error, _, debug = steer.update(_lane(0.06, -0.06, x_max=0.13), 2, G, XO, HALF, (0.1, 0.0, 0.0), (0.1, 0.0, 0.0))
    assert debug["strategy"] == "drivable_pivot_left" and debug.get("exit_from_memory"), debug


def test_a_wall_beside_the_robot_is_no_exit_and_open_sides_keep_right():
    way = _lane(0.5, -0.5, x_max=0.15) | _lane(0.5, -0.03, x_max=0.33)
    blocked = DrivableSteer().update(way, 1, G, XO, HALF, side_clear_m={"left": 0.1, "right": None})[2]
    assert blocked["exit"] != "left", blocked
    both = _lane(0.5, -0.5, x_max=0.33)
    assert way_target(both, G, XO, HALF)["seen_exit"] in ("right", None)


def test_a_bend_inner_edge_does_not_block_the_arc_but_a_line_across_does():
    from control.sensing.perception.learned.drivable_steer import _crosses
    # left bend: inner edge points on a circle of radius 0.3 - 0.08 around (0, 0.3); the arc to a
    # target on the lane centre circle (radius 0.3) keeps 0.08 m from it
    inner = [(0.22 * math.sin(a), 0.3 - 0.22 * math.cos(a)) for a in np.linspace(0.0, 1.2, 30)]
    target = (0.3 * math.sin(0.8), 0.3 - 0.3 * math.cos(0.8))
    assert _crosses(inner, *target) is None
    across = [(0.15, y) for y in np.linspace(-0.1, 0.1, 20)]
    assert _crosses(across, 0.25, 0.0) is not None


def test_at_a_crosswalk_a_closed_way_goes_straight_not_around():
    steer = DrivableSteer()
    steer.crosswalk((0.0, 0.0, 0.0))
    error, confidence, debug = steer.update(_lane(0.5, -HALF, x_max=0.12) | _lane(0.5, 0.04, x_max=0.33), 1, G, XO, HALF,
                                            (0.05, 0.0, 0.0), (0.05, 0.0, 0.0))
    assert (error, debug["strategy"]) == (0.0, "drivable_crosswalk_straight"), debug


def test_an_in_place_turn_stops_after_about_a_hundred_degrees():
    steer = DrivableSteer()
    closed = _lane(0.5, -HALF, x_max=0.12) | _lane(0.5, 0.04, x_max=0.33)
    assert steer.update(closed, 1, G, XO, HALF, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))[2]["strategy"] == "drivable_pivot_left"
    after = steer.update(closed, 2, G, XO, HALF, (0.0, 0.0, 1.9), (0.0, 0.0, 1.9))[2]
    assert after.get("pivot_limit") and not after["strategy"].startswith("drivable_pivot")


def test_a_way_beyond_a_line_with_side_walls_known_holds_without_error():
    beyond = np.zeros((240, 320), bool)
    beyond[115:160, 100:220] = True                      # floor only beyond a gap
    error, confidence, debug = DrivableSteer().update(beyond, 1, G, XO, HALF, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0),
                                                      wall_ahead_m=None, side_clear_m={"left": None, "right": None})
    assert error is None and debug["reason"] == "way_beyond_line"


def test_pursuit_error_realises_the_arc_under_cores_law():
    from control.sensing.perception.learned.drivable_steer import (
        CORE_CRUISE_MPS, CORE_CURVE_SLOWDOWN, CORE_MIN_CONFIDENCE, CORE_STEERING_GAIN, pursuit_error)
    x, y, conf = 0.25, 0.05, 0.9
    error = pursuit_error(x, y, conf)
    w = -CORE_STEERING_GAIN * error
    v = CORE_CRUISE_MPS * (conf - CORE_MIN_CONFIDENCE) / (1 - CORE_MIN_CONFIDENCE) * max(0.2, 1 - CORE_CURVE_SLOWDOWN * abs(error))
    assert abs(w / v - 2 * y / (x * x + y * y)) < 1e-6 and error < 0
    assert pursuit_error(0.25, 0.0, conf) == 0.0


def test_route_guide_picks_the_side_and_turns_at_a_blind_corner():
    closed = _lane(0.06, -0.06, x_max=0.13)         # wall ahead, no opening in view
    error, _, debug = DrivableSteer().update(closed, 1, G, XO, HALF, guide_deg=80.0)
    assert debug["strategy"] == "drivable_pivot_left" and error < 0
    both = _lane(0.5, -0.5, x_max=0.15) | _lane(0.03, -0.03, x_max=0.33)
    debug = DrivableSteer().update(both, 1, G, XO, HALF, guide_deg=-70.0)[2]
    assert debug["exit"] in ("right", None)


def test_facing_against_the_route_reorients_in_place():
    error, confidence, debug = DrivableSteer().update(_lane(HALF, -HALF), 1, G, XO, HALF, guide_deg=-170.0)
    assert debug["strategy"] == "drivable_reorient_right" and error > 0 and confidence == PIVOT_CONFIDENCE


def test_map_bridges_a_cut_way_when_the_lane_goes_on_and_defers_reorient_in_a_narrow_lane():
    cut = _lane(HALF, -HALF, x_max=0.13)              # blue tape across the lane
    debug = DrivableSteer().update(cut, 1, G, XO, HALF, guide_deg=3.0)[2]
    assert debug["strategy"] == "drivable_map_bridge"
    debug = DrivableSteer().update(cut, 1, G, XO, HALF, guide_deg=3.0, wall_ahead_m=0.15)[2]
    assert debug["strategy"] != "drivable_map_bridge"
    debug = DrivableSteer().update(_lane(HALF, -HALF), 1, G, XO, HALF, guide_deg=170.0, guide_pivot_ok=False)[2]
    assert not debug["strategy"].startswith("drivable_reorient") and debug.get("reorient_deferred")


def test_no_turn_circle_creeps_along_the_way_then_holds():
    # architect 2026-10-10: off the ring-entry turn spots a pivot becomes a <= 0.07 m creep, then HOLD
    steer, way = DrivableSteer(), _lane(0.5, -HALF, x_max=0.2) | _lane(0.5, 0.04, x_max=0.33)
    kw = dict(guide_deg=60.0, guide_pivot_ok=False)
    debug = steer.update(way, 1, G, XO, HALF, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), **kw)[2]
    assert debug["strategy"] == "drivable_creep", debug
    error, confidence, debug = steer.update(way, 2, G, XO, HALF, (0.08, 0.0, 0.0), (0.08, 0.0, 0.0), **kw)
    assert error is None and debug["reason"] == "creep_done", debug
    debug = DrivableSteer().update(_lane(HALF, -HALF), 1, G, XO, HALF, guide_deg=170.0, guide_here_deg=170.0,
                                   guide_pivot_ok=False)[2]
    assert debug["reason"] == "wrong_way_hold", debug
