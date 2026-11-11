"""Tests for the OMX 1단/2단/3단 tier-stacking problem-recovery simulation suite."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "tools/sim", ROOT / "deploy/robot/omx", ROOT / "middleware/devices/omx/adapter"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cell_problem_pipeline as cpp  # noqa: E402
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


def test_real_problem_ledger_capture_and_sim_replay_verification_pipeline(tmp_path: Path):
    cfg = {"_work": tmp_path, "arm_id": "arm_b"}
    captured = cpp.capture_from_attempt(
        cfg,
        {
            "from": "pallet-l1",
            "dest": "pallet-l2",
            "result": "reinserted",
            "fail_stage": "run lift_pick",
            "why": "skewed grasp reinserted",
            "grasp_debate": {"verdict": "reinsert_and_retry", "dx_mm": 6.1, "dy_mm": 0.0},
            "wrist": {"along_mm": -6.1, "across_mm": 0.2, "finger_color": "white"},
        },
    )
    assert captured is not None
    assert captured["category"] == "unstable_grasp_reinsert"
    assert (tmp_path / "problem-cases.jsonl").exists()

    report = rsim.replay_and_verify_ledger(tmp_path)
    assert report["all_verified"] is True
    assert report["total_cases"] >= 5
    assert report["passed_cases"] == report["total_cases"]


def test_online_imitation_and_reinforcement_learning_residual_policy_loop(tmp_path: Path):
    cfg = {"_work": tmp_path, "arm_id": "arm_b"}
    # Episode 1: empty grasp at (0.1100, -0.0250, 0.0085), recovery refined to (0.1130, -0.0240, 0.0055)
    ep1 = {
        "result": "empty",
        "task_verified": False,
        "pick": {"area": "pallet", "col": 1, "row": 1, "tier": 1, "x": 0.1100, "y": -0.0250, "z": 0.0085, "yaw_deg": -90.0},
        "place": {"area": "pallet", "col": 2, "row": 1, "tier": 2, "x": 0.1430, "y": -0.0200, "z": 0.0390, "yaw_deg": -90.0},
        "recovery": [{"recovered_pick_xyz_m": [0.1130, -0.0240, 0.0055]}],
        "steps": [{"command": "run grasp_pick", "holding": False}],
    }
    r1 = cpp.update_il_rl_from_run(cfg, ep1)
    assert r1["reward"] == -0.5
    assert r1["il_demos"] == 1
    assert r1["bucket"] == "pallet_left"
    assert r1["residual"]["dx_m"] > 0.0
    assert r1["residual"]["dz_m"] < 0.0

    # Episode 2: apply learned IL/RL residual to a new directive in pallet_left, then succeed!
    directive = {
        "directive_id": "next-ep-col1",
        "pick": {"area": "pallet", "col": 1, "row": 1, "tier": 1, "x": 0.1100, "y": -0.0250, "z": 0.0085, "yaw_deg": -90.0},
        "place": {"area": "pallet", "col": 2, "row": 1, "tier": 2, "x": 0.1430, "y": -0.0200, "z": 0.0390, "yaw_deg": -90.0},
    }
    updated = cpp.apply_learned_il_rl_residual(cfg, directive)
    assert updated["pick"]["x"] > 0.1100
    assert updated["pick"]["z"] < 0.0085

    ep2 = {
        "result": "placed",
        "task_verified": True,
        "pick": updated["pick"],
        "place": updated["place"],
        "steps": [
            {"command": "run grasp_pick", "holding": True},
            {"command": "run release_place", "holding": False},
        ],
    }
    r2 = cpp.update_il_rl_from_run(cfg, ep2)
    assert r2["reward"] == 2.0
    assert r2["il_demos"] == 2
    assert r2["rl_episodes"] == 2


def test_cell_reach_multisample_jitter_averaging_and_feel_z_step_search(tmp_path: Path):
    import cell_feel
    import cell_reach

    class ShakyCell:
        def __init__(self):
            self.states = [
                {"ok": True, "state": [0.105, 0.0, 0.0, 0.0, 0.0, 55.0], "jitter": {"shaking": True}},
                {"ok": True, "state": [0.095, 0.0, 0.0, 0.0, 0.0, 55.0], "jitter": {"shaking": True}},
                {"ok": True, "state": [0.100, 0.0, 0.0, 0.0, 0.0, 55.0], "jitter": {"shaking": False}},
            ]

        def act(self, cmd):
            if cmd == "state":
                return self.states.pop(0)
            return {"ok": True}

    res = cell_reach.correct(
        ShakyCell(),
        (0.100, 0.0),
        lambda dx, dy: tmp_path / "r.json",
        fk=lambda s: (s[0], s[1]),
    )
    assert res["verdict"] == "pass"
    assert res["iterations"][0]["samples"] == 3
    assert res["iterations"][0]["error_mm"] == [0.0, 0.0]

    class FeelCell:
        def __init__(self):
            self.calls = []
            self.grasp_try = 0

        def act(self, cmd):
            self.calls.append(cmd)
            if cmd == "run grasp_pick":
                self.grasp_try += 1
                return {"ok": True, "holding": self.grasp_try >= 1, "state": [0, 0, 0, 0, 0, 52.3]}
            return {"ok": True, "state": [0, 0, 0, 0, 0, 55.0]}

    cfg = {
        "work_dir": str(tmp_path),
        "params": {"feel.enabled": 1, "feel.tries": 3, "feel.step_mm": 10.0, "feel.z_step_mm": 8.0, "reach.enabled": 0},
        "sites": {"ship": {"surface_z": -0.025}},
    }
    target = {"pick": {"site": "ship", "x": 0.17, "y": -0.15, "z": 0.008, "yaw_deg": 0.0}, "place": {"x": 0.14, "y": 0.12, "z": 0.02, "yaw_deg": 0.0}}
    planned_zs = []

    def write_lib(_c, pick, _place, path):
        planned_zs.append(pick["z"])
        path.write_text("{}")
        return path

    fc = FeelCell()
    hook = cell_feel.feel_hook(cfg, fc, target, write_lib)
    out = hook(fc.act)
    assert out["holding"] is True
    assert planned_zs == [0.0]  # 0.008 - 0.008 = 0.0 m Z-step tried first!



