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
    compile_rail_and_belt_safe_standby_waypoints,
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


from cell_sim_real_outer import load_r2s_snapshot_context  # noqa: E402, F401


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

        standby_returns = {
            "arm_s": compile_rail_and_belt_safe_standby_waypoints([0.0, 2.0, -8.0, 52.0, -5.0, 58.1]),
            "arm_a": compile_rail_and_belt_safe_standby_waypoints([12.0, -10.0, 12.0, 48.0, 0.0, 58.1]),
            "arm_b": compile_rail_and_belt_safe_standby_waypoints([-12.0, -10.0, 12.0, 48.0, 0.0, 58.1]),
        }
        self.board_state = {
            "pinky_supply_queue": [f"container-c3-{i + 1}" for i in range(int(containers_count))],
            "belt_slot": None,
            "stacked_tiers": [],
            "temp_plate_a": {1: None, 2: None, 3: None},
            "temp_plate_b": {1: None, 2: None, 3: None},
            "pallet_boards": {t: build_empty_pallet_board(tier=t) for t in (1, 2, 3)},
            "arms_at_standby": {"arm_s": True, "arm_a": True, "arm_b": True},
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
            "unstack_steps": unstack_steps, "standby_returns": standby_returns,
            "arms_at_standby": dict(self.board_state["arms_at_standby"]),
            "pinky_supply_ready": len(self.board_state["pinky_supply_queue"]),
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

    from cell_sim_real_outer import (
        fuse_r2s_sim_and_real_models,
        pretrain_task_with_r2s_sim_rl,
        run_outer_sim_retrain_and_hotswap,
        sim_rl_fallback_on_real_failure,
    )
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
        arm_s_return = compile_rail_and_belt_safe_standby_waypoints([0.0, 4.0, -10.0, 54.0, -5.0, 58.1])
        arm_ab_return = compile_rail_and_belt_safe_standby_waypoints(
            [12.0 if arm_ab == "arm_a" else -12.0, -12.0, 14.0, 48.0, 0.0, 58.1]
        )
        self.board_state["arms_at_standby"] = {"arm_s": True, "arm_a": True, "arm_b": True}
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
            "realignment": realignment_res, "sim_rl_fallback": sim_fallback_res,
            "standby_return": {"arm_s": arm_s_return, "arm_ab": arm_ab_return, "returned_to_standby": True},
            "place_error_mm": float(ab_stage["place_error_mm"]),
            "model_version_used": self.model_version, "verified": bool(realignment_res["passed"]) if realignment_res else True,
        }

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

    def run_pipelined_r2s_rl_unit(
        self, *, container_id: str, tier: int, wrist_img: Any = None, env_obs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run one zero-bottleneck unit transfer overlapping `arm_s` physical motion with live camera-to-R2S projection,
        parallel 4-policy speculative RL rollout, and `arm_ab` IK pre-staging."""
        from cell_r2s_parallel_rl import run_pipelined_parallel_unit_transfer

        return run_pipelined_parallel_unit_transfer(self, container_id=container_id, tier=tier, wrist_img=wrist_img, env_obs=env_obs)

    def run_complete_stack_return_and_recovery(self, **kwargs: Any) -> dict[str, Any]:
        """Execute full 1->2->3 tier stacking + standby return + 7-Situation/displaced recovery + 3->2->1 teardown to Pinky."""
        from cell_r2s_parallel_rl import run_complete_stack_return_and_recovery_scenario

        return run_complete_stack_return_and_recovery_scenario(self, **kwargs)


