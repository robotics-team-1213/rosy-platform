#!/usr/bin/env python3
"""1/2/3-Tier Hybrid Stacking Stage & Plan Executor (`vla_handover_stages.py`).

Single Responsibility:
  - Executes a complete 1/2/3-tier hybrid stacking stage (`run_hybrid_stack_stage`) combining
    `cell_area_xyz.execute_directive` hover staging, `compute_stud_release_residual`, in-line
    SmolVLA steps, 3-stage `CellStackGuard` release evaluation, camera stack verification, and
    online IL/RL residual update (`cell_problem_pipeline.update_il_rl_from_run`).
  - Orchestrates multi-tier plans (`run_3tier_hybrid_plan`) with look-ahead prefetching.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from cell_control_core import compute_stud_release_residual, ensure_omx_paths

ensure_omx_paths()

from omx_adapter.area_xyz import TIER_Z_M  # noqa: E402
import cell_area_xyz  # noqa: E402
import cell_problem_pipeline as cpp  # noqa: E402
from cell_stack_guard import CellStackGuard, GateResult, StackGateConfig  # noqa: E402


def run_hybrid_stack_stage(
    broker,
    task,
    *,
    base_plan: dict[str, Any],
    work_dir: Path,
    act_fn: Callable[[str], dict[str, Any]],
    vla_step_fn: Callable[[Dict[str, Any]], Any],
    seating_probe_fn: Callable[[int], tuple[float, list[float]]],
    frame_fn: Optional[Callable[[str], Any]] = None,
    stack_guard: Optional[CellStackGuard] = None,
    vla_refinement_steps: int = 3,
    wrist_obs: Optional[dict[str, Any]] = None,
    read_grip_holding_fn: Optional[Callable[[], bool]] = None,
    read_z_fn: Optional[Callable[[], float]] = None,
    lift_step_fn: Optional[Callable[[float], None]] = None,
) -> dict[str, Any]:
    """Executes a complete 1/2/3-tier hybrid stacking stage with ReleaseCorrector residual & IL/RL update.

    The release gate needs injected real readbacks (`read_grip_holding_fn`, `read_z_fn`,
    `lift_step_fn`); without them the stage HOLDs and nothing is released. VLA joint outputs are
    proposals only (`vla_executed` is always False): they never reach `act_fn`, which carries the
    reviewed named chunks alone (D-854 keeps the execution path closed)."""
    from vla_handover_broker import HandoverState

    guard = stack_guard or CellStackGuard(StackGateConfig(tier=task.tier))
    broker.trigger_prefetch(task.target_slot, task.tier)
    dispatch_tel = broker.dispatch_task(task, base_plan=base_plan, work_dir=work_dir)
    if broker.current_state == HandoverState.FAILED or task.directive is None:
        return {"ok": False, "state": broker.current_state.value, "telemetry": dispatch_tel}
    if read_grip_holding_fn is None or read_z_fn is None or lift_step_fn is None:
        broker.current_state = HandoverState.HELD
        return {"ok": False, "state": broker.current_state.value,
                "held": "release gate needs injected grip and z readbacks; nothing was released",
                "telemetry": dispatch_tel, "vla_steps_proposed": 0, "vla_executed": False}

    hover_dir = dict(task.directive)
    hover_dir["execution"] = {**dict(hover_dir.get("execution") or {}), "stay_hover": True}
    before_side = frame_fn("side") if frame_fn is not None else None
    before_top = frame_fn("top") if frame_fn is not None else None

    macro_res = cell_area_xyz.execute_directive(
        hover_dir,
        base_plan=base_plan,
        work_dir=work_dir,
        act_fn=act_fn,
        frame_fn=frame_fn,
        max_attempts=2,
    )
    grasp_dyn = macro_res.get("grasp_dynamics") or {"holding": False, "regime": "unmeasured"}
    ready_tel = broker.signal_ready_reached(
        facts={
            "chunk": "above_place",
            "holding": bool(grasp_dyn.get("holding", False)),
            "grasp_stable": grasp_dyn.get("regime") not in ("slip_collapse", "unmeasured"),
        }
    )
    if broker.current_state != HandoverState.VLA_ACTIVE:
        return {"ok": False, "state": broker.current_state.value, "telemetry": ready_tel, "macro": macro_res}
    vla_actions: list[list[float]] = []
    gate_reports: list[GateResult] = []
    q_cur = [0.0, -10.0, 15.0, 45.0, 48.0, 54.4]
    z_box = [float(task.target_z_m or TIER_Z_M[task.tier])]
    pl_orig = list(task.directive["place"].get("effective_xyz_m") or [0.158, -0.013, z_box[0]])
    last_residual = {"dx_m": 0.0, "dy_m": 0.0, "dyaw_deg": 0.0}

    while True:
        last_residual = compute_stud_release_residual(
            wrist_obs or macro_res.get("wrist"),
            tier=task.tier,
            retry_count=broker.retry_count,
        )
        for step_i in range(max(1, vla_refinement_steps)):
            act_vec, _ = broker.step_vla_inference(
                vla_step_fn,
                {
                    "tier": task.tier,
                    "step": step_i,
                    "attempt": broker.retry_count,
                    "state": list(q_cur),
                    "release_residual": last_residual,
                },
                clamp_norm=True,
                current_state=q_cur,
            )
            q_cur = list(act_vec)
            vla_actions.append(act_vec)

        _, torque_hist = seating_probe_fn(broker.retry_count)
        try:
            measured_z = read_z_fn()
            measured_grip = read_grip_holding_fn()
            if measured_z is None or measured_grip is None or not math.isfinite(float(measured_z)):
                raise ValueError("missing grip or height readback")
            z_box[0] = float(measured_z)
        except Exception as error:
            broker.current_state = HandoverState.HELD
            return {"ok": False, "state": broker.current_state.value,
                    "held": f"release readback unavailable: {error}", "macro": macro_res,
                    "vla_steps_proposed": len(vla_actions), "vla_executed": False}

        def _eval_gate() -> bool:
            g_res = guard.evaluate_release(
                current_z_m=z_box[0],
                target_z_m=task.target_z_m,
                torque_history=torque_hist,
                read_grip_holding_fn=read_grip_holding_fn,
                read_z_fn=read_z_fn,
                lift_step_fn=lift_step_fn,
                tier=task.tier,
            )
            gate_reports.append(g_res)
            return g_res.passed

        seat_tel = broker.signal_seating_attempted(
            gate_eval_fn=_eval_gate,
            retry_fn=lambda: act_fn("goto above_place"),
        )
        if broker.current_state in (HandoverState.COMPLETED, HandoverState.FAILED):
            break

    if broker.current_state == HandoverState.COMPLETED:
        act_fn("run release_place")
        act_fn("park")

    after_side = frame_fn("side") if frame_fn is not None else None
    after_top = frame_fn("top") if frame_fn is not None else None
    cam_verify = (
        cell_area_xyz.verify_stack_outcome(
            before_side=before_side,
            after_side=after_side,
            before_top=before_top,
            after_top=after_top,
            pick=task.directive["pick"],
            place=task.directive["place"],
        )
        if frame_fn is not None
        else {"verified": broker.current_state == HandoverState.COMPLETED, "reason": "stack_guard_verified"}
    )

    recovered_place_xyz = [
        round(float(pl_orig[0]) + last_residual["dx_m"], 5),
        round(float(pl_orig[1]) + last_residual["dy_m"], 5),
        round(float(z_box[0]), 5),
    ]
    stage_ok = broker.current_state == HandoverState.COMPLETED and bool(cam_verify.get("verified", True))
    il_rl_update = cpp.update_il_rl_from_run(
        {"_work": work_dir, "arm_id": broker.arm_id},
        {
            "arm_id": broker.arm_id,
            "directive": task.directive,
            "pick": task.directive["pick"],
            "place": task.directive["place"],
            "recovered_place_xyz_m": (
                recovered_place_xyz if broker.retry_count > 0 or any(last_residual.values()) else None
            ),
            "result": "placed" if stage_ok else "stopped",
            "task_verified": stage_ok,
            "grasp_dynamics": grasp_dyn,
            "recovery": macro_res.get("recovery", []),
            "steps": list(macro_res.get("steps") or [])
            + ([{"command": "run release_place", "holding": False}] if stage_ok else []),
        },
    )
    return {
        "ok": stage_ok,
        "task_id": task.task_id,
        "tier": task.tier,
        "target_z_m": task.target_z_m,
        "state": broker.current_state.value,
        "retry_count": broker.retry_count,
        "vla_steps_proposed": len(vla_actions),
        "vla_executed": False,  # the VLA joint targets above never reached act_fn; only the named chunks did
        "release_residual": last_residual,
        "recovered_place_xyz_m": recovered_place_xyz,
        "gate_reports": [
            {"passed": g.passed, "stage_failed": g.stage_failed, "reason": g.reason} for g in gate_reports
        ],
        "verification": cam_verify,
        "il_rl_update": il_rl_update,
        "sim_precheck": dispatch_tel.sim_precheck,
        "telemetry": seat_tel,
    }


def run_3tier_hybrid_plan(
    broker,
    tasks: list,
    *,
    base_plan: dict[str, Any],
    work_dir: Path,
    act_fn: Callable[[str], dict[str, Any]],
    vla_step_fn: Callable[[Dict[str, Any]], Any],
    seating_probe_fn: Callable[[int, int], tuple[float, list[float]]],
    frame_fn: Optional[Callable[[str], Any]] = None,
    read_grip_holding_fn: Optional[Callable[[], bool]] = None,
    read_z_fn: Optional[Callable[[], float]] = None,
    lift_step_fn: Optional[Callable[[float], None]] = None,
) -> dict[str, Any]:
    """Executes a multi-tier (Tier 1 -> Tier 2 -> Tier 3) hybrid stacking plan with Look-Ahead Prefetching."""
    results = []
    for idx, task in enumerate(tasks):
        res = run_hybrid_stack_stage(
            broker,
            task,
            base_plan=base_plan,
            work_dir=work_dir,
            act_fn=act_fn,
            vla_step_fn=vla_step_fn,
            seating_probe_fn=lambda retry_i, _tier=task.tier: seating_probe_fn(_tier, retry_i),
            frame_fn=frame_fn,
            read_grip_holding_fn=read_grip_holding_fn,
            read_z_fn=read_z_fn,
            lift_step_fn=lift_step_fn,
        )
        results.append(res)
        if not res["ok"]:
            break
        if idx + 1 < len(tasks):
            nxt = tasks[idx + 1]
            broker.trigger_prefetch(nxt.target_slot, nxt.tier)

    return {
        "ok": bool(results) and all(r["ok"] for r in results),
        "tiers_completed": [r["tier"] for r in results if r["ok"]],
        "stages": results,
    }
