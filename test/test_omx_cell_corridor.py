"""cell_corridor: a blob where the planned path goes low is refused; the work itself and high travel are not."""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_corridor as cc  # noqa: E402

ROI = (0, 0, 400, 400)


def to_px(p):  # 1 px per mm, arm (0, 0) at pixel (200, 200)
    return (200 + p[0] * 1000, 200 + p[1] * 1000)


def blob(mask, x_m, y_m, r=8):
    cx, cy = to_px((x_m, y_m))
    mask[int(cy) - r:int(cy) + r, int(cx) - r:int(cx) + r] = 1
    return mask


def lane_for(tcp):
    return cc.corridor(cc.low_points(tcp), to_px, (400, 400), ROI)


def test_only_low_points_away_from_the_base_make_the_corridor():
    tcp = [(0.05, 0.0, 0.05), (0.15, 0.0, 0.05), (0.16, 0.0, 0.20), (0.17, 0.0, 0.04), (0.18, 0.0, 0.04)]
    assert cc.low_points(tcp) == [[(0.15, 0.0)], [(0.17, 0.0), (0.18, 0.0)]]


def test_a_box_on_the_low_path_is_a_hit_and_one_beside_it_is_not():
    tcp = [(0.12, y, 0.04) for y in np.linspace(-0.05, 0.05, 11)]
    lane = lane_for(tcp)
    assert cc.hits(blob(np.zeros((400, 400), np.uint8), 0.12, 0.0), lane, roi=ROI)
    assert not cc.hits(blob(np.zeros((400, 400), np.uint8), 0.12 + 0.08, 0.0), lane, roi=ROI)


def test_the_pick_object_is_the_work_not_an_obstacle():
    tcp = [(0.12, 0.0, 0.04)]
    mask = blob(np.zeros((400, 400), np.uint8), 0.12, 0.0)
    assert cc.hits(mask, lane_for(tcp), roi=ROI)
    assert not cc.hits(mask, lane_for(tcp), exempt_px=[to_px((0.12, 0.0))], exempt_r_px=45, roi=ROI)


def test_travel_above_the_clear_height_passes_over_a_box():
    tcp = [(0.12, y, 0.15) for y in np.linspace(-0.05, 0.05, 11)]
    assert not lane_for(tcp).any()


def test_a_path_off_the_map_draws_nothing():
    lane = cc.corridor([[(0.12, 0.0)]], lambda p: None, (400, 400), ROI)
    assert not lane.any()
