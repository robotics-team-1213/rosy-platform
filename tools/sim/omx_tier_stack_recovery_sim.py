#!/usr/bin/env python3
"""Simulation verification and expansion suite for OMX 1단/2단/3단 tier-stacking problem scenarios.

Reproduces and verifies the solutions to the four real-hardware problem classes in Simulation:
1. Per-arm finger polarity (`arm_s` dark flat fingers vs `arm_a`/`arm_b` white v2.1 curved fingers) and automatic
   calibration/profile persistence (`cell_arm_cal.py`, `arm-cal-<arm_id>.json`), including wrist-camera visual hazards
   (cyan pallet corners, cool-LED top-face highlights, and narrow 6 mm inter-column gaps).
2. Closed-loop wrist-camera `(x, y)` centering (`wrist_servo`) from initial +-6..8 mm approach offsets over 1단/2단/3단
   container stacks, paired with curved-fingertip jaw clearance (`58.2` on `arm_b` vs `54.7` on `arm_s`).
3. Unstable/skewed grasp detection via v2 multi-model deliberation (`cell_grasp_debate.py`, `schema_version = 2`),
   physical put-back (`reinsert_pick` / `release_pick`) into the stack slot, and re-centered retry (`reinsert_and_retry`).
4. Differentiated speed profile (fast horizontal transit `0.82` vs guarded vertical descent `0.30`/`0.26`) and
   `chunk_runner.py` `hold()` holding-state preservation when contact occurs while carrying a container.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import tempfile
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OMX_DIR = ROOT / "deploy/robot/omx"
ADAPTER_DIR = ROOT / "middleware/devices/omx/adapter"
SIM_DIR = Path(__file__).resolve().parent
for _p in (OMX_DIR, ADAPTER_DIR, SIM_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cell_arm_cal  # noqa: E402
import cell_fingers  # noqa: E402
import cell_grasp_debate as cgd  # noqa: E402
import cell_params as prm  # noqa: E402
import cell_problem_pipeline as cpp  # noqa: E402
from omx_tier_stack_recovery_helpers import (  # noqa: E402
    TIERS,
    render_synthetic_wrist_frame,
    simulate_descent_and_hold_preservation,
    simulate_grasp_debate_reinsert_and_retry,
    simulate_orientation_detection_and_reorient_recovery,
    simulate_wrist_centering_loop,
)


def replay_and_verify_problem_case(case: dict[str, Any], work_dir: Path) -> dict[str, Any]:
    """Reproduce a recorded `rosy.omx-problem-case.v1` ledger entry in simulation and verify its recovery."""
    rep = case.get("sim_reproducer") or {}
    arm_id = str(rep.get("arm_id") or case.get("arm_id") or "arm_b")
    tier = int(rep.get("tier") or case.get("tier") or 1)
    cat = str(rep.get("category") or case.get("category") or "wrist_offset_or_visual_hazard")
    init_off = float(rep.get("initial_offset_mm") or -6.4)
    if abs(init_off) < 2.0 and cat == "wrist_offset_or_visual_hazard":
        init_off = -6.4

    if cat == "orientation_mismatch_or_jaw_lag":
        res = simulate_orientation_detection_and_reorient_recovery()
        passed = bool(
            res["horizontal_detected_as_failure"]
            and res["horizontal_recovery_mode"] == "re_orient_and_re_place"
            and res["vertical_verified_after_reorient"]
            and res["vertical_orientation_class"] == "vertical_ns"
            and res["safe_diag_yaw_deg"] == -135.0
        )
        return {"case_id": case.get("case_id"), "category": cat, "arm_id": arm_id, "tier": tier, "verified": passed, "sim_result": res}
    if cat == "wrist_offset_or_visual_hazard":
        res = simulate_wrist_centering_loop(arm_id, initial_offset_mm=init_off, work_dir=work_dir)
        passed = bool(res["converged"] and abs(res["final_offset_mm"]) <= 1.5)
        return {"case_id": case.get("case_id"), "category": cat, "arm_id": arm_id, "tier": tier, "verified": passed, "sim_result": res}
    if cat in ("unstable_grasp_reinsert", "slip_during_lift"):
        res = simulate_grasp_debate_reinsert_and_retry(arm_id, tier=tier, work_dir=work_dir)
        passed = bool(res["attempt_1"]["verdict"] == "reinsert_and_retry" and res["attempt_2"]["verdict"] == "proceed")
        return {"case_id": case.get("case_id"), "category": cat, "arm_id": arm_id, "tier": tier, "verified": passed, "sim_result": res}
    if cat == "descent_or_park_contact":
        res = simulate_descent_and_hold_preservation()
        passed = bool(
            res["holding_preserved_on_descend_place_contact"]
            and res["holding_cleared_when_jaws_empty"]
            and res["infer_holding_overrides_uncalibrated_threshold"]
        )
        return {"case_id": case.get("case_id"), "category": cat, "arm_id": arm_id, "tier": tier, "verified": passed, "sim_result": res}
    # calibration_drift
    w_res = simulate_wrist_centering_loop(arm_id, initial_offset_mm=init_off if abs(init_off) >= 2.0 else 5.8, work_dir=work_dir)
    g_res = simulate_grasp_debate_reinsert_and_retry(arm_id, tier=tier, work_dir=work_dir)
    cal_after = cell_arm_cal.load(work_dir, arm_id)
    passed = bool(w_res["converged"] and g_res["attempt_2"]["verdict"] == "proceed" and cal_after.get("samples", 0) >= 1)
    return {
        "case_id": case.get("case_id"),
        "category": cat,
        "arm_id": arm_id,
        "tier": tier,
        "verified": passed,
        "sim_result": {"wrist": w_res, "grasp": g_res, "calibration_after": cal_after},
    }


def replay_and_verify_ledger(out_dir: Path) -> dict[str, Any]:
    """Seed canonical real-hardware problem cases into `problem-cases.jsonl`, replay all in simulation, and verify 100% pass."""
    cases = cpp.seed_real_hardware_problem_cases(out_dir)
    verifications = [replay_and_verify_problem_case(c, out_dir) for c in cases]
    passed = sum(1 for v in verifications if v["verified"])
    return {
        "schema": cpp.REPORT_SCHEMA,
        "ledger_path": str(cpp.ledger_path(out_dir)),
        "total_cases": len(verifications),
        "passed_cases": passed,
        "all_verified": passed == len(verifications) and len(verifications) > 0,
        "cases": verifications,
    }


def simulate_sim2real_jitter_z_and_dynamics(out_dir: Path) -> dict[str, Any]:
    """Verify multi-arm (`arm_s`, `arm_a`, `arm_b`) real-time jitter damping, 3D Z-axis search, and calculus grasp dynamics in parallel."""
    from concurrent.futures import ThreadPoolExecutor
    for _p in (OMX_DIR, ADAPTER_DIR, SIM_DIR):
        if str(_p) not in sys.path:
            sys.path.insert(0, str(_p))
    from omx_adapter.chunk_library import TemporalChunkEnsembler
    import cell_area_zones as caz
    import joint_jitter as jj
    import omx_real2sim_comp as r2s_comp

    def _verify_arm(arm_id: str) -> dict[str, Any]:
        # 1. Real-time rolling jitter window + active chunk damping + multi-sample settled_state
        osc = [
            {"t": k * 0.033, "chunk": "hold", "target": [0.0] * 6, "sent": [0.0] * 6,
             "present": [0.0, (-1) ** k * 1.2, (-1) ** k * 0.8, 0.0, 0.0, 48.0]}
            for k in range(36)
        ]
        win = jj.live_window(osc)
        ens = TemporalChunkEnsembler()
        cur = [0.0, 0.0, 0.0, 0.0, 0.0, 48.0]
        nxt = [0.0, 4.0, 2.0, 0.0, 0.0, 48.0]
        cmd_damped = jj.damp_step(ens, cur, nxt, [[0.0, 1.0, 0.5, 0.0, 0.0, 48.0], [0.0, 2.0, 1.0, 0.0, 0.0, 48.0]])
        # 2. 3D Z-axis pick recovery on area corresponding to arm
        area = {"arm_s": "pinky", "arm_a": "ship", "arm_b": "pallet"}[arm_id]
        z_nom = {"pinky": 0.008, "ship": 0.004, "pallet": 0.012}[area]
        directive = {
            "arm_id": arm_id,
            "pick": {"area": area, "col": 1, "tier": 1, "x": 0.165, "y": -0.145 if arm_id != "arm_b" else 0.02, "z": z_nom,
                     "effective_xyz_m": [0.165, -0.145 if arm_id != "arm_b" else 0.02, z_nom], "yaw_deg": -90.0},
            "execution": {},
        }
        rec = caz.diagnose_and_recover_pick(
            attempt=0, cur_directive=directive, r_desc={"ok": True},
            r_grasp={"ok": True, "state": [0, 0, 0, 0, 0, 49.5], "gripper_current_ma": 40.0},
            cal={"held_30mm": 54.0}, tried_xs=[],
        )
        dz_mm = round((rec["recovered_pick_xyz_m"][2] - z_nom) * 1000.0, 2)
        # 3. Calculus grasp dynamics (elastic settle vs slip collapse)
        r_g1 = {"ok": True, "holding": True, "gripper_current_ma": 155.0, "state": [0, 0, 0, 0, 48.0, 55.68]}
        r_l1 = {"ok": True, "holding": True, "gripper_current_ma": 132.0, "state": [0, 0, 0, 0, 48.0, 54.29]}
        r_a1 = {"ok": True, "holding": True, "gripper_current_ma": 128.0, "state": [0, 0, 0, 0, 48.0, 54.25]}
        dyn_ok = cell_arm_cal.evaluate_grasp_dynamics(r_g1, r_lift=r_l1, r_above_place=r_a1, closed=48.8, open_pos=57.85)
        r_g2 = {"ok": True, "holding": True, "gripper_current_ma": 144.0, "state": [0, 0, 0, 0, 48.0, 52.31]}
        r_l2 = {"ok": True, "holding": False, "gripper_current_ma": 88.0, "state": [0, 0, 0, 0, 48.0, 49.18]}
        dyn_slip = cell_arm_cal.evaluate_grasp_dynamics(r_g2, r_lift=r_l2, closed=48.8, open_pos=57.85)
        return {
            "arm_id": arm_id,
            "shaking_detected": bool(win["shaking"]),
            "damped_step_reduced": abs(cmd_damped[1] - cur[1]) < abs(nxt[1] - cur[1]),
            "z_search_dz_mm": dz_mm,
            "z_search_non_zero": dz_mm < 0.0,
            "dynamics_elastic_stable": bool(dyn_ok["holding"] and dyn_ok["regime"] == "elastic_settle"),
            "dynamics_slip_caught": bool(not dyn_slip["holding"] and dyn_slip["regime"] == "slip_collapse"),
        }

    with ThreadPoolExecutor(max_workers=3) as ex:
        arm_rows = list(ex.map(_verify_arm, ("arm_s", "arm_a", "arm_b")))

    # 4. Verify ServoCompensator closed-loop jitter damping, oscillation-settled gate, and 3D Z-sag compensation
    class _DummyModel:
        actuator_forcerange = np.tile([[0.0, 3.0]], (10, 1))
        dof_damping = np.full(10, 0.25)
        dof_frictionloss = np.full(10, 0.03)
        actuator_gainprm = np.tile([[12.0, 0.0, 0.0]], (10, 1))

    class _DummyWorld:
        model = _DummyModel()
        q = {"arm_a": np.arange(0, 6), "arm_b": np.arange(6, 12)}
        arm_dof = {"arm_a": np.arange(0, 6), "arm_b": np.arange(0, 6)}
        act = {"arm_a": np.arange(0, 6), "arm_b": np.arange(0, 6)}
        hold_dof = {"arm_a": [2, 3], "arm_b": [2, 3]}

        @staticmethod
        def tcp(_data, _arm):
            return np.array([0.14, -0.05, 0.012]), np.eye(3)

    class _DummyData:
        qpos = np.zeros(12)
        qvel = np.zeros(10)
        qfrc_bias = np.zeros(10)

    comp = r2s_comp.ServoCompensator(_DummyWorld(), fps=15)
    d = _DummyData()
    for k in range(10):
        d.qpos[1] = (-1) ** k * 0.009
        d.qvel[1] = (-1) ** k * 0.12
        comp.apply(d, {"arm_a": np.zeros(6)})
    jit = comp.jitter_state("arm_a")
    not_settled_while_shaking = not comp.is_settled("arm_a", q_err=0.002, q_vel=0.0, tcp_ok=True)
    z_comp_pos = comp.compensate_z_target(d, "arm_a", np.array([0.14, -0.05, 0.020]))
    all_ok = (
        all(r["shaking_detected"] and r["damped_step_reduced"] and r["z_search_non_zero"]
            and r["dynamics_elastic_stable"] and r["dynamics_slip_caught"] for r in arm_rows)
        and jit["shaking"]
        and comp.damped_frames["arm_a"] >= 1
        and not_settled_while_shaking
        and float(z_comp_pos[2]) > 0.020
    )
    return {
        "all_ok": bool(all_ok),
        "arms": arm_rows,
        "servo_compensator": {
            "jitter_state": jit,
            "damped_frames": comp.damped_frames["arm_a"],
            "not_settled_while_shaking": not_settled_while_shaking,
            "z_compensated_m": round(float(z_comp_pos[2]), 5),
        },
    }


def run_full_problem_recovery_simulation(out_dir: Path) -> dict[str, Any]:
    """Run all tier (1단/2단/3단) and multi-arm (`arm_s`, `arm_a`, `arm_b`) problem-recovery simulations."""
    out_dir.mkdir(parents=True, exist_ok=True)
    wrist_results = []
    debate_results = []
    for arm_id, init_off in (("arm_s", 6.2), ("arm_a", -5.8), ("arm_b", -6.6)):
        wrist_results.append(simulate_wrist_centering_loop(arm_id, initial_offset_mm=init_off, work_dir=out_dir))
    def _sim_seat(name: str):
        def _fn(prompt: str, images=()):
            if '"status": "edge_pinch"' in prompt or '"along_mm": -6.' in prompt or '"along_mm": -5.' in prompt:
                return {"action": "reinsert_and_retry", "dx_mm": 6.4, "dy_mm": 0.0, "reason": f"{name}: put back and re-center"}
            return {"action": "proceed", "dx_mm": 0.0, "dy_mm": 0.0, "reason": f"{name}: centered and stable"}
        _fn.__name__ = name
        return _fn

    for tier_spec in TIERS:
        tier = tier_spec["tier"]
        for arm_id in ("arm_s", "arm_b"):
            debate_results.append(
                simulate_grasp_debate_reinsert_and_retry(
                    arm_id=arm_id,
                    tier=tier,
                    work_dir=out_dir,
                    models=[_sim_seat("glm-5.1"), _sim_seat("qwen3-vl:8b")],
                )
            )
    descent_hold = simulate_descent_and_hold_preservation()
    ledger_replay = replay_and_verify_ledger(out_dir)
    sim2real_loop = simulate_sim2real_jitter_z_and_dynamics(out_dir)
    cal_files = {
        arm: cell_arm_cal.load(out_dir, arm)
        for arm in ("arm_s", "arm_a", "arm_b")
    }
    summary = {
        "schema": "rosy.omx-tier-stack-problem-recovery-sim.v1",
        "completed": (
            all(r["converged"] for r in wrist_results)
            and all(
                r["attempt_1"]["verdict"] == "reinsert_and_retry" and r["attempt_2"]["verdict"] == "proceed"
                for r in debate_results
            )
            and descent_hold["holding_preserved_on_descend_place_contact"]
            and descent_hold["holding_cleared_when_jaws_empty"]
            and descent_hold["infer_holding_overrides_uncalibrated_threshold"]
            and ledger_replay["all_verified"]
            and sim2real_loop["all_ok"]
        ),
        "tiers_verified": [t["tier"] for t in TIERS],
        "arms_verified": ["arm_s", "arm_a", "arm_b"],
        "wrist_centering": wrist_results,
        "grasp_debate_reinsert_recovery": debate_results,
        "descent_and_hold_preservation": descent_hold,
        "problem_ledger_replay": ledger_replay,
        "sim2real_jitter_z_and_dynamics": sim2real_loop,
        "persisted_arm_calibrations": cal_files,
    }
    (out_dir / "problem-recovery-sim-report.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=Path(tempfile.gettempdir()) / "omx-tier-recovery-sim")
    args = ap.parse_args(argv)
    res = run_full_problem_recovery_simulation(args.out)
    print(json.dumps(res, indent=2))
    return 0 if res["completed"] else 1


__all__ = [
    "ADAPTER_DIR",
    "OMX_DIR",
    "ROOT",
    "SIM_DIR",
    "TIERS",
    "main",
    "render_synthetic_wrist_frame",
    "replay_and_verify_ledger",
    "replay_and_verify_problem_case",
    "run_full_problem_recovery_simulation",
    "simulate_descent_and_hold_preservation",
    "simulate_grasp_debate_reinsert_and_retry",
    "simulate_orientation_detection_and_reorient_recovery",
    "simulate_sim2real_jitter_z_and_dynamics",
    "simulate_wrist_centering_loop",
]


if __name__ == "__main__":
    raise SystemExit(main())
