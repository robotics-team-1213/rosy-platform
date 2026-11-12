#!/usr/bin/env python3
"""Decision <-> VLA Handover Broker State Machine & Precondition Sovereignty (`vla_handover_broker.py`).

Single Responsibility:
  - Manages low-latency state handover (`HandoverState`, `TaskDispatch`, `HandoverTelemetry`, `VlaHandoverBroker`)
    between ROSY Decision Seats (`judge_seat.measured`), Sim pre-flight (`sim_precheck_and_optimize_directive`),
    and in-line SmolVLA chunk ensembling (`TemporalChunkEnsembler`, `clamp_lerobot_norm_action`).
  - Multi-tier hybrid stacking stage and 3-tier plan execution live in `vla_handover_stages.py`
    and are exposed as methods on `VlaHandoverBroker`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import enum
from pathlib import Path
import time
from typing import Any, Callable, Dict, Optional

from cell_control_core import (  # noqa: F401  (re-exported)
    BODY_LIMIT,
    GRIPPER_LIMIT,
    GUARD_UNITS_PER_S,
    MAX_RELEASE_RESIDUAL_XY_M,
    MAX_RELEASE_RESIDUAL_YAW_DEG,
    clamp_lerobot_norm_action,
    compute_stud_release_residual,
    ensure_omx_paths,
)

ensure_omx_paths()

from omx_adapter.area_xyz import DIRECTIVE_SCHEMA, TIER_Z_M, build_directive  # noqa: E402
from omx_adapter.chunk_library import TemporalChunkEnsembler  # noqa: E402
import cell_area_xyz  # noqa: E402
from cell_fleet_pipeline import FleetModelPipeline  # noqa: E402,F401  (re-exported)
import cell_problem_pipeline as cpp  # noqa: E402
from cell_stack_guard import CellStackGuard, GateResult, StackGateConfig  # noqa: E402,F401  (re-exported)
import judge_seat  # noqa: E402
from vla_handover_stages import run_3tier_hybrid_plan, run_hybrid_stack_stage  # noqa: E402


class HandoverState(str, enum.Enum):
    IDLE = "IDLE"
    PREFETCHING = "PREFETCHING"
    MACRO_IK_TRANSIT = "MACRO_IK_TRANSIT"
    VLA_ACTIVE = "VLA_ACTIVE"
    STACK_VERIFYING = "STACK_VERIFYING"
    RETRY_TRIGGERED = "RETRY_TRIGGERED"
    PARKED = "PARKED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass
class TaskDispatch:
    task_id: str
    container_id: str
    target_slot: str
    tier: int
    vla_prompt: str
    target_z_m: Optional[float] = None
    ready_z_m: Optional[float] = None
    area: str = "pallet"
    col: int = 2
    row: int = 1
    directive: Optional[dict[str, Any]] = None
    created_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if self.target_z_m is None:
            self.target_z_m = float(TIER_Z_M.get(int(self.tier), TIER_Z_M[3]))
        if self.ready_z_m is None:
            self.ready_z_m = round(float(self.target_z_m) + 0.030, 4)


@dataclass
class HandoverTelemetry:
    state: HandoverState
    task_id: str
    current_tier: int
    vla_inference_lat_ms: float = 0.0
    action_vector: list[float] = field(default_factory=list)
    retry_count: int = 0
    decision_veto: Optional[dict[str, Any]] = None
    sim_precheck: Optional[dict[str, Any]] = None
    release_residual: Optional[dict[str, float]] = None
    message: str = ""


class VlaHandoverBroker:
    """Manages low-latency handover and prefetching between ROSY Decision Seats and SmolVLA."""

    def __init__(self, arm_id: str = "arm_a", max_retries: int = 3, ensemble_decay: float = 0.01):
        self.arm_id = arm_id
        self.max_retries = max_retries
        self.current_state = HandoverState.IDLE
        self.active_task: Optional[TaskDispatch] = None
        self.retry_count = 0
        self.last_telemetry: Optional[HandoverTelemetry] = None
        self.ensembler = TemporalChunkEnsembler(coeff=ensemble_decay, vmax=GUARD_UNITS_PER_S, fps=30)

    def build_area_xyz_directive(
        self,
        pick: dict[str, Any],
        place: dict[str, Any],
        *,
        directive_id: str = "vla-handover",
    ) -> dict[str, Any]:
        """Constructs a validated D-1014 `rosy.omx-cell-area-xyz-directive.v1` directive."""
        return build_directive(
            arm_id=self.arm_id,
            pick=pick,
            place=place,
            directive_id=directive_id,
        )

    def check_decision_precondition(self, facts: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Runs `judge_seat.measured(facts)` sovereign precondition check before/during handover."""
        norm_facts = dict(facts) if "box_found" not in facts or ("grasp_stable" in facts and "stable" not in facts) else facts
        if "box_found" not in norm_facts:
            norm_facts["box_found"] = True
        if "grasp_stable" in norm_facts and "stable" not in norm_facts:
            norm_facts["stable"] = norm_facts["grasp_stable"]
        forced, forbidden = judge_seat.measured(norm_facts)
        if forced == "park":
            self.current_state = HandoverState.PARKED
            return {"action": "park", "reason": "hardware fault veto", "forbidden": sorted(forbidden)}
        if forced == "abort":
            self.current_state = HandoverState.FAILED
            return {"action": "abort", "reason": "no box found / lost hold", "forbidden": sorted(forbidden)}
        if "proceed" in forbidden:
            action = "reinsert" if "reinsert" not in forbidden else "abort"
            self.current_state = (
                HandoverState.RETRY_TRIGGERED if action == "reinsert" else HandoverState.FAILED
            )
            return {
                "action": action,
                "reason": str(norm_facts.get("grasp_issue") or "proceed forbidden by measurement"),
                "forbidden": sorted(forbidden),
            }
        return None

    def dispatch_task(
        self,
        task: TaskDispatch,
        *,
        base_plan: Optional[dict[str, Any]] = None,
        work_dir: Optional[Path] = None,
    ) -> HandoverTelemetry:
        """Called by Decision Layer to issue a manipulation assignment with optional Sim precheck."""
        self.active_task = task
        self.retry_count = 0
        self.ensembler.reset()
        sim_res = None
        if task.directive and base_plan is not None:
            if task.directive.get("schema") == DIRECTIVE_SCHEMA:
                if work_dir is not None:
                    task.directive = cpp.apply_learned_il_rl_residual(work_dir, task.directive)
                sim_res = cell_area_xyz.sim_precheck_and_optimize_directive(
                    task.directive, base_plan, work_dir=work_dir
                )
                if not sim_res.get("ok", True):
                    self.current_state = HandoverState.FAILED
                    return self._emit_telemetry(
                        f"Task {task.task_id} rejected by Sim precheck: {sim_res.get('reason')}",
                        sim_precheck=sim_res,
                    )
                task.directive = sim_res["directive"]

        self.current_state = HandoverState.MACRO_IK_TRANSIT
        return self._emit_telemetry(
            f"Task {task.task_id} dispatched (tier={task.tier}, z={task.target_z_m:.4f}m): {task.vla_prompt}",
            sim_precheck=sim_res,
        )

    def trigger_prefetch(self, target_slot: str, tier: int) -> HandoverTelemetry:
        """Look-ahead: Move arm to Pre-stack Ready posture while upstream arm is unloading."""
        self.current_state = HandoverState.PREFETCHING
        z_m = TIER_Z_M.get(int(tier), TIER_Z_M[3])
        return self._emit_telemetry(
            f"Prefetching {self.arm_id} to slot {target_slot} tier {tier} (nominal_z={z_m:.4f}m) ready posture"
        )

    def signal_ready_reached(self, facts: Optional[dict[str, Any]] = None) -> HandoverTelemetry:
        """Called when Macro IK has brought the arm to the +30mm Ready position above target."""
        if not self.active_task:
            self.current_state = HandoverState.IDLE
            return self._emit_telemetry("No active task; aborted handover")

        if facts is not None:
            veto = self.check_decision_precondition(facts)
            if veto is not None:
                return self._emit_telemetry(
                    f"Decision precondition vetoed VLA handover: {veto['action']} ({veto['reason']})",
                    decision_veto=veto,
                )

        self.current_state = HandoverState.VLA_ACTIVE
        return self._emit_telemetry(f"Handover to SmolVLA: prompt='{self.active_task.vla_prompt}'")

    def step_vla_inference(
        self,
        vla_step_fn: Callable[[Dict[str, Any]], Any],
        observation: Dict[str, Any],
        *,
        clamp_norm: bool = False,
        current_state: Optional[list[float]] = None,
    ) -> tuple[list[float], HandoverTelemetry]:
        """Executes one in-line SmolVLA inference step (~2.3ms on RTX 5080), blending multi-step chunks via TemporalChunkEnsembler."""
        if self.current_state != HandoverState.VLA_ACTIVE:
            return [], self._emit_telemetry("VLA inference rejected: not in VLA_ACTIVE state")

        t0 = time.perf_counter()
        raw_out = vla_step_fn(observation)
        lat_ms = (time.perf_counter() - t0) * 1000.0

        if raw_out and isinstance(raw_out[0], (list, tuple)):
            self.ensembler.push([list(row) for row in raw_out])
            raw_action = self.ensembler.step(fallback=current_state)
        elif raw_out:
            self.ensembler.push([list(raw_out)])
            raw_action = self.ensembler.step(fallback=current_state)
        else:
            raw_action = self.ensembler.step(fallback=current_state) if self.ensembler._chunks else []

        action = (
            clamp_lerobot_norm_action(raw_action, current_state=current_state)
            if clamp_norm and len(raw_action) in (6, 7, 8)
            else list(raw_action)
        )
        tel = self._emit_telemetry("VLA Step", lat_ms=lat_ms, action=action)
        return action, tel

    def signal_seating_attempted(
        self,
        gate_eval_fn: Callable[[], bool],
        retry_fn: Optional[Callable[[], None]] = None,
    ) -> HandoverTelemetry:
        """Invoked when VLA reaches bottom seating; executes 3-Stage CellStackGuard."""
        self.current_state = HandoverState.STACK_VERIFYING
        passed = gate_eval_fn()

        if passed:
            self.current_state = HandoverState.COMPLETED
            return self._emit_telemetry(
                f"Task {self.active_task.task_id if self.active_task else ''} SUCCESS: Verified & Released"
            )

        self.retry_count += 1
        if self.retry_count <= self.max_retries:
            self.current_state = HandoverState.RETRY_TRIGGERED
            if retry_fn:
                retry_fn()
            self.current_state = HandoverState.VLA_ACTIVE
            return self._emit_telemetry(
                f"Gate failed; Reinsert & Retry attempt {self.retry_count}/{self.max_retries}"
            )

        self.current_state = HandoverState.FAILED
        return self._emit_telemetry(
            f"Retries exhausted ({self.max_retries}). Escalating to Decision Seat for Fallback"
        )

    def execute_hybrid_stack_stage(
        self,
        task: TaskDispatch,
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
    ) -> dict[str, Any]:
        """Executes a complete 1/2/3-tier hybrid stacking stage with ReleaseCorrector residual & IL/RL update."""
        return run_hybrid_stack_stage(
            self,
            task,
            base_plan=base_plan,
            work_dir=work_dir,
            act_fn=act_fn,
            vla_step_fn=vla_step_fn,
            seating_probe_fn=seating_probe_fn,
            frame_fn=frame_fn,
            stack_guard=stack_guard,
            vla_refinement_steps=vla_refinement_steps,
            wrist_obs=wrist_obs,
        )

    def execute_3tier_hybrid_plan(
        self,
        tasks: list[TaskDispatch],
        *,
        base_plan: dict[str, Any],
        work_dir: Path,
        act_fn: Callable[[str], dict[str, Any]],
        vla_step_fn: Callable[[Dict[str, Any]], Any],
        seating_probe_fn: Callable[[int, int], tuple[float, list[float]]],
        frame_fn: Optional[Callable[[str], Any]] = None,
    ) -> dict[str, Any]:
        """Executes a multi-tier (Tier 1 -> Tier 2 -> Tier 3) hybrid stacking plan with Look-Ahead Prefetching."""
        return run_3tier_hybrid_plan(
            self,
            tasks,
            base_plan=base_plan,
            work_dir=work_dir,
            act_fn=act_fn,
            vla_step_fn=vla_step_fn,
            seating_probe_fn=seating_probe_fn,
            frame_fn=frame_fn,
        )

    def _emit_telemetry(
        self,
        message: str,
        lat_ms: float = 0.0,
        action: Optional[list[float]] = None,
        decision_veto: Optional[dict[str, Any]] = None,
        sim_precheck: Optional[dict[str, Any]] = None,
        release_residual: Optional[dict[str, float]] = None,
    ) -> HandoverTelemetry:
        self.last_telemetry = HandoverTelemetry(
            state=self.current_state,
            task_id=self.active_task.task_id if self.active_task else "NONE",
            current_tier=self.active_task.tier if self.active_task else 0,
            vla_inference_lat_ms=lat_ms,
            action_vector=action or [],
            retry_count=self.retry_count,
            decision_veto=decision_veto,
            sim_precheck=sim_precheck,
            release_residual=release_residual,
            message=message,
        )
        return self.last_telemetry
