"""D-597 amendment 2: keep steers to the centre of the drivable way; closed ahead, it turns in
place toward the side the way leaves the view."""
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
    error, confidence, debug = steer.update(_lane(0.5, -HALF, x_max=0.2) | _lane(0.5, 0.0, x_max=0.33), 1, G, XO, HALF)
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
    assert turned > straight + 0.3       # turned left since the frame: the same point now lies right
