"""omx_grasp_probe's per-trial verdict: the block must rise with the gripper and rest back near its pick spot."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/sim"))
from omx_grasp_probe import LIFT_M, judge  # noqa: E402


def trial(lifted_z, rest_xy):
    return {"block_start_z": .015, "block_lifted_z": lifted_z, "block_start_xy": (0.0, .17), "block_rest_xy": rest_xy}


def test_a_block_that_rose_with_the_gripper_and_rested_back_passes():
    verdict = judge(trial(.015 + LIFT_M, (.0009, .17)))
    assert verdict["held"] and verdict["rested"]


def test_a_block_left_on_the_table_or_knocked_away_fails():
    assert not judge(trial(.015, (0.0, .17)))["held"]  # 2026-10-27 MuJoCo before finger pads
    assert not judge(trial(.015, (.032, .17)))["rested"]  # 2026-10-27 Isaac: fingers shoved the block
