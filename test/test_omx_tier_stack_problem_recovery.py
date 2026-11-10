"""Tests for the OMX 1단/2단/3단 tier-stacking problem-recovery simulation suite."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "tools/sim", ROOT / "deploy/robot/omx", ROOT / "middleware/devices/omx/adapter"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import judge_seat  # noqa: E402
import omx_tier_stack_recovery_sim as rsim  # noqa: E402


def test_wrist_centering_converges_for_dark_and_white_fingers_with_hazards(tmp_path: Path):
    for arm_id, expected_color, init_mm in (("arm_s", "dark", 6.2), ("arm_a", "white", -5.8), ("arm_b", "white", -6.6)):
        res = rsim.simulate_wrist_centering_loop(arm_id, initial_offset_mm=init_mm, work_dir=tmp_path)
        assert res["finger_color"] == expected_color
        assert res["converged"] is True
        assert abs(res["final_offset_mm"]) <= 1.5
        assert (tmp_path / f"arm-cal-{arm_id}.json").exists()


def test_grasp_debate_reinsert_recovery_and_auto_calibration_across_all_three_tiers(tmp_path: Path):
    res = rsim.run_full_problem_recovery_simulation(tmp_path)
    assert res["completed"] is True
    assert res["tiers_verified"] == [1, 2, 3]
    assert res["arms_verified"] == ["arm_s", "arm_a", "arm_b"]
    for row in res["grasp_debate_reinsert_recovery"]:
        assert row["schema_version"] == 2
        assert row["attempt_1"]["verdict"] == "reinsert_and_retry"
        assert row["attempt_1"]["recovery_chunk"] == "run reinsert_pick"
        assert row["attempt_2"]["verdict"] == "proceed"
        assert row["calibration_after"]["samples"] >= 1


def test_judge_seat_from_config_accepts_shorthand_string_specs():
    fn_glm = judge_seat.from_config("glm-5.1")
    fn_ollama = judge_seat.from_config("ollama:qwen3-vl:8b")
    fn_panel = judge_seat.from_config(["glm-5.1", "ollama:qwen3-vl:8b"])
    assert callable(fn_glm)
    assert callable(fn_ollama)
    assert callable(fn_panel)
