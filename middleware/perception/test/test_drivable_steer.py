"""D-597 amendment 2: keep steers to the centre of the drivable way; closed ahead, it turns in
place toward the side the way leaves the view."""
import math
from types import SimpleNamespace

import numpy as np
import pytest

from control.sensing.perception.drivable.drivable_steer import (
    CORE_CRUISE_MPS, CORE_MIN_CONFIDENCE, PIVOT_CONFIDENCE, PIVOT_ERROR, DrivableSteer, _centre_target,
    one_edge_centre, way_target)

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


def test_observed_centre_path_stops_at_a_gap_between_way_rows():
    from control.sensing.perception.drivable.target import _row_x
    way = _lane(HALF, -HALF)
    way[160:165] = False
    info = way_target(way, G, XO, HALF)
    path = info['centre_path_m']
    assert len(path) > 2
    assert all(0. < point[0] <= _row_x([165], G, XO)[0] for point in path)
    assert all(a[0] < b[0] for a, b in zip(path, path[1:]))


def _columns(left, right, top=130):
    """A way drawn in pixels: rows top..239, columns left(f)..right(f), f 0 at the bottom row, 1 at top."""
    way = np.zeros((240, 320), bool)
    for row in range(top, 240):
        f = (239 - row) / (239 - top)
        way[row, int(left(f)):int(right(f)) + 1] = True
    return way


def test_a_bend_the_robot_lags_is_followed_not_closed():
    # v2 lap r6: behind a right bend the way leaves the straight corridor from the nearest row, both
    # edges inside the frame; the corridor read 0 m with the centre target 0.21 m ahead and keep stopped
    way = _columns(lambda f: 150 + 40 * f, lambda f: 300 + 10 * f)
    t = way_target(way, G, XO, HALF)
    assert t["ahead_m"] < 0.12 and t["exit"] is None and t["target_m"][0] >= 0.18
    error, confidence, debug = DrivableSteer().update(way, 1, G, XO, HALF)
    assert debug["strategy"] == "drivable_centre" and error > 0     # on, toward the bend's right


def test_a_corner_turning_inside_the_view_pivots_toward_the_ways_target():
    # v2 lap r8: at an inner corner 0.16 m from the wall the way turned left without reaching the frame
    # border, so there was no opening and no memory; keep stood closed until Fleet's stall
    way = _columns(lambda f: 60 - 40 * f, lambda f: 260 - 200 * f ** 0.5, top=170)
    t = way_target(way, G, XO, HALF)
    assert t["ahead_m"] < 0.14 and t["seen_exit"] is None and t["target_m"][1] > 0
    error, confidence, debug = DrivableSteer().update(way, 1, G, XO, HALF)
    assert (error, debug["strategy"], debug["exit_from_target"]) == (-PIVOT_ERROR, "drivable_pivot_left", True)


def test_the_target_can_ask_for_the_maps_tightest_bend():
    # map_v2_fleet NE corner: a ~0.12 m radius quarter turn of the lane centre
    s = np.linspace(0.0, 0.19, 40)
    xs, centre = 0.12 * np.sin(s / 0.12), 0.12 * (1.0 - np.cos(s / 0.12))
    _, curvature, _ = _centre_target(xs, centre, 0.25)
    assert curvature >= 1.0 / 0.125


def test_closed_at_the_body_a_tight_corner_turns_in_place_though_the_arc_clips_its_inner_edge(monkeypatch):
    # v2 lap r11: a ~0.06 m radius corner; the arc to the way's target cut the way's own inner edge,
    # so the side was "behind a line" and keep stood closed at the corner
    import control.sensing.perception.drivable.drivable_steer as steer_module
    way = _columns(lambda f: 100 - 90 * f, lambda f: 175 - 120 * f, top=150)
    assert way_target(way, G, XO, HALF)["ahead_m"] < 0.05
    pose = (0.0, 0.0, 0.0)
    debug = DrivableSteer().update(way, 1, G, XO, HALF, pose, pose)[2]
    assert debug["strategy"] == "drivable_pivot_left" and debug["exit_from_target"]
    monkeypatch.setattr(steer_module, "PIVOT_AT_BODY_M", 0.0)     # the arc alone is rejected
    assert DrivableSteer().update(way, 1, G, XO, HALF, pose, pose)[2]["strategy"] != "drivable_pivot_left"


def test_a_turn_in_place_outlasts_a_frame_without_a_side_until_the_way_runs_on():
    # v2 lap r13: a frame naming no side dropped the corner pivot; the robot arced out to the wall
    pose = (0.0, 0.0, 0.0)
    steer = DrivableSteer()
    corner = _columns(lambda f: 100 - 90 * f, lambda f: 175 - 120 * f, top=150)
    assert steer.update(corner, 1, G, XO, HALF, pose, pose)[2]["strategy"] == "drivable_pivot_left"
    no_side = steer.update(_lane(0.06, -0.06, x_max=0.13), 2, G, XO, HALF, pose, pose)[2]
    assert no_side["exit"] is None and no_side["strategy"] == "drivable_pivot_left"
    on = steer.update(_lane(HALF, -HALF), 3, G, XO, HALF, pose, pose)[2]
    assert on["straight_on"] and on["strategy"] == "drivable_centre"


@pytest.mark.parametrize("min_confidence", [CORE_MIN_CONFIDENCE, 0.5])
def test_a_turn_in_place_is_sent_at_the_laws_min_confidence_so_core_drives_no_linear(min_confidence):
    # v2 lap r9-r16: at 0.37 CORE's speed scale left ~2 mm/s, so a wall 0.13 m off the front sector (inside
    # the 0.149 m stop distance) stopped the turn too, at the NE corner exit until the stall
    pose = (0.0, 0.0, 0.0)
    corner = _columns(lambda f: 100 - 90 * f, lambda f: 175 - 120 * f, top=150)
    error, confidence, debug = DrivableSteer(min_confidence=min_confidence).update(corner, 1, G, XO, HALF, pose, pose)
    assert debug["strategy"] == "drivable_pivot_left" and confidence == min_confidence
    assert PIVOT_CONFIDENCE == CORE_MIN_CONFIDENCE
    span = 1.0 - min_confidence             # line_follow manager._steer: linear scales by this share
    assert CORE_CRUISE_MPS * max(0.0, (confidence - min_confidence) / span) == 0.0


def test_a_front_sector_inside_cores_stop_distance_turns_in_place_toward_the_target_until_it_clears():
    # v2 lap r17: top lane 0.12 m from the north wall, robot 28 deg short of parallel; CORE stopped every
    # forward step while keep, the way running on ahead, kept asking for a gentle arc
    pose = (0.0, 0.0, 0.0)
    way = _lane(HALF, -HALF)
    steer = DrivableSteer()
    blocked = steer.update(way, 1, G, XO, HALF, pose, pose, front_sector_m=0.125)[2]
    assert blocked["strategy"] == "drivable_pivot_left" and blocked["front_blocked_m"] == 0.125
    clear = steer.update(way, 2, G, XO, HALF, pose, pose, front_sector_m=0.2)[2]
    assert clear["strategy"] == "drivable_centre"


@pytest.mark.parametrize("index, front", [(0, 0.14), (40, 0.14), (90, None)])   # LiDAR range, as CORE
def test_scan_summary_reports_cores_front_sector(index, front):
    # Pinky mount: scan angle -pi looks forward from x -0.017 m; 40 deg off is in the +-45 deg sector, 90 is not
    from control.sensing.perception.drivable.drivable_keep import scan_summary
    ranges = [math.inf] * 360
    ranges[index] = 0.14
    got = scan_summary(ranges, -math.pi, 2 * math.pi / 360, 0.01, 6.0)[2]
    assert got == pytest.approx(front, abs=0.005) if front is not None else got is None


def test_a_near_blob_on_a_way_that_runs_on_ahead_turns_nothing_in_place():
    # v2 lap r12: a blob of non-way by the inner line closed the camera's narrow near rows (ahead 0) 0.1 m
    # before the NE bend; keep pivoted toward the opening remembered and left the lane
    way = _lane(HALF, -HALF)
    way[205:240, 0:150] = False
    assert way_target(way, G, XO, HALF)["ahead_m"] < 0.05
    pose = (0.0, 0.0, 0.0)
    steer = DrivableSteer()
    steer._memory = ("left", pose)
    error, _, debug = steer.update(way, 1, G, XO, HALF, pose, pose)
    assert debug["straight_on"] and debug["strategy"] == "drivable_centre" and abs(error) < PIVOT_ERROR


def test_a_way_that_ends_just_ahead_still_stops():
    error, _, debug = DrivableSteer().update(_columns(lambda f: 100, lambda f: 220, top=232), 1, G, XO, HALF)
    assert error is None and debug["reason"] == "drivable_closed"


@pytest.mark.parametrize("slope", [0.0, 1.0, -3.0])
def test_one_edge_centre_lies_the_offset_away_along_the_edge_normal(slope):
    # v2 lap r7: a tight bend's inner line runs sideways; an across-row offset put the centre in the corner
    xs = np.linspace(0.12, 0.40, 40)
    edge = -0.1 + slope * (xs - 0.2)
    cx, cy = one_edge_centre(xs, edge, 0.08)
    distance = (cy - (-0.1 + slope * (cx - 0.2))) / math.hypot(1.0, slope)   # signed, left +
    assert np.allclose(distance, 0.08, atol=1e-6)
    assert np.allclose(one_edge_centre(xs, edge, -0.08)[1], edge - 0.08 / math.hypot(1.0, slope))


def test_near_edges_are_the_way_edges_by_the_robot_and_an_off_frame_side_is_unseen():
    near = way_target(_lane(HALF, -HALF), G, XO, HALF)["near_edges_m"]
    for side, y in (("left", HALF), ("right", -HALF)):
        assert len(near[side]) >= 5 and all(abs(p[1] - y) < 0.01 for p in near[side])
        assert max(p[0] for p in near[side]) - min(p[0] for p in near[side]) <= 0.121
    # a bend's left edge seen only from 0.2 m on: near the robot that side runs off the frame
    near = way_target(_lane(0.4, -HALF), G, XO, HALF)["near_edges_m"]
    assert near["left"] == [] and len(near["right"]) >= 5


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


def test_reset_cannot_republish_the_previous_turn_on_a_fresh_straight_lane():
    steer = DrivableSteer()
    corner = _lane(0.5, -HALF, x_max=0.2) | _lane(0.5, 0.04, x_max=0.33)
    assert steer.update(corner, 1, G, XO, HALF)[2]["strategy"] == "drivable_turn_left"
    steer.reset()  # Called when camera evidence is invalidated.
    straight = _lane(HALF, -HALF)
    error, confidence, info = steer.update(straight, 2, G, XO, HALF)
    fresh_error, fresh_confidence, fresh_info = DrivableSteer().update(straight, 2, G, XO, HALF)
    assert (error, confidence, info["strategy"], info.get("target_now_m")) == (
        fresh_error, fresh_confidence, fresh_info["strategy"], fresh_info.get("target_now_m"))


def test_only_a_wall_within_two_cm_of_the_body_front_invents_a_closed_way():
    way = _lane(0.5, -HALF)                 # open straight ahead in the camera, wide to the left
    distant = DrivableSteer().update(way, 1, G, XO, HALF, wall_ahead_m=0.18)[2]
    assert distant["strategy"] == "drivable_centre", distant
    error, confidence, debug = DrivableSteer().update(way, 1, G, XO, HALF, wall_ahead_m=0.06)
    assert debug["ahead_m"] < 0.14 and debug["strategy"] == "drivable_pivot_left", debug


def test_remembered_exit_cannot_turn_towards_a_newly_seen_side_wall():
    steer = DrivableSteer()
    pose = (0.0, 0.0, 0.0)
    steer.update(_lane(0.5, -HALF, x_max=0.33), 1, G, XO, HALF, pose, pose)
    debug = steer.update(_lane(0.06, -0.06, x_max=0.13), 2, G, XO, HALF,
                         pose, pose, side_clear_m={"left": 0.10, "right": None})[2]
    assert debug["strategy"] != "drivable_pivot_left" and not debug.get("exit_from_memory"), debug


def test_side_exit_with_more_than_five_cm_outside_the_body_remains_open():
    way = _lane(0.5, -0.5, x_max=0.15) | _lane(0.5, -0.03, x_max=0.33)
    debug = DrivableSteer().update(way, 1, G, XO, HALF,
                                  side_clear_m={"left": 0.145, "right": None})[2]
    assert debug["exit"] == "left", debug


def test_exit_rejected_for_crossing_a_boundary_cannot_return_from_memory():
    steer = DrivableSteer()
    pose = (0.0, 0.0, 0.0)
    steer.update(_lane(0.5, -HALF, x_max=0.33), 1, G, XO, HALF, pose, pose)
    # A previously observed transverse boundary lies between us and the apparent opening.
    steer._edges = [(0.15, float(y)) for y in np.linspace(-0.5, 0.5, 80)]
    closed = _lane(0.5, -HALF, x_max=0.12) | _lane(0.5, 0.04, x_max=0.33)
    debug = steer.update(closed, 2, G, XO, HALF, pose, pose)[2]
    assert debug.get("exit_behind_line") and not debug.get("exit_from_memory"), debug
    assert debug["strategy"] != "drivable_pivot_left", debug


def test_an_exit_the_route_turns_into_is_kept_across_a_remembered_boundary():
    steer = DrivableSteer()
    pose = (0.0, 0.0, 0.0)
    steer.update(_lane(0.5, -HALF, x_max=0.33), 1, G, XO, HALF, pose, pose)
    steer._edges = [(0.15, float(y)) for y in np.linspace(-0.5, 0.5, 80)]
    closed = _lane(0.5, -HALF, x_max=0.12) | _lane(0.5, 0.04, x_max=0.33)
    debug = steer.update(closed, 2, G, XO, HALF, pose, pose, guide_deg=75.0)[2]
    assert debug["exit"] == "left" and not debug.get("exit_behind_line"), debug


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
    from control.sensing.perception.drivable.drivable_steer import _crosses
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


def test_crosswalk_straight_does_not_override_a_lidar_front_stop():
    steer = DrivableSteer()
    steer.crosswalk((0.0, 0.0, 0.0))
    way = _lane(0.5, -HALF, x_max=0.12) | _lane(0.5, 0.04, x_max=0.33)
    error, confidence, debug = steer.update(way, 1, G, XO, HALF,
        (0.05, 0.0, 0.0), (0.05, 0.0, 0.0), front_sector_m=0.114)
    assert debug["strategy"] == "drivable_pivot_left", debug
    assert error < 0 and confidence == CORE_MIN_CONFIDENCE

    error, _, debug = steer.update(way, 2, G, XO, HALF,
        (0.05, 0.0, 0.0), (0.05, 0.0, 0.0), front_sector_m=0.3)
    assert (error, debug["strategy"]) == (0.0, "drivable_crosswalk_straight"), debug


def test_an_in_place_turn_stops_after_about_a_hundred_degrees():
    steer = DrivableSteer()
    closed = _lane(0.5, -HALF, x_max=0.12) | _lane(0.5, 0.04, x_max=0.33)
    assert steer.update(closed, 1, G, XO, HALF, current_pose=(0.0, 0.0, 0.0))[2]["strategy"] == "drivable_pivot_left"
    after = steer.update(closed, 2, G, XO, HALF, current_pose=(0.0, 0.0, 1.9))[2]
    assert after.get("pivot_limit") and not after["strategy"].startswith("drivable_pivot")


def test_a_way_beyond_a_line_with_side_walls_known_holds_without_error():
    beyond = np.zeros((240, 320), bool)
    beyond[115:160, 100:220] = True                      # floor only beyond a gap
    error, confidence, debug = DrivableSteer().update(beyond, 1, G, XO, HALF, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0),
                                                      wall_ahead_m=None, side_clear_m={"left": None, "right": None})
    assert error is None and debug["reason"] == "way_beyond_line"


def test_a_bend_ahead_sets_the_target_on_the_centreline_curvature():
    # 0.16 m straight, then a left bend of radius 0.20. A straight-ahead slice at 0.25 m
    # still sits near y=0.02 (chord curvature under 1/m). The centre line has already
    # turned, so the target is the arc of that curvature.
    xs, ys = [], []
    for x in np.linspace(0.04, 0.16, 7):
        xs.append(x)
        ys.append(0.0)
    radius = 0.20
    for distance in np.linspace(0.02, 0.12, 6):
        turn = distance / radius
        xs.append(0.16 + radius * math.sin(turn))
        ys.append(radius * (1.0 - math.cos(turn)))
    point, curvature, _ = _centre_target(np.asarray(xs), np.asarray(ys), 0.25)
    assert curvature > 1.2, (point, curvature)
    assert point[1] > 0.03
    chord = 2.0 * point[1] / (point[0] * point[0] + point[1] * point[1])
    assert abs(chord - curvature) < 0.15


def test_an_offset_straight_centre_comes_back_instead_of_taking_a_false_bend():
    xs = np.linspace(0.05, 0.30, 8)
    point, curvature, _ = _centre_target(xs, np.full(xs.shape, 0.05), 0.25)
    assert curvature > 0.0 and point[1] > 0.03


def test_pursuit_cruise_is_the_line_follow_cruise():
    assert CORE_CRUISE_MPS == 0.08


def test_pursuit_error_realises_the_arc_under_cores_law():
    from control.sensing.perception.drivable.drivable_steer import (
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


def test_a_closed_corner_on_a_turning_route_turns_in_place_and_a_reversed_robot_still_holds():
    # user 2026-10-18: the route prior names the side only; a turn in place is CORE's to admit, not a
    # creep-then-hold (architect 2026-10-10 rule, which held the v2 lap at its corners)
    steer, way = DrivableSteer(), _lane(0.06, -0.06, x_max=0.13)   # closed, no opening in view
    kw = dict(guide_deg=80.0, guide_here_deg=0.0, guide_pivot_ok=False)
    error, _, debug = steer.update(way, 1, G, XO, HALF, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), **kw)
    assert debug["strategy"] == "drivable_pivot_left" and debug["exit_from_guide"] and error == -PIVOT_ERROR
    right = DrivableSteer().update(way, 1, G, XO, HALF, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0),
                                   **dict(kw, guide_deg=-80.0))[2]
    assert right["strategy"] == "drivable_pivot_right"     # the route's side, not keep-left/right
    debug = DrivableSteer().update(_lane(HALF, -HALF), 1, G, XO, HALF, guide_deg=170.0, guide_here_deg=170.0,
                                   guide_pivot_ok=False)[2]
    assert debug["reason"] == "wrong_way_hold", debug
    debug = DrivableSteer().update(_lane(HALF, -HALF), 1, G, XO, HALF, guide_deg=16.0, guide_here_deg=170.0,
                                   guide_pivot_ok=False)[2]
    assert debug.get("reason") != "wrong_way_hold", debug     # a polyline joint, the lane ahead agrees


def test_driving_context_rules(monkeypatch):
    # (b) a side opening is not an exit where the map goes on (bend < 15 deg)
    both = _lane(0.5, -0.5, x_max=0.15) | _lane(0.03, -0.03, x_max=0.33)
    assert DrivableSteer().update(both, 1, G, XO, HALF, guide_deg=10.0)[2]["exit"] is None
    # (c2) a target off the map heading for >= 2 s: HOLD and request realign
    import control.sensing.perception.drivable.drivable_steer as ds
    clock = iter([0.0, 0.0, 3.0, 3.0, 3.0, 3.0])
    monkeypatch.setattr(ds.time, "monotonic", lambda: next(clock, 3.0))
    steer, lane = DrivableSteer(), _lane(HALF, -HALF)
    steer.update(lane, 1, G, XO, HALF, guide_deg=-80.0, guide_here_deg=-80.0, guide_fresh=True)
    error, _, debug = steer.update(lane, 2, G, XO, HALF, guide_deg=-80.0, guide_here_deg=-80.0, guide_fresh=True)
    assert error is None and debug["reason"] == "realign", debug
    assert debug["context"]["last"], debug


def test_a_map_corner_is_not_a_crosswalk_hold_and_turns_toward_the_opening():
    # g10-9dfk SW corner: transverse line read as crosswalk bars, guide 83 deg left, opening left
    steer = DrivableSteer()
    corner = _lane(HALF, -HALF, x_max=0.13) | _lane(0.5, 0.02, x_max=0.3)
    steer.crosswalk((0.0, 0.0, 0.0))
    error, _, debug = steer.update(corner, 1, G, XO, HALF, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), guide_deg=83.0,
                                   guide_here_deg=80.0, guide_pivot_ok=False)
    assert debug["strategy"] != "drivable_crosswalk_straight" and error is not None and error < 0, debug


def test_a_corner_never_turns_toward_an_opening_against_the_route():
    # c2-8kcn: the way closed with an opening left while the map said right: no turn to the left
    closed_left = _lane(0.06, -0.06, x_max=0.13) | _lane(0.5, 0.02, x_max=0.3)
    error, _, debug = DrivableSteer().update(closed_left, 1, G, XO, HALF, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0),
                                             guide_deg=-45.0, guide_here_deg=0.0, guide_pivot_ok=False)
    assert error is None or error >= 0, debug          # the map tangent (right) or a HOLD, never left


def test_the_routes_exit_is_kept_by_odometry_once_it_leaves_the_view(monkeypatch):
    import control.sensing.perception.drivable.drivable_steer as steer_module
    steer = DrivableSteer()
    pose = (0.0, 0.0, 0.0)
    exit_right = _lane(HALF, -0.5, x_max=0.15) | _lane(HALF, -HALF, x_max=0.26)   # 0.2-0.3 m from the corner
    seen = steer.update(exit_right, 1, G, XO, HALF, pose, pose, guide_deg=-75.0)[2]
    assert seen["exit"] == "right", seen
    # v2 lap r25 at the ring's NW exit: the right exit out of the view, the ring bending on to the left
    ring = dict(target_m=(0.22, 0.06), ahead_m=0.22, exit=None, seen_exit="left", straddle=None, both=False,
                exit_point_m={"left": (0.18, 0.09)}, exit_reach_m={"left": 0.22}, near_centre_m=(0.14, 0.05),
                centre_path_m=[], edges_m=[], near_edges_m={})
    monkeypatch.setattr(steer_module, "way_target", lambda *a, **k: dict(ring))
    moved = (0.03, 0.0, 0.0)
    debug = steer.update(exit_right, 2, G, XO, HALF, moved, moved, guide_deg=-80.0)[2]
    assert debug["exit"] == "right" and debug.get("exit_from_route_memory"), debug
    moved = (0.05, -0.01, -0.2)                           # a switch of strategy takes two frames
    debug = steer.update(exit_right, 3, G, XO, HALF, moved, moved, guide_deg=-70.0)[2]
    assert debug["strategy"] == "drivable_turn_right", debug


def test_a_mild_map_bend_is_arced_and_a_sharp_one_turned_in_place(monkeypatch):
    import control.sensing.perception.drivable.drivable_steer as steer_module
    # v2 lap r28: the way read closed at the body 0.14 m before a 62 deg corner, the map 34 deg ahead
    closed = dict(target_m=(0.15, -0.1), ahead_m=0.0, exit="right", seen_exit="right", straddle=None, both=False,
                  exit_point_m={"right": (0.18, -0.07)}, exit_reach_m={"right": 0.19}, near_centre_m=(0.14, 0.0),
                  centre_path_m=[], edges_m=[], near_edges_m={})
    monkeypatch.setattr(steer_module, "way_target", lambda *a, **k: dict(closed))
    mild = DrivableSteer().update(_lane(HALF, -HALF), 1, G, XO, HALF, guide_deg=-34.0)[2]
    assert mild["strategy"] == "drivable_turn_right", mild
    sharp = DrivableSteer().update(_lane(HALF, -HALF), 1, G, XO, HALF, guide_deg=-70.0)[2]
    assert sharp["strategy"] == "drivable_pivot_right", sharp


def test_a_seen_opening_is_turned_into_rather_than_bridged_on_the_map(monkeypatch):
    import control.sensing.perception.drivable.drivable_steer as steer_module
    # v2 lap r33 after the NE corner: closed at the body, an opening seen ahead left, the map bend easing to
    # 21.8 deg (under GUIDE_STRAIGHT_DEG). The map bridge was refused as unobserved floor and the robot stood.
    closed = dict(target_m=(0.204, 0.123), ahead_m=0.0, exit="left", seen_exit="left", straddle=None, both=False,
                  exit_point_m={"left": (0.204, 0.123)}, exit_reach_m={"left": 0.24}, near_centre_m=(0.14, 0.05),
                  centre_path_m=[], edges_m=[], near_edges_m={})
    monkeypatch.setattr(steer_module, "way_target", lambda *a, **k: dict(closed))
    debug = DrivableSteer().update(_lane(HALF, -HALF), 1, G, XO, HALF, guide_deg=21.8)[2]
    assert debug["strategy"] == "drivable_turn_left", debug


def test_a_body_corridor_closed_by_drifting_to_the_edge_recentres_before_the_bend(monkeypatch):
    import control.sensing.perception.drivable.drivable_steer as steer_module
    # v2 lap r45a on the east road's turn north: drifted to the left edge, the way's centre 7 cm right, the
    # body corridor read 0 m and the robot pivoted left 0.2 m before the bend (map 51 deg ahead)
    edge = dict(target_m=(0.213, -0.111), ahead_m=0.0, exit="left", seen_exit="left", straddle=None, both=False,
                exit_point_m={"left": (0.262, 0.134), "right": (0.197, -0.096)},
                exit_reach_m={"left": 0.364, "right": 0.219}, near_centre_m=(0.163, -0.07),
                centre_path_m=[], edges_m=[], near_edges_m={})
    monkeypatch.setattr(steer_module, "way_target", lambda *a, **k: dict(edge))
    debug = DrivableSteer().update(_lane(HALF, -HALF), 1, G, XO, HALF, guide_deg=51.4)[2]
    assert debug["strategy"] == "drivable_centre" and debug.get("recentre_first"), debug
    corner = dict(edge, near_centre_m=(0.14, 0.0))       # centred at a real corner: still turned in place
    monkeypatch.setattr(steer_module, "way_target", lambda *a, **k: dict(corner))
    assert DrivableSteer().update(_lane(HALF, -HALF), 1, G, XO, HALF, guide_deg=51.4)[2]["strategy"] == "drivable_pivot_left"


def test_an_arc_toward_the_routes_bend_waits_while_the_ways_centre_lies_the_other_way(monkeypatch):
    import control.sensing.perception.drivable.drivable_steer as steer_module
    # v2 lap r50b on the south spoke: the map bends left 0.25 m on, the way's centre still 6 cm right; an arc
    # left from there cut the corner and left the lane
    spoke = dict(target_m=(0.238, -0.067), ahead_m=0.194, exit=None, seen_exit="right", straddle=None, both=False,
                 exit_point_m={"left": (0.2, 0.12), "right": (0.2, -0.1)}, exit_reach_m={"left": 0.3, "right": 0.25},
                 exit_near={"left": True, "right": False}, near_centre_m=(0.163, -0.055), centre_path_m=[], edges_m=[], near_edges_m={})
    monkeypatch.setattr(steer_module, "way_target", lambda *a, **k: dict(spoke))
    debug = DrivableSteer().update(_lane(HALF, -HALF), 1, G, XO, HALF, guide_deg=25.0)[2]
    assert debug["strategy"] == "drivable_centre" and debug.get("recentre_first"), debug
