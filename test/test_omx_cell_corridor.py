"""cell_corridor: anything where the path goes low, or an unknown blob under high travel, refuses the leg."""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_corridor as cc  # noqa: E402

ROI = (0, 0, 400, 400)
PICK, PLACE = (0.13, 0.08), (0.16, -0.02)


def to_px(p):  # 1 px per mm, arm (0, 0) at pixel (200, 200)
    return (200 + p[0] * 1000, 200 + p[1] * 1000)


def blob(mask, xy, r=8):
    cx, cy = to_px(xy)
    mask[int(cy) - r:int(cy) + r, int(cx) - r:int(cx) + r] = 1
    return mask


def leg():
    """Rise-turn-descend as on 2026-11-01: down at the pick, travel at 138 mm, down at the place."""
    down = lambda xy: [(xy[0], xy[1], z) for z in np.linspace(0.14, 0.03, 12)]  # noqa: E731
    travel = [(x, y, 0.138) for x, y in np.linspace(PICK, PLACE, 30)]
    return down(PICK) + down(PICK)[::-1] + travel + down(PLACE)


def empty():
    return np.zeros((400, 400), np.uint8)


def test_runs_split_low_and_high_and_skip_the_base():
    tcp = [(0.05, 0.0, 0.05), (0.15, 0.0, 0.05), (0.16, 0.0, 0.20), (0.17, 0.0, 0.04), (0.18, 0.0, 0.04)]
    assert cc.runs(tcp) == ([[(0.15, 0.0)], [(0.17, 0.0), (0.18, 0.0)]], [[(0.16, 0.0)]])


def test_a_clear_table_and_the_pick_object_itself_pass():
    assert cc.check(leg(), empty(), ROI, to_px)["clear"]
    assert cc.check(leg(), blob(empty(), PICK), ROI, to_px, pick_xy=PICK)["clear"]


def test_something_beside_the_pick_object_inside_the_jaws_lane_is_in_the_way():
    mask = blob(blob(empty(), PICK), (PICK[0] + 0.025, PICK[1]), r=5)
    mask[:, int(to_px(PICK)[0]) + 8:int(to_px(PICK)[0]) + 20] = 0  # a gap: two blobs, not one
    out = cc.check(leg(), mask, ROI, to_px, pick_xy=PICK)
    assert not out["clear"] and out["low"]


def test_the_place_slot_must_be_empty_unless_a_stack_is_declared():
    mask = blob(empty(), PLACE)
    assert cc.check(leg(), mask, ROI, to_px, pick_xy=PICK)["low"]
    assert cc.check(leg(), mask, ROI, to_px, pick_xy=PICK, stack_xy=PLACE)["clear"]


def test_under_high_travel_a_known_box_passes_and_an_unknown_blob_does_not():
    middle = tuple(np.mean([PICK, PLACE], axis=0))
    mask = blob(empty(), middle)
    out = cc.check(leg(), mask, ROI, to_px, pick_xy=PICK)
    assert not out["clear"] and out["high"] and not out["low"]
    assert cc.check(leg(), mask, ROI, to_px, pick_xy=PICK, known=mask.copy())["clear"]


def test_a_blob_well_off_the_path_is_not_in_the_way():
    assert cc.check(leg(), blob(empty(), (0.25, 0.15)), ROI, to_px, pick_xy=PICK)["clear"]


def test_a_path_off_the_map_is_not_clear():
    assert not cc.check(leg(), empty(), ROI, lambda p: None)["clear"]
