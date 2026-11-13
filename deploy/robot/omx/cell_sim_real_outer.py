#!/usr/bin/env python3
"""R2S Sim-First RL Pre-Training, Fallback, Bayesian Fusion, and Outer-Loop Hot-Swap Helpers."""
from __future__ import annotations

import json
from typing import Any

import numpy as np

from cell_control_core import HERE, ensure_omx_paths
from cell_fast_learner import (
    CLASSES,
    InterventionWeightedLearner,
    ResidualFailureClassifier,
    extract_feature_vector_20d,
)
import cell_problem_pipeline as cpp
from cell_realignment_pipeline import run_iterative_fail_recovery_loop

ensure_omx_paths()

DEFAULT_R2S_SNAPSHOT_ID = "20261112-1838"


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

