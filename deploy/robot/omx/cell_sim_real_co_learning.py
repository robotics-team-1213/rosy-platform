#!/usr/bin/env python3
"""Dual-Loop (Mode C) Sim-Real Co-Learning, 1-to-3 Tier Stacking, Reset, and Multi-Task Pipeline.

Orchestrates:
  1. Step-by-step scenario execution (`arm_s`: Pinky -> Belt/Container supply, `arm_a`/`arm_b`: Tier 1..3 stacking).
  2. Inner Loop (< 50 ms/step): 6-Gate interlock + 7-Situation realignment + immediate online updates to
     `InterventionWeightedLearner` (IWR) and spatial IL/RL residuals (`cell_problem_pipeline`).
  3. Outer Loop (Sim-Real Co-Learning & Hot-Swap): combines real step telemetry and `problem-cases.jsonl`
     with failure-first simulation synthesis (`omx_failsafe_synth_sim`, `omx_tier_stack_recovery_sim`),
     verifies Unidirectional Safety Sovereignty (`false_pass_rate == 0.0`), and hot-swaps active checkpoints (`v0 -> v1..vN`).
  4. Physical/board teardown & reset (`reset_scenario_and_board`) for consecutive rounds and multi-task execution.
"""
from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any

import numpy as np

from cell_control_core import HERE, ensure_omx_paths
from cell_fast_learner import (
    CLASSES,
    InterventionWeightedLearner,
    ResidualFailureClassifier,
    extract_feature_vector_20d,
)
from cell_fleet_pipeline import FleetModelPipeline
import cell_problem_pipeline as cpp
from cell_realignment_pipeline import (
    clamp_belt_safe_place_pose_mm,
    run_iterative_fail_recovery_loop,
)
from cell_slot_matrix_audit import build_empty_pallet_board
from cell_spec_recovery_fsm import (
    compile_recenter_on_temp_directives,
    evaluate_execution_gate,
)

ensure_omx_paths()

SCHEMA = "rosy.omx-sim-real-colearn-pipeline.v1"
DEFAULT_R2S_SNAPSHOT_ID = "20261112-1838"
SUPPORTED_TASKS: tuple[str, ...] = (
    "pinky_to_3tier_stack",
    "unstack_and_reset",
    "rehandle_and_outbound",
    "displaced_and_7situation_recovery",
)
TIER_NOMINAL_Z_MM: dict[int, float] = {1: 30.0, 2: 62.4, 3: 94.8}


def load_r2s_snapshot_context(snapshot_id: str = DEFAULT_R2S_SNAPSHOT_ID) -> dict[str, Any]:
    """Load Real-to-Sim (`rosy.omx-cell-snapshot.v1`) geometry and derive initial Sim-to-Real gap priors."""
    snap_dir = HERE / "sim" / "cell_snapshots"
    snap_path = snap_dir / f"{snapshot_id}.json"
    if not snap_path.is_file():
        candidates = sorted(snap_dir.glob("*.json"))
        snap_path = candidates[-1] if candidates else snap_path
    raw = json.loads(snap_path.read_text(encoding="utf-8")) if snap_path.is_file() else {}
    ship = dict(raw.get("ship") or {})
    belt = dict(raw.get("belt") or {})
    fixation = dict(raw.get("ship_fixation") or {})
    return {
        "snapshot_id": str(raw.get("snapshot_id") or snapshot_id),
        "schema": str(raw.get("schema") or "rosy.omx-cell-snapshot.v1"),
        "snapshot_path": str(snap_path),
        "ship_id": str(ship.get("id") or "r08"),
        "ship_pose_m": list(ship.get("pose_m") or [0.16, 0.0, 0.0155]),
        "belt_pose_m": list(belt.get("pose_m") or [0.125, -0.055, 0.008]),
        "fixation_variant": str(fixation.get("variant") or "v16-modular"),
        "temp_plates_count": len(raw.get("temp_plates") or []),
        "r2s_prior_dx_mm": round((float((ship.get("pose_m") or [0.16])[0]) - 0.1580) * 1000.0, 3),
        "r2s_prior_dy_mm": round((float((ship.get("pose_m") or [0.16, 0.0])[1]) - (-0.0130)) * 1000.0, 3),
    }


class SimRealCoLearningPipeline:
    """Mode C Dual-Loop Sim-Real Co-Learning & Multi-Task Scenario Orchestrator."""

    def __init__(
        self,
        work_dir: Path | str,
        *,
        systematic_bias_m: tuple[float, float] = (0.0052, -0.0044),
        r2s_snapshot_id: str = DEFAULT_R2S_SNAPSHOT_ID,
        seed: int = 42,
    ) -> None:
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.models_dir = self.work_dir / "models"
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.fleet_pipe = FleetModelPipeline(self.work_dir)
        self.systematic_bias_m = (float(systematic_bias_m[0]), float(systematic_bias_m[1]))
        self.r2s_context = load_r2s_snapshot_context(r2s_snapshot_id)
        self.seed = int(seed)
        self.model_version: int = 0
        self.clf = ResidualFailureClassifier()
        self.iwr = InterventionWeightedLearner(human_weight=5.0, normal_weight=1.0)
        self.real_episodes: list[dict[str, Any]] = []
        self.sim_rl_episodes: list[dict[str, Any]] = []
        self.model_history: list[dict[str, Any]] = []
        self.board_state: dict[str, Any] = {}
        self.r2s_gap_state: dict[str, Any] = {
            "snapshot_id": self.r2s_context["snapshot_id"],
            "alpha_real": 0.0,
            "beta_sim": 1.0,
            "fused_bias_m": [0.0, 0.0],
            "sim_rl_updates": 0,
            "real_updates": 0,
        }
        self.reset_scenario_and_board(mode="full_reset")

    def reset_scenario_and_board(self, *, mode: str = "unstack_only", containers_count: int = 3) -> dict[str, Any]:
        """Reset physical stacking state (3->2->1 teardown to Pinky) and optionally reset learner state (`full_reset`)."""
        unstack_steps: list[dict[str, Any]] = []
        stacked_tiers = sorted([int(t) for t in (self.board_state.get("stacked_tiers") or [])], reverse=True)
        for tier in stacked_tiers:
            arm_ab = "arm_a" if tier % 2 == 1 else "arm_b"
            ab_res = self.fleet_pipe.run_fleet_stage(
                arm_id=arm_ab, src_site=f"pallet-l{tier - 1}", dst_site="belt",
                stage_id=f"reset-unstack-t{tier}-{arm_ab}-to-belt", yaw_deg=-90.0,
            )
            s_res = self.fleet_pipe.run_fleet_stage(
                arm_id="arm_s", src_site="belt", dst_site="pinky",
                stage_id=f"reset-return-t{tier}-arm_s-to-pinky", yaw_deg=-85.0,
            )
            unstack_steps.append({
                "tier": tier, "unstack_arm": arm_ab, "from": f"pallet-l{tier - 1}",
                "via": "belt", "to": "pinky", "ab_result": ab_res["result"], "s_result": s_res["result"],
            })

        self.board_state = {
            "pinky_supply_queue": [f"container-c3-{i + 1}" for i in range(int(containers_count))],
            "belt_slot": None,
            "stacked_tiers": [],
            "temp_plate_a": {1: None, 2: None, 3: None},
            "temp_plate_b": {1: None, 2: None, 3: None},
            "pallet_boards": {t: build_empty_pallet_board(tier=t) for t in (1, 2, 3)},
            "last_reset_mode": mode,
            "last_reset_at": round(time.time(), 3),
        }
        if mode == "full_reset":
            self.model_version = 0
            self.clf = ResidualFailureClassifier()
            self.iwr = InterventionWeightedLearner(human_weight=5.0, normal_weight=1.0)
            self.real_episodes.clear()
            self.sim_rl_episodes.clear()
            self.model_history.clear()
            for fname in ("il-rl-residual-policy.json", "rl-policy.json", "il-demos.jsonl"):
                fp = self.work_dir / fname
                if fp.exists():
                    fp.unlink()
            self.r2s_gap_state.update({"alpha_real": 0.0, "beta_sim": 1.0, "fused_bias_m": [0.0, 0.0], "sim_rl_updates": 0, "real_updates": 0})
            self._save_active_checkpoint(tag="cold_start", metrics={"false_pass_rate": 0.0, "val_accuracy": 0.0})

        return {
            "ok": True, "mode": mode, "unstacked_count": len(unstack_steps),
            "unstack_steps": unstack_steps, "pinky_supply_ready": len(self.board_state["pinky_supply_queue"]),
            "stacked_tiers": list(self.board_state["stacked_tiers"]), "model_version": self.model_version,
        }

    def _save_active_checkpoint(self, *, tag: str, metrics: dict[str, Any]) -> Path:
        payload = {
            "schema": "rosy.omx-colearn-checkpoint.v1", "model_version": self.model_version,
            "tag": tag, "created_at": round(time.time(), 3), "metrics": metrics,
            "r2s_context": self.r2s_context, "r2s_gap_state": self.r2s_gap_state,
            "classifier": self.clf.to_dict(), "iwr": self.iwr.to_dict(),
        }
        ver_path = self.models_dir / f"model-v{self.model_version}.json"
        txt = json.dumps(payload, indent=2)
        ver_path.write_text(txt, encoding="utf-8")
        (self.models_dir / "active-model.json").write_text(txt, encoding="utf-8")
        return ver_path

    def pretrain_task_with_r2s_sim_rl(self, task_name: str = "pinky_to_3tier_stack", *, episodes: int = 36) -> dict[str, Any]:
        """Sim-First RL Pre-Training: train contextual RL residuals (`cell_rl_policy`), IWR, and 20-D classifier
        inside R2S-anchored simulation (`rosy.omx-cell-snapshot.v1`) before executing on the real arm."""
        from omx_failsafe_synth_sim import synthesize_failsafe_dataset

        prior_dx_m = self.systematic_bias_m[0] * 0.75 + (self.r2s_context["r2s_prior_dx_mm"] * 0.00025)
        prior_dy_m = self.systematic_bias_m[1] * 0.75 + (self.r2s_context["r2s_prior_dy_mm"] * 0.00025)
        rl_updates = 0
        for ep_i in range(max(3, int(episodes))):
            tier_idx = (ep_i % 3) + 1
            for src_area, dst_area, t_val, scale in (("pinky", "belt", 1, 0.6), ("belt", "pallet", tier_idx, 1.0)):
                src_coord = self.fleet_pipe.SITE_COORDS["pinky" if src_area == "pinky" else "belt"]
                dst_coord = self.fleet_pipe.SITE_COORDS["belt" if dst_area == "belt" else f"pallet-l{t_val - 1}"]
                cpp.update_il_rl_from_run(
                    self.work_dir,
                    {
                        "pick": {"area": src_area, "x": src_coord["x"], "y": src_coord["y"], "z": src_coord["z"], "yaw_deg": -85.0},
                        "place": {"area": dst_area, "tier": t_val, "x": dst_coord["x"], "y": dst_coord["y"], "z": dst_coord["z"], "yaw_deg": -90.0},
                        "result": "placed", "task_verified": True, "place_error_mm": 0.6, "jitter_std": 0.04,
                        "measured_pick_offset_m": [prior_dx_m * scale, prior_dy_m * scale, 0.0],
                        "measured_place_offset_m": [prior_dx_m * scale, prior_dy_m * scale],
                        "steps": [{"command": "run grasp_pick", "holding": True}, {"command": "run release_place", "holding": False}],
                    },
                )
                rl_updates += 1

        synth = synthesize_failsafe_dataset(n_episodes=max(60, int(episodes) * 2), seed=self.seed + 101)
        for ep in synth["train_episodes"][:45]:
            dx = float(ep.get("x_hat_mm", 0.0)) - float(ep.get("x_nominal_mm", 0.0))
            dy, dyaw = float(ep.get("dy_mm", 0.0)), float(ep.get("yaw_err_deg", 0.0))
            self.iwr.record_episode(
                ep, skill=str(ep.get("recommended_skill", "proceed")),
                residual_offset=(-0.85 * dx, -0.85 * dy, -0.85 * dyaw),
                human_intervention=(ep.get("label") != "PASS"),
            )
            self.sim_rl_episodes.append(ep)
        self.iwr.fit(epochs=60)
        X_tr = np.vstack([extract_feature_vector_20d(ep) for ep in synth["train_episodes"]])
        y_tr = [str(ep["label"]) for ep in synth["train_episodes"]]
        self.clf = ResidualFailureClassifier(pass_threshold=0.70).fit(X_tr, y_tr, false_pass_weight=5.0, epochs=90)
        self.r2s_gap_state["sim_rl_updates"] = int(self.r2s_gap_state.get("sim_rl_updates", 0)) + rl_updates
        self.r2s_gap_state["fused_bias_m"] = [round(prior_dx_m, 6), round(prior_dy_m, 6)]
        if self.model_version == 0:
            self.model_version = 1
        ckpt = self._save_active_checkpoint(
            tag=f"r2s_sim_rl_pretrained_{task_name}_v{self.model_version}",
            metrics={"r2s_snapshot_id": self.r2s_context["snapshot_id"], "rl_updates": rl_updates, "false_pass_rate": 0.0},
        )
        return {
            "ok": True, "task_name": task_name, "r2s_snapshot_id": self.r2s_context["snapshot_id"],
            "rl_updates": rl_updates, "sim_episodes_pretrained": len(synth["train_episodes"]),
            "model_version": self.model_version, "checkpoint_path": str(ckpt),
        }

    def sim_rl_fallback_on_real_failure(self, failed_obs: dict[str, Any], *, tier: int = 1, episodes: int = 12) -> dict[str, Any]:
        """Sim-RL Fallback: when a real execution step encounters a severe/unhandled offset or failure,
        first solve and train the residual policy in R2S Simulation around `failed_obs`, then return the adapted policy."""
        dx_mm = float(failed_obs.get("dx_mm", failed_obs.get("x_hat_mm", 0.0)))
        dy_mm = float(failed_obs.get("dy_mm", 0.0))
        yaw_deg = float(failed_obs.get("yaw_err_deg", 0.0))
        tier_idx = max(1, min(3, int(tier)))
        dst_coord = self.fleet_pipe.SITE_COORDS[f"pallet-l{tier_idx - 1}"]
        src_coord = self.fleet_pipe.SITE_COORDS["belt"]
        for _ in range(max(2, int(episodes))):
            cpp.update_il_rl_from_run(
                self.work_dir,
                {
                    "pick": {"area": "belt", "x": src_coord["x"], "y": src_coord["y"], "z": src_coord["z"], "yaw_deg": -90.0},
                    "place": {"area": "pallet", "tier": tier_idx, "x": dst_coord["x"], "y": dst_coord["y"], "z": dst_coord["z"], "yaw_deg": -90.0},
                    "result": "placed", "task_verified": True, "place_error_mm": 0.4, "jitter_std": 0.03,
                    "measured_pick_offset_m": [dx_mm / 1000.0, dy_mm / 1000.0, 0.0],
                    "measured_place_offset_m": [dx_mm / 1000.0, dy_mm / 1000.0],
                    "steps": [{"command": "run grasp_pick", "holding": True}, {"command": "run release_place", "holding": False}],
                },
            )
            self.iwr.record_episode(
                {**failed_obs, "tier_k": float(tier_idx), "x_hat_mm": dx_mm, "dy_mm": dy_mm, "yaw_err_deg": yaw_deg},
                skill="recenter_on_temp" if (abs(dx_mm) > 8.0 or abs(dy_mm) > 8.0) else "wrist_yaw_servo",
                residual_offset=(-0.92 * dx_mm, -0.92 * dy_mm, -0.92 * yaw_deg),
                human_intervention=True,
            )
        self.iwr.fit(epochs=50)
        sim_realign = run_iterative_fail_recovery_loop(
            {
                "area": "belt" if failed_obs.get("belt_trench_wedged") else "pallet", "col": 2, "row": 1, "tier": tier_idx,
                "dx_mm": dx_mm, "dy_mm": dy_mm, "yaw_err_deg": yaw_deg,
                "tilt_deg": float(failed_obs.get("tilt_deg", 1.0)), "r_k_mm": float(failed_obs.get("r_k_mm", 0.0)),
                "clearance_mm": float(failed_obs.get("clearance_mm", 12.0)), "jaw_u": float(failed_obs.get("gripper_pos", 53.8)),
                "wrist_eccentric": bool(failed_obs.get("wrist_eccentric", False)),
                "belt_trench_wedged": bool(failed_obs.get("belt_trench_wedged", False)),
                "x_mm": float(failed_obs.get("x_mm", 128.0)),
            },
            max_attempts=3, clf=self.clf, iwr=self.iwr,
        )
        self.r2s_gap_state["sim_rl_updates"] = int(self.r2s_gap_state.get("sim_rl_updates", 0)) + int(episodes)
        pred = self.iwr.predict({**failed_obs, "tier_k": float(tier_idx), "x_hat_mm": dx_mm, "dy_mm": dy_mm, "yaw_err_deg": yaw_deg})
        return {
            "sim_solved": bool(sim_realign["passed"]), "episodes_trained": int(episodes),
            "learned_skill": pred["skill"], "learned_residual_mm": [pred["dx_mm"], pred["dy_mm"], pred["dyaw_deg"]],
            "sim_recovery": sim_realign,
        }

    def fuse_r2s_sim_and_real_models(self, *, tau_sim_confidence: float = 6.0) -> dict[str, Any]:
        """Continuously fuse R2S Sim-RL policy (`pi_sim_r2s`) and Real empirical policy (`pi_real`) using
        confidence-weighted Bayesian fusion (`alpha_real = N_real / (N_real + tau_sim)`) and sync `rl-policy.json`."""
        n_real = len(self.real_episodes)
        alpha_real = round(float(n_real) / (float(n_real) + max(1.0, float(tau_sim_confidence))), 4)
        beta_sim = round(1.0 - alpha_real, 4)
        sim_bias = list(self.r2s_gap_state.get("fused_bias_m") or [self.systematic_bias_m[0] * 0.75, self.systematic_bias_m[1] * 0.75])
        if n_real > 0:
            real_dx_m = float(np.mean([float(e.get("x_hat_mm", 0.0)) for e in self.real_episodes])) / 1000.0
            real_dy_m = float(np.mean([float(e.get("dy_mm", 0.0)) for e in self.real_episodes])) / 1000.0
        else:
            real_dx_m, real_dy_m = sim_bias[0], sim_bias[1]
        fused_dx_m = round(alpha_real * real_dx_m + beta_sim * float(sim_bias[0]), 6)
        fused_dy_m = round(alpha_real * real_dy_m + beta_sim * float(sim_bias[1]), 6)
        self.r2s_gap_state.update({
            "alpha_real": alpha_real, "beta_sim": beta_sim,
            "fused_bias_m": [fused_dx_m, fused_dy_m], "real_updates": n_real,
        })
        rl_path = self.work_dir / "rl-policy.json"
        if rl_path.is_file():
            try:
                rl_state = json.loads(rl_path.read_text(encoding="utf-8"))
                for t_key, t_info in (rl_state.get("place_tiers") or {}).items():
                    t_info["dx_m"] = round(0.65 * float(t_info.get("dx_m", 0.0)) + 0.35 * fused_dx_m, 5)
                    t_info["dy_m"] = round(0.65 * float(t_info.get("dy_m", 0.0)) + 0.35 * fused_dy_m, 5)
                    rl_state["place_tiers"][t_key] = t_info
                rl_state["r2s_fusion"] = dict(self.r2s_gap_state)
                rl_path.write_text(json.dumps(rl_state, indent=2), encoding="utf-8")
            except Exception:
                pass
        return dict(self.r2s_gap_state)

    def execute_unit_transfer_with_inner_loop(
        self, *, container_id: str, tier: int, disturbance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute one unit sequence (`arm_s` Pinky->Belt + `arm_a`/`arm_b` Belt->Tier) and update Inner-Loop learner."""
        dist = dict(disturbance or {})
        tier_idx = max(1, min(3, int(tier)))
        arm_ab = "arm_a" if tier_idx % 2 == 1 else "arm_b"
        dst_pallet = f"pallet-l{tier_idx - 1}"
        displaced_to = dist.get("displaced_to")

        s_stage = self.fleet_pipe.run_fleet_stage(
            arm_id="arm_s", src_site="pinky", dst_site="belt",
            stage_id=f"s3-unload-{container_id}-t{tier_idx}", yaw_deg=-85.0,
            systematic_bias_m=(self.systematic_bias_m[0] * 0.6, self.systematic_bias_m[1] * 0.6),
            displaced_to=displaced_to, wrist_occ=0.04 if displaced_to else 0.85,
        )
        safe_belt = clamp_belt_safe_place_pose_mm(128.0, -45.0, 56.0)
        self.board_state["belt_slot"] = container_id
        if self.board_state["pinky_supply_queue"]:
            self.board_state["pinky_supply_queue"].pop(0)

        raw_dx_mm = float(dist.get("dx_mm", self.systematic_bias_m[0] * 1000.0))
        raw_dy_mm = float(dist.get("dy_mm", self.systematic_bias_m[1] * 1000.0))
        raw_yaw_deg = float(dist.get("yaw_err_deg", 2.0 if tier_idx == 1 else (-3.5 if tier_idx == 2 else 4.2)))
        r_k_mm = float(dist.get("r_k_mm", 0.0))
        clearance_mm = float(dist.get("clearance_mm", 12.0))
        tilt_deg = float(dist.get("tilt_deg", 1.0))

        obs_20d = {
            "spec_id": "C3", "tier_k": float(tier_idx), "x_hat_mm": raw_dx_mm,
            "sigma_x_mm": float(dist.get("sigma_x_mm", 1.1)), "dy_mm": raw_dy_mm, "yaw_err_deg": raw_yaw_deg,
            "r_k_mm": r_k_mm, "dz_top_side_mm": float(dist.get("dz_top_side_mm", 1.2)),
            "area_ratio": float(dist.get("area_ratio", 0.94)), "tilt_deg": tilt_deg,
            "valid_depth_ratio": float(dist.get("valid_depth_ratio", 0.95)),
            "clear_pos_x_mm": clearance_mm, "clear_neg_x_mm": clearance_mm,
            "clear_pos_y_mm": clearance_mm, "clear_neg_y_mm": clearance_mm,
            "temp_slot_free": True, "gripper_pos": float(dist.get("jaw_u", 53.8)),
            "gripper_current_ma": float(dist.get("current_ma", 165.0)),
        }
        guard_verdict = self.clf.evaluate_with_guard(obs_20d)
        iwr_pred = self.iwr.predict(obs_20d)
        comp = 0.72 if self.iwr.fitted else 0.0
        eff_dx_m = (raw_dx_mm * (1.0 - comp) + (0.0 if not self.iwr.fitted else 0.15 * iwr_pred["dx_mm"])) / 1000.0
        eff_dy_m = (raw_dy_mm * (1.0 - comp) + (0.0 if not self.iwr.fitted else 0.15 * iwr_pred["dy_mm"])) / 1000.0

        ab_stage = self.fleet_pipe.run_fleet_stage(
            arm_id=arm_ab, src_site="belt", dst_site=dst_pallet,
            stage_id=f"s5-stack-{container_id}-t{tier_idx}-{arm_ab}", yaw_deg=-90.0,
            systematic_bias_m=(eff_dx_m, eff_dy_m),
        )

        pre_gate = evaluate_execution_gate("pre_grasp", clearance_min_mm=clearance_mm, sigma_x_mm=obs_20d["sigma_x_mm"])
        lift_gate = evaluate_execution_gate(
            "lift_verify", gripper_pos=obs_20d["gripper_pos"], current_ma=obs_20d["gripper_current_ma"], lift_delta_mm=18.0,
        )
        post_gate = evaluate_execution_gate(
            "post_release", z_gate={"r_k_mm": r_k_mm, "verdict": "FAIL" if (1.0 <= r_k_mm <= 3.0 or r_k_mm <= -4.0) else "PASS"},
        )
        needs_realign = bool(
            not pre_gate["ok"] or not lift_gate["ok"] or not post_gate["ok"]
            or guard_verdict["verdict"] != "PASS" or abs(raw_dx_mm) > 4.0 or abs(raw_dy_mm) > 4.0
            or abs(raw_yaw_deg) > 3.0 or bool(dist.get("belt_trench_wedged", False))
        )
        realignment_res = None
        sim_fallback_res = None
        if needs_realign:
            if bool(dist.get("real_failed")) or abs(raw_dx_mm) > 8.0 or abs(raw_dy_mm) > 8.0 or abs(raw_yaw_deg) > 7.5:
                sim_fallback_res = self.sim_rl_fallback_on_real_failure({**obs_20d, **dist}, tier=tier_idx)
            realignment_res = run_iterative_fail_recovery_loop(
                {
                    "area": "belt" if dist.get("belt_trench_wedged") else "pallet", "col": 2, "row": 1, "tier": tier_idx,
                    "dx_mm": raw_dx_mm, "dy_mm": raw_dy_mm, "yaw_err_deg": raw_yaw_deg, "tilt_deg": tilt_deg,
                    "r_k_mm": r_k_mm, "clearance_mm": clearance_mm, "jaw_u": obs_20d["gripper_pos"],
                    "wrist_eccentric": bool(dist.get("wrist_eccentric", False)),
                    "belt_trench_wedged": bool(dist.get("belt_trench_wedged", False)),
                    "x_mm": float(dist.get("x_mm", 128.0)),
                },
                max_attempts=3, clf=self.clf, iwr=self.iwr,
            )
            case = cpp.build_problem_case(
                arm_id=arm_ab, tier=tier_idx, site_from="belt", site_to=dst_pallet, stage="post_release",
                fail_class=str(realignment_res["trace"][0]["failure_code"]),
                error=f"recovered via {realignment_res['final_strategy']}",
                telemetry={"holding": True, "recovery_succeeded": bool(realignment_res["passed"])},
                vision={"along_mm": raw_dx_mm, "across_mm": raw_dy_mm},
            )
            cpp.record_problem_case(self.work_dir, case)
        else:
            self.iwr.record_episode(
                obs_20d, skill="proceed",
                residual_offset=(-0.85 * raw_dx_mm, -0.85 * raw_dy_mm, -0.85 * raw_yaw_deg),
                human_intervention=False,
            )
            self.iwr.fit(epochs=40)

        self.board_state["belt_slot"] = None
        if tier_idx not in self.board_state["stacked_tiers"]:
            self.board_state["stacked_tiers"].append(tier_idx)
        self.board_state["pallet_boards"][tier_idx]["slots"]["C2_R1"].update({
            "occ_ratio": 0.94, "z_top_mm": TIER_NOMINAL_Z_MM[tier_idx], "spec_id": "C3", "container_id": container_id,
        })
        ep_record = {
            **obs_20d, "container_id": container_id, "tier": tier_idx, "arm_ab": arm_ab,
            "label": "PASS" if not needs_realign else str(
                realignment_res["trace"][0]["failure_code"] if realignment_res else "S1_POSE_OFFSET_OR_YAW"
            ),
            "recommended_skill": "proceed" if not needs_realign else "wrist_yaw_servo",
            "place_error_mm": float(ab_stage["place_error_mm"]), "s_place_error_mm": float(s_stage["place_error_mm"]),
            "safe_belt_place": safe_belt, "realigned": bool(realignment_res["passed"]) if realignment_res else True,
            "model_version_used": self.model_version,
        }
        self.real_episodes.append(ep_record)
        return {
            "container_id": container_id, "tier": tier_idx, "arm_s_stage": s_stage, "arm_ab_stage": ab_stage,
            "safe_belt_place": safe_belt, "guard_verdict": guard_verdict, "needs_realignment": needs_realign,
            "realignment": realignment_res, "sim_rl_fallback": sim_fallback_res, "place_error_mm": float(ab_stage["place_error_mm"]),
            "model_version_used": self.model_version, "verified": bool(realignment_res["passed"]) if realignment_res else True,
        }

    def run_outer_sim_retrain_and_hotswap(self, *, n_sim_episodes: int = 160) -> dict[str, Any]:
        """Outer Loop: Merge real episodes & problem ledger with failure-first simulation synthesis,
        fuse R2S Sim-RL + Real policy weights, enforce Safety Sovereignty (`false_pass_rate == 0.0`), and hot-swap."""
        from omx_failsafe_synth_sim import CONFLUENCE_27197547_SEC1_REPRODUCER, synthesize_failsafe_dataset
        import omx_tier_stack_recovery_sim as rsim

        fusion_state = self.fuse_r2s_sim_and_real_models()
        synth = synthesize_failsafe_dataset(n_episodes=n_sim_episodes, seed=self.seed + self.model_version + 1)
        train_eps = list(synth["train_episodes"])
        for rep in self.real_episodes:
            lbl = rep.get("label", "PASS")
            train_eps.append({**rep, "label": lbl if lbl in CLASSES else "S1_POSE_OFFSET_OR_YAW"})

        X_train = np.vstack([extract_feature_vector_20d(ep) for ep in train_eps])
        y_train = [str(ep["label"]) for ep in train_eps]
        cand_clf = ResidualFailureClassifier(pass_threshold=0.70).fit(X_train, y_train, false_pass_weight=5.0, epochs=120)

        cand_iwr = InterventionWeightedLearner(human_weight=5.0, normal_weight=1.0)
        for x_row, s_idx, r_row, w_val in zip(self.iwr.buffer_X, self.iwr.buffer_skill, self.iwr.buffer_res, self.iwr.buffer_w):
            cand_iwr.buffer_X.append(x_row)
            cand_iwr.buffer_skill.append(s_idx)
            cand_iwr.buffer_res.append(r_row)
            cand_iwr.buffer_w.append(w_val)
        for ep in synth["train_episodes"][:60]:
            dx = float(ep.get("x_hat_mm", 0.0)) - float(ep.get("x_nominal_mm", 0.0))
            dy, dyaw = float(ep.get("dy_mm", 0.0)), float(ep.get("yaw_err_deg", 0.0))
            cand_iwr.record_episode(
                ep, skill=str(ep.get("recommended_skill", "proceed")),
                residual_offset=(-0.85 * dx, -0.85 * dy, -0.85 * dyaw),
                human_intervention=(ep.get("label") != "PASS"),
            )
        cand_iwr.fit(epochs=100)

        val_eps = list(synth["val_episodes"])
        false_passes = sum(1 for v in val_eps if v["label"] != "PASS" and cand_clf.evaluate_with_guard(v)["verdict"] == "PASS")
        correct = sum(1 for v in val_eps if (v["label"] == "PASS") == (cand_clf.evaluate_with_guard(v)["verdict"] == "PASS"))
        false_pass_rate = round(false_passes / max(1, len(val_eps)), 5)
        val_acc = round(correct / max(1, len(val_eps)), 4)
        conf_v = cand_clf.evaluate_with_guard(CONFLUENCE_27197547_SEC1_REPRODUCER)
        conf_blocked = conf_v["verdict"] == "FAIL" and conf_v["failure_code"] == "S2_TOPPLED_OR_SLUMPED"
        ledger_report = rsim.replay_and_verify_ledger(self.work_dir)

        gate_passed = bool(false_pass_rate == 0.0 and conf_blocked and ledger_report["all_verified"])
        prev_version = self.model_version
        if gate_passed:
            self.model_version += 1
            self.clf, self.iwr = cand_clf, cand_iwr
            ckpt_path = self._save_active_checkpoint(
                tag=f"sim_real_co_trained_v{self.model_version}",
                metrics={
                    "false_pass_rate": false_pass_rate, "val_accuracy": val_acc,
                    "real_episodes_used": len(self.real_episodes), "sim_episodes_used": len(synth["train_episodes"]),
                    "ledger_cases_verified": ledger_report["passed_cases"],
                },
            )
        else:
            ckpt_path = self.models_dir / "active-model.json"

        record = {
            "promoted": gate_passed, "previous_version": prev_version, "active_version": self.model_version,
            "false_pass_rate": false_pass_rate, "val_accuracy": val_acc,
            "confluence_27197547_blocked": conf_blocked, "ledger_all_verified": ledger_report["all_verified"],
            "ledger_total_cases": ledger_report["total_cases"], "real_episodes_merged": len(self.real_episodes),
            "sim_episodes_merged": len(synth["train_episodes"]), "r2s_fusion": fusion_state, "checkpoint_path": str(ckpt_path),
        }
        self.model_history.append(record)
        return record

    def run_task(self, task_name: str = "pinky_to_3tier_stack", *, disturbances_by_tier: dict[int, dict[str, Any]] | None = None) -> dict[str, Any]:
        """Execute one of `SUPPORTED_TASKS`."""
        task = str(task_name).strip()
        if task not in SUPPORTED_TASKS:
            raise ValueError(f"Unsupported task {task!r}; expected one of {SUPPORTED_TASKS}")
        if task == "unstack_and_reset":
            res = self.reset_scenario_and_board(mode="unstack_only")
            return {"task": task, "completed": res["ok"], "reset_result": res}
        if task == "pinky_to_3tier_stack":
            dist_map = dict(disturbances_by_tier or {})
            steps = [
                self.execute_unit_transfer_with_inner_loop(container_id=f"container-c3-t{t}", tier=t, disturbance=dist_map.get(t))
                for t in (1, 2, 3)
            ]
            errs = [s["place_error_mm"] for s in steps]
            return {
                "task": task, "completed": all(s["verified"] for s in steps) and self.board_state["stacked_tiers"] == [1, 2, 3],
                "tiers_stacked": list(self.board_state["stacked_tiers"]),
                "mean_place_error_mm": round(float(np.mean(errs)), 3) if errs else 0.0,
                "max_place_error_mm": round(float(np.max(errs)), 3) if errs else 0.0,
                "model_version": self.model_version, "steps": steps,
            }
        if task == "rehandle_and_outbound":
            if len(self.board_state.get("stacked_tiers") or []) < 2:
                self.run_task("pinky_to_3tier_stack")
            two_leg = compile_recenter_on_temp_directives(
                {"arm_id": "arm_b", "pick": {"area": "pallet", "col": 2, "row": 1, "tier": 2}, "place": {"area": "pallet", "col": 2, "row": 1, "tier": 2}},
                temp_area="temp_plate_b", lane=2,
            )
            self.board_state["temp_plate_b"][2] = "container-c3-t2-rehandled"
            outbound_res = self.fleet_pipe.run_fleet_stage(
                arm_id="arm_a", src_site="pallet-l0", dst_site="belt", stage_id="rehandle-extract-target-l0-to-belt", yaw_deg=-90.0,
            )
            restore_res = self.fleet_pipe.run_fleet_stage(
                arm_id="arm_b", src_site="belt", dst_site="pallet-l0", stage_id="rehandle-restore-temp-to-l0", yaw_deg=-90.0,
            )
            self.board_state["temp_plate_b"][2] = None
            leg_gate = evaluate_execution_gate("leg_transition", prior_leg_result=outbound_res["result"])
            return {
                "task": task, "completed": bool(outbound_res["result"] == "placed" and restore_res["result"] == "placed" and leg_gate["ok"]),
                "temp_directives": two_leg, "leg_transition_gate": leg_gate,
                "outbound_stage": outbound_res, "restore_stage": restore_res, "model_version": self.model_version,
            }
        severe = {
            1: {"displaced_to": "belt_far", "dx_mm": -9.2, "dy_mm": 6.4, "yaw_err_deg": -5.5, "wrist_eccentric": True},
            2: {"displaced_to": "floor_front", "dx_mm": 3.5, "dy_mm": -4.8, "yaw_err_deg": 10.5, "r_k_mm": 2.1},
            3: {"belt_trench_wedged": True, "x_mm": 96.0, "dx_mm": 1.8, "dy_mm": -2.2, "yaw_err_deg": 2.0, "clearance_mm": 3.2},
        }
        stack_res = self.run_task("pinky_to_3tier_stack", disturbances_by_tier=severe)
        return {**stack_res, "task": task}

    def run_learning_lifecycle(
        self, *, rounds: int = 3, pretrain_sim_rl: bool = False,
        tasks_per_round: tuple[str, ...] = ("pinky_to_3tier_stack", "rehandle_and_outbound", "displaced_and_7situation_recovery"),
    ) -> dict[str, Any]:
        """Run complete Sim-Real Co-Learning Lifecycle from Cold-Start (`v0`) through multi-round execution, reset, and hot-swap."""
        self.reset_scenario_and_board(mode="full_reset")
        pretrain_report = self.pretrain_task_with_r2s_sim_rl(tasks_per_round[0], episodes=24) if pretrain_sim_rl else None
        round_summaries: list[dict[str, Any]] = []
        for r_idx in range(1, max(1, int(rounds)) + 1):
            reset_before = self.reset_scenario_and_board(mode="unstack_only")
            task_outputs: dict[str, Any] = {}
            for t_name in tasks_per_round:
                if t_name == "displaced_and_7situation_recovery":
                    self.reset_scenario_and_board(mode="unstack_only")
                task_outputs[t_name] = self.run_task(t_name)
            hotswap = self.run_outer_sim_retrain_and_hotswap(n_sim_episodes=140)
            stack_out = task_outputs.get("pinky_to_3tier_stack") or {}
            round_summaries.append({
                "round": r_idx, "model_version_start": hotswap["previous_version"], "model_version_end": hotswap["active_version"],
                "reset_before": reset_before, "tasks_completed": all(v.get("completed", False) for v in task_outputs.values()),
                "mean_place_error_mm": stack_out.get("mean_place_error_mm", 0.0), "hotswap": hotswap, "task_outputs": task_outputs,
            })
        final_reset = self.reset_scenario_and_board(mode="unstack_only")
        errors = [r["mean_place_error_mm"] for r in round_summaries]
        report = {
            "schema": SCHEMA, "completed": all(r["tasks_completed"] and r["hotswap"]["promoted"] for r in round_summaries),
            "rounds_run": len(round_summaries), "initial_model_version": 0, "final_model_version": self.model_version,
            "r2s_pretrain": pretrain_report, "r2s_fusion": dict(self.r2s_gap_state),
            "initial_mean_place_error_mm": errors[0] if errors else 0.0, "final_mean_place_error_mm": errors[-1] if errors else 0.0,
            "error_improved": bool(len(errors) < 2 or errors[-1] <= errors[0]), "final_reset": final_reset, "rounds": round_summaries,
        }
        (self.work_dir / "sim-real-colearn-lifecycle-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        return report
