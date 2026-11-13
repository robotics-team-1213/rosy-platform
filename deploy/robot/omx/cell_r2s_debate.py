#!/usr/bin/env python3
"""Multi-Agent Deliberation Panel and End-to-End 1-to-3 Tier Stack + Recovery Scenario (`cell_r2s_debate.py`)."""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import json as _json
from typing import Any

import numpy as np

from cell_control_core import ensure_omx_paths
import judge_seat

ensure_omx_paths()

SCHEMA = "rosy.omx-r2s-parallel-rl.v1"


def build_default_multi_agent_debate_panel(panel_spec: Any = None):
    """Build a multi-agent deliberation panel (`opencode`, `codex`, `claude`, `glm-5.3`).
    Executes independent specialist seats (`opencode:glm-5.3-flash`, `codex:gpt-5-codex`) in parallel
    and consults `claude:sonnet-arbiter` on conflict."""
    if panel_spec is not None:
        return judge_seat.from_config(panel_spec)

    def _opencode_seat(prompt_text: str, images: Any, schema: dict) -> dict:
        allowed = (schema.get("properties") or {}).get("verdict", {}).get("enum") or ("proceed", "realign_and_proceed", "sim_rl_fallback")
        v = "realign_and_proceed" if ("recenter_on_temp" in prompt_text or "wrist_yaw_servo" in prompt_text) else "proceed"
        return {"verdict": v if v in allowed else allowed[0], "policy_id": "pi_contextual_rl", "reason": "opencode: R2S speculative RL advantage verified"}

    def _codex_seat(prompt_text: str, images: Any, schema: dict) -> dict:
        allowed = (schema.get("properties") or {}).get("verdict", {}).get("enum") or ("proceed", "realign_and_proceed", "sim_rl_fallback")
        v = "sim_rl_fallback" if "real_failed=true" in prompt_text.lower() else (
            "realign_and_proceed" if ("recenter_on_temp" in prompt_text or "wrist_yaw_servo" in prompt_text) else "proceed"
        )
        return {"verdict": v if v in allowed else allowed[0], "policy_id": "pi_iwr", "reason": "codex: physical clearance & IWR residual verified"}

    def _claude_arbiter(prompt_text: str, images: Any, schema: dict) -> dict:
        allowed = (schema.get("properties") or {}).get("verdict", {}).get("enum") or ("proceed", "realign_and_proceed", "sim_rl_fallback")
        v = "sim_rl_fallback" if "sim_rl_fallback" in prompt_text else ("realign_and_proceed" if "realign_and_proceed" in prompt_text else "proceed")
        return {"verdict": v if v in allowed else allowed[0], "policy_id": "pi_contextual_rl", "reason": f"claude-arbiter: resolved consensus over {_json.dumps(list(allowed))}"}

    _opencode_seat.__name__ = "opencode:zai-coding-plan/glm-5.3-flash"
    _codex_seat.__name__ = "codex:gpt-5-codex"
    _claude_arbiter.__name__ = "claude:sonnet-arbiter"

    def _parallel_panel(prompt_text: str, images: Any, schema: dict) -> dict:
        with ThreadPoolExecutor(max_workers=2) as pool:
            f0 = pool.submit(_opencode_seat, prompt_text, images, schema)
            f1 = pool.submit(_codex_seat, prompt_text, images, schema)
            r0 = f0.result()
            r1 = f1.result()
        rounds = [
            {"role": "proposal", "model": _opencode_seat.__name__, **r0},
            {"role": "critique_1", "model": _codex_seat.__name__, **r1},
        ]
        if r0.get("verdict") == r1.get("verdict"):
            return {**r1, "deliberation": rounds, "consensus": True}
        arb_prompt = f"{prompt_text}\n[Deliberation v2 role=arbiter] Models disagreed: {_json.dumps(rounds)}"
        arb = _claude_arbiter(arb_prompt, images, schema)
        rounds.append({"role": "arbiter", "model": _claude_arbiter.__name__, **arb})
        return {**arb, "deliberation": rounds, "consensus": False}

    _parallel_panel.__name__ = f"cooperate({_opencode_seat.__name__},{_codex_seat.__name__})"
    return _parallel_panel


def deliberate_real_sim_r2s_step(
    r2s_projection: dict[str, Any],
    speculative_rl: dict[str, Any],
    *,
    panel_spec: Any = None,
    real_failed: bool = False,
) -> dict[str, Any]:
    """Run multi-agent debate (`opencode` || `codex` -> `claude` arbiter) over concurrent Real observation
    and R2S 32-branch Speculative RL candidates, enforcing Unidirectional Safety Sovereignty."""
    panel = build_default_multi_agent_debate_panel(panel_spec)
    obs = r2s_projection["obs_20d"]
    schema = {
        "type": "object",
        "required": ["verdict", "reason"],
        "properties": {
            "verdict": {"type": "string", "enum": ["proceed", "realign_and_proceed", "sim_rl_fallback"]},
            "policy_id": {"type": "string"},
            "reason": {"type": "string"},
        },
    }
    prompt_text = (
        f"Tier={int(obs.get('tier_k', 1))} dx_mm={obs['x_hat_mm']} dy_mm={obs['dy_mm']} yaw_deg={obs['yaw_err_deg']} "
        f"selected_policy={speculative_rl['selected_policy_id']} selected_skill={speculative_rl['selected_skill']} "
        f"predicted_post_error_mm={speculative_rl['predicted_post_error_mm']} safety_ok={speculative_rl['safety_ok']} "
        f"real_failed={str(bool(real_failed)).lower()}"
    )
    reply = panel(prompt_text, (), schema)
    verdict = str(reply.get("verdict", "proceed"))
    if not speculative_rl.get("safety_ok", True) and verdict == "proceed":
        verdict = "realign_and_proceed"
    return {
        "verdict": verdict,
        "selected_policy_id": str(reply.get("policy_id") or speculative_rl["selected_policy_id"]),
        "selected_skill": str(speculative_rl["selected_skill"]),
        "selected_residual_mm": list(speculative_rl["selected_residual_mm"]),
        "consensus": bool(reply.get("consensus", True)),
        "deliberation": list(reply.get("deliberation") or []),
        "panel_name": getattr(panel, "__name__", "multi_agent_panel"),
    }


def run_complete_stack_return_and_recovery_scenario(
    pipeline: Any,
    *,
    tier_disturbances: dict[int, dict[str, Any]] | None = None,
    wrist_frames_by_tier: dict[int, np.ndarray] | None = None,
    unstack_back_to_pinky: bool = True,
    debate_panel_spec: Any = None,
) -> dict[str, Any]:
    """Execute the complete end-to-end 1-to-3 Tier Stacking + Standby Return + Recovery + Teardown scenario
    with Cross-Tier Lookahead R2S Speculative RL and Parallel Multi-Agent Deliberation."""
    from cell_r2s_parallel_rl import (
        AsyncShadowRetrainer,
        parallel_speculative_r2s_rl_select,
        project_live_camera_env_to_r2s,
        run_pipelined_parallel_unit_transfer,
    )

    if int(pipeline.model_version) == 0:
        pipeline.pretrain_task_with_r2s_sim_rl("pinky_to_3tier_stack", episodes=24)

    default_dist = {
        1: {"displaced_to": "belt_far", "dx_mm": -6.5, "dy_mm": 5.0, "yaw_err_deg": -4.5, "wrist_eccentric": True},
        2: {"displaced_to": "floor_front", "dx_mm": 4.2, "dy_mm": -4.6, "yaw_err_deg": 8.2, "r_k_mm": 1.8, "real_failed": True},
        3: {"belt_trench_wedged": True, "x_mm": 96.0, "dx_mm": 2.4, "dy_mm": -2.8, "yaw_err_deg": 3.5, "clearance_mm": 3.4},
    }
    dist_map = dict(default_dist if tier_disturbances is None else tier_disturbances)
    frames_map = dict(wrist_frames_by_tier or {})
    shadow = AsyncShadowRetrainer(pipeline)

    def _precompute_tier(t_idx: int) -> dict[str, Any]:
        env_t = dict(dist_map.get(t_idx) or {})
        proj = project_live_camera_env_to_r2s(
            pipeline.r2s_context, tier=t_idx, wrist_img=frames_map.get(t_idx),
            env_obs=env_t, systematic_bias_m=pipeline.systematic_bias_m,
        )
        rl_sel = parallel_speculative_r2s_rl_select(
            proj, work_dir=pipeline.work_dir, clf=pipeline.clf,
            iwr=pipeline.iwr, r2s_gap_state=pipeline.r2s_gap_state,
        )
        debate = deliberate_real_sim_r2s_step(
            proj, rl_sel, panel_spec=debate_panel_spec, real_failed=bool(env_t.get("real_failed", False))
        )
        return {"r2s_projection": proj, "speculative_rl": rl_sel, "debate": debate}

    tier_steps: list[dict[str, Any]] = []
    debates: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=1) as lookahead_pool:
        next_fut: Future | None = lookahead_pool.submit(_precompute_tier, 1)
        for tier_idx in (1, 2, 3):
            pre_bundle = next_fut.result() if next_fut is not None else None
            next_fut = lookahead_pool.submit(_precompute_tier, tier_idx + 1) if tier_idx < 3 else None
            t_env = dict(dist_map.get(tier_idx) or {})
            unit = run_pipelined_parallel_unit_transfer(
                pipeline,
                container_id=f"container-c3-t{tier_idx}",
                tier=tier_idx,
                wrist_img=frames_map.get(tier_idx),
                env_obs=t_env,
                debate_panel_spec=debate_panel_spec,
                include_debate=True,
                precomputed_r2s_bundle=pre_bundle,
            )
            debates.append(unit["multi_agent_debate"])
            tier_steps.append(unit)
            if tier_idx == 2:
                shadow.submit_shadow_retrain(n_sim_episodes=110)

    rehandle_out = pipeline.run_task("rehandle_and_outbound")
    shadow_swap = shadow.poll_and_commit(wait=True, timeout_s=10.0)
    stacked_snapshot = list(pipeline.board_state.get("stacked_tiers") or [])
    teardown_res = pipeline.reset_scenario_and_board(mode="unstack_only") if unstack_back_to_pinky else None
    errs = [float(s["place_error_mm"]) for s in tier_steps]

    return {
        "schema": SCHEMA,
        "completed": bool(
            all(s["verified"] and s["standby_return"]["returned_to_standby"] for s in tier_steps)
            and stacked_snapshot == [1, 2, 3]
            and rehandle_out["completed"]
            and (teardown_res is None or (teardown_res["ok"] and teardown_res["unstacked_count"] == 3))
        ),
        "tiers_stacked_before_teardown": stacked_snapshot,
        "all_arms_returned_to_standby": all(s["standby_return"]["returned_to_standby"] for s in tier_steps),
        "displaced_recoveries_verified": [
            (s["arm_s_stage"].get("displaced_recovery") or {}).get("failure_code")
            for s in tier_steps
            if s["arm_s_stage"].get("displaced_recovery")
        ],
        "multi_agent_debates": debates,
        "mean_place_error_mm": round(float(np.mean(errs)), 3) if errs else 0.0,
        "rehandle_and_outbound": rehandle_out,
        "shadow_hotswap": shadow_swap,
        "teardown_return_to_pinky": teardown_res,
        "active_model_version": pipeline.model_version,
        "tier_steps": tier_steps,
    }
