"""Off the cell's dock target -> the vehicle re-parks, before any arm command (2026-11-19)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))
import cell_task_exec as te  # noqa: E402


def test_box_off_target_asks_for_the_move_and_inside_tolerance_does_not():
    fix = te.zone_fix([0.064, 0.178], [[-0.0291, 0.1689]])
    assert fix["need_arm_dxdy_m"] == [0.0931, 0.0091] and fix["object_arm_xy_m"] == [-0.0291, 0.1689]
    assert te.zone_fix([0.064, 0.178], [[0.0553, 0.1858]]) is None  # 11-19 05:20 measured 12 mm off
    assert te.zone_fix([0.064, 0.178], []) is None and te.zone_fix(None, [[0, 0]]) is None


def test_the_nearest_object_is_the_one_moved_to_target():
    fix = te.zone_fix([0.0, 0.2], [[0.3, 0.3], [0.0, 0.15]])
    assert fix["object_arm_xy_m"] == [0.0, 0.15] and fix["need_arm_dxdy_m"] == [0.0, 0.05]
