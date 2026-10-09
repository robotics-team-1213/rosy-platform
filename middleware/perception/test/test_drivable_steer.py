"""D-597 amendment 2: keep steers to the centre of the drivable way; closed ahead, it turns in
place toward the side the way leaves the view."""
from types import SimpleNamespace

import numpy as np

from control.sensing.perception.learned.drivable_steer import (
    PIVOT_CONFIDENCE, PIVOT_ERROR, DrivableSteer, way_target)

G = SimpleNamespace(height_m=0.0575, pitch_rad=0.195, focal_px=281.6, principal_x=160.0, principal_y=120.0)
XO, HALF = 0.033, 0.0925


def _way(rows, cols):
    way = np.zeros((240, 320), bool)
    way[rows, cols] = True
    return way


def test_centred_lane_steers_straight():
    t = way_target(_way(slice(112, None), slice(100, 220)), G, XO, HALF)
    assert abs(t["target_m"][1]) < 0.01 and t["both"] and t["ahead_m"] > 0.3


def test_one_unseen_edge_offsets_from_the_seen_edge():
    t = way_target(_way(slice(112, None), slice(0, 150)), G, XO, HALF)
    assert t["target_m"][1] > 0.02 and not t["both"]


def test_closed_ahead_pivots_toward_the_open_side_then_releases():
    steer = DrivableSteer()
    error, confidence, debug = steer.update(_way(slice(200, None), slice(0, 250)), 1, G, XO, HALF)
    assert (error, confidence, debug["strategy"]) == (-PIVOT_ERROR, PIVOT_CONFIDENCE, "drivable_pivot_left")
    error, confidence, debug = steer.update(_way(slice(112, None), slice(100, 220)), 2, G, XO, HALF)
    assert debug["strategy"] == "drivable_centre" and abs(error) < 0.2


def test_wall_corner_border_near_the_robot_loses_to_the_far_open_side():
    way = _way(slice(112, None), slice(0, 320))
    for row in range(112, 200):          # a wall corner on the right: floor reaches the right border only near
        way[row, 320 - (200 - row) * 3:] = False
    assert way_target(way, G, XO, HALF)["exit"] == "left"


def test_odometry_moves_the_target_into_the_current_pose():
    steer = DrivableSteer()
    way = _way(slice(112, None), slice(100, 220))
    straight, _, _ = steer.update(way, 1, G, XO, HALF, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    steer.reset()
    turned, _, _ = steer.update(way, 1, G, XO, HALF, (0.0, 0.0, 0.0), (0.0, 0.0, 0.3))
    assert turned > straight + 0.3       # turned left since the frame: the same point now lies right
