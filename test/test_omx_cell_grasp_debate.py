"""cell_grasp_debate: multi-model consistency debate and post-grasp put-back (release_pick / reinsert_pick)."""
import json
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
ROOT = Path(__file__).resolve().parents[1]
OMX = ROOT / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
try:
    import cell_grasp_debate as cgd
    import grasp_planner as gp
finally:
    sys.path.remove(str(OMX))

PLAN = json.loads((OMX / "grasp-plan.example.json").read_text())


def test_planner_generates_release_pick_and_reinsert_pick_with_grip_release():
    plan = dict(PLAN, grip_open=56.58, grip_release=56.10, grip_closed=48.8)
    planner = gp.Planner(plan)
    lib = planner.library()
    assert "release_pick" in lib["chunks"] and "reinsert_pick" in lib["chunks"]
    rel = lib["chunks"]["release_pick"]
    reins = lib["chunks"]["reinsert_pick"]
    # release_pick starts closed at pick.z, opens to grip_release (56.10), and lifts to lifted
    assert rel[0][5] == pytest.approx(48.8, abs=0.2)
    assert rel[-1][5] == pytest.approx(56.10, abs=0.05)
    assert rel[-1][:5] == pytest.approx(lib["chunks"]["lift_pick"][-1][:5], abs=0.05)
    # reinsert_pick starts at lifted with grip_closed (48.8), lowers to pick.z, opens to 56.10, and lifts back up
    assert reins[0][:5] == pytest.approx(lib["chunks"]["lift_pick"][-1][:5], abs=0.05)
    assert reins[0][5] == pytest.approx(48.8, abs=0.05)
    assert reins[-1][:5] == pytest.approx(lib["chunks"]["lift_pick"][-1][:5], abs=0.05)
    assert reins[-1][5] == pytest.approx(56.10, abs=0.05)


def test_telemetry_judge_distinguishes_shallow_corner_pinch_stable_grasp_and_diagonal_wedge():
    params = {"gripper.held_30mm": 55.7, "grasp.shallow_tol_units": 1.2, "grasp.wedged_tol_units": 0.7}
    # Trial 4 shallow corner pinch (52.4 < 54.5)
    shallow = cgd.telemetry_judge([0, 0, 0, 0, 0, 52.4], True, params)
    assert shallow["verdict"] == "reinsert" and shallow["class"] == "unstable_shallow"
    # Trial 8 centered grasp (55.4 within 54.5..56.4)
    stable = cgd.telemetry_judge([0, 0, 0, 0, 0, 55.4], True, params)
    assert stable["verdict"] == "proceed" and stable["class"] == "stable"
    # Diagonal rim wedge (56.6 > 56.4)
    wedged = cgd.telemetry_judge([0, 0, 0, 0, 0, 56.6], True, params)
    assert wedged["verdict"] == "reinsert" and wedged["class"] == "unstable_wedged"


def test_multi_model_debate_enforces_safety_invariant_and_chooses_reinsert_pick():
    telemetry = {"verdict": "reinsert", "class": "unstable_shallow", "jaw_units": 52.4, "error_units": -3.3, "reason": "shallow"}
    vision = {"verdict": "reinsert", "class": "unstable_skewed", "found": True, "along_mm": -6.6, "dx_mm": 5.61, "dy_mm": 0.0, "reason": "skewed"}

    # Even if Critic mistakenly says 'proceed', safety invariant overrides to 'reinsert_and_retry', and Arbiter refines dx_mm
    def critic(prompt, images, schema):
        return {"verdict": "proceed", "dx_mm": 5.6, "dy_mm": 0.0, "reason": "critic tried proceed"}

    def arbiter(prompt, images, schema):
        return {"verdict": "reinsert_and_retry", "dx_mm": 5.8, "dy_mm": -0.2, "reason": "arbiter confirmed reinsert + shift"}

    out = cgd.debate_and_decide("run lift_pick", telemetry, vision, reinsert_count=0, max_reinsert=1, models=[critic, arbiter])
    assert out["verdict"] == "reinsert_and_retry"
    assert out["recovery_chunk"] == "run reinsert_pick"
    assert (out["dx_mm"], out["dy_mm"]) == (5.8, -0.2)
    assert len(out["debate"]) == 2 and out["debate"][0]["verdict"] == "reinsert_and_retry"


def test_hook_executes_reinsert_pick_replans_and_retries_on_unstable_lift(tmp_path):
    commands = []
    states = [
        [0, 0, 0, 0, 0, 52.4],  # first lift_pick is shallow (52.4)
        [0, 0, 0, 0, 0, 55.6],  # after reinsert_pick + replan, second lift_pick is stable (55.6)
    ]

    class FakeCell:
        def act(self, cmd):
            commands.append(cmd)
            st = states[-1] if len(commands) >= 4 else states[0]
            return {"ok": True, "holding": True, "state": st}

        def frame(self, cam):
            return None

    cfg = {
        "work_dir": str(tmp_path),
        "arm_id": "arm_b",
        "params": {"gripper.held_30mm": 55.7, "grasp.shallow_tol_units": 1.2, "grasp.wedged_tol_units": 0.7, "grasp.max_reinsert": 1},
        "wrist": {"camera": "wrist", "hsv_min": [0, 60, 120], "hsv_max": [179, 255, 255]},
    }
    target = {"pick": {"x": 0.1650, "y": -0.1020, "z": 0.0074, "yaw_deg": -90.0}, "place": {"x": 0.1280, "y": -0.0120, "z": 0.0398, "yaw_deg": -90.0}}
    chk = cgd.hook(cfg, FakeCell(), target, lambda c, pk, pl, p: p, 34.4)
    res = chk("run lift_pick", {"ok": True, "holding": True, "state": states[0]}, FakeCell().act)
    assert res["verdict"] == "reinsert_and_retry" and res["put_back_ok"] is True
    assert commands[0] == "run reinsert_pick"
    assert commands[1].startswith("load ") and commands[2:] == ["goto above_pick", "run descend_pick", "run grasp_pick", "run lift_pick"]
    assert target["pick"]["x"] != 0.1650
