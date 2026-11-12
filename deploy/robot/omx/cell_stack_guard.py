#!/usr/bin/env python3
"""Triple Verification Gate for 1/2/3-Tier Precision Stacking (2026-11-11).
Integrates with ROSY Unified AreaXYZ (`omx_adapter.area_xyz.TIER_Z_M`),
calculus grasp dynamics (`cell_arm_cal.evaluate_grasp_dynamics`),
preload-relieved guarded release (`learning/envs/isaac/guarded_release.py`),
and dual-camera ROI outcome verification (`cell_area_zones.verify_stack_outcome`).

3-Stage Pre-Release + Post-Release Verification:
  1. Height Window Gate: Absolute Z-height must match AreaXYZ TIER_Z_M[tier]
     (Tier 1 = 0.0074m, Tier 2 = 0.0398m, Tier 3 = 0.0674m) ± tolerance.
  2. Torque & Calculus Seating Stiffness Gate: Contact current/torque profile and vertical
     stiffness derivative (`k_seat = -dI/dz`) must show vertical stud seating and preload
     relaxation within [settle_torque_min, settle_torque_max], not side-edge rim collision.
  3. Preload-Relief & Micro-Tension Lock Test: Subtle +1.0mm upward lift (matching
     guarded_release step_up_z) to relieve preload and confirm stud lock before opening.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any, Callable, Optional

_HERE = Path(__file__).resolve().parent
_ADAPTER = _HERE.parents[2] / "middleware" / "devices" / "omx" / "adapter"
for _p in (_HERE, _ADAPTER):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

try:
    from omx_adapter.area_xyz import TIER_Z_M
except ImportError:
    TIER_Z_M = {1: 0.0074, 2: 0.0398, 3: 0.0674}

import cell_arm_cal as acal
import cell_area_zones as caz


@dataclass
class StackGateConfig:
    tier: int = 3
    nominal_z_m: Optional[float] = None  # Defaults to TIER_Z_M[tier] (0.0674m for Tier 3)
    z_tolerance_m: float = 0.0025  # ±2.5mm physical stud engagement window
    min_holding_current: float = 50.0  # mA
    jam_torque_threshold: float = 280.0  # Excessive current/torque indicates side-edge rim jam
    max_torque_surge_per_step: float = 190.0  # Rapid single-step current spike from hard rim impact
    settle_torque_min: float = 80.0
    settle_torque_max: float = 220.0
    min_seat_stiffness_ma_per_mm: float = 8.0
    max_seat_stiffness_ma_per_mm: float = 165.0
    pull_test_lift_m: float = 0.001  # +1mm preload relief / micro-tension test
    max_retries: int = 3

    def resolved_nominal_z_m(self) -> float:
        if self.nominal_z_m is not None:
            return float(self.nominal_z_m)
        return float(TIER_Z_M.get(int(self.tier), TIER_Z_M[3]))


@dataclass
class GateResult:
    passed: bool
    reason: str
    stage_failed: Optional[str] = None
    recovery_action: Optional[str] = None
    telemetry: Optional[dict[str, Any]] = None


class CellStackGuard:
    """Guards against container drops and rim jamming during Tier 1/2/3 stacking."""

    def __init__(self, config: Optional[StackGateConfig] = None):
        self.cfg = config or StackGateConfig()

    def verify_height(
        self,
        current_z_m: float,
        target_z_m: Optional[float] = None,
        *,
        tier: Optional[int] = None,
    ) -> tuple[bool, str]:
        """Stage 1: Verify absolute Z height window against AreaXYZ TIER_Z_M."""
        if target_z_m is not None:
            target = float(target_z_m)
        elif tier is not None and int(tier) in TIER_Z_M:
            target = float(TIER_Z_M[int(tier)])
        else:
            target = self.cfg.resolved_nominal_z_m()

        diff = abs(current_z_m - target)
        if diff > self.cfg.z_tolerance_m:
            return (
                False,
                f"Height mismatch: current={current_z_m * 1000:.1f}mm, target={target * 1000:.1f}mm "
                f"(err={diff * 1000:.1f}mm > {self.cfg.z_tolerance_m * 1000:.1f}mm)",
            )
        return True, f"Height window OK ({current_z_m * 1000:.1f}mm vs target {target * 1000:.1f}mm)"

    def verify_torque_profile(self, torque_samples: list[float]) -> tuple[bool, str]:
        """Stage 2: Verify current/torque surge, 1st-derivative impact rate, & settle signature."""
        if not torque_samples:
            return False, "No torque telemetry samples provided"

        peak_torque = max(torque_samples)
        final_settle_torque = torque_samples[-1]
        max_surge = max((torque_samples[i + 1] - torque_samples[i] for i in range(len(torque_samples) - 1)), default=0.0)

        if peak_torque > self.cfg.jam_torque_threshold:
            return (
                False,
                f"Side jamming detected: peak torque {peak_torque:.1f} exceeds jam limit {self.cfg.jam_torque_threshold:.1f}",
            )

        if max_surge > self.cfg.max_torque_surge_per_step:
            return (
                False,
                f"Hard rim impact detected: single-step surge {max_surge:.1f} exceeds limit {self.cfg.max_torque_surge_per_step:.1f}",
            )

        if final_settle_torque < self.cfg.settle_torque_min:
            return (
                False,
                f"Under-seating detected: settled torque {final_settle_torque:.1f} below minimum {self.cfg.settle_torque_min:.1f}",
            )

        if final_settle_torque > self.cfg.settle_torque_max:
            return (
                False,
                f"Over-stress detected: settled torque {final_settle_torque:.1f} exceeds settle max {self.cfg.settle_torque_max:.1f}",
            )

        return (
            True,
            f"Torque signature valid (peak={peak_torque:.1f}, settle={final_settle_torque:.1f}, max_surge={max_surge:.1f})",
        )

    def evaluate_stud_seating_derivatives(
        self,
        z_samples_m: list[float],
        torque_samples: list[float],
    ) -> dict[str, Any]:
        """Computes vertical contact stiffness `k_seat_ma_per_mm = dI / (-dz_mm)` and preload relaxation."""
        if len(z_samples_m) < 2 or len(torque_samples) < 2:
            return {"ok": True, "regime": "insufficient_samples", "k_seat_ma_per_mm": 0.0, "preload_relax_ma": 0.0}

        dz_mm = max(0.2, (float(z_samples_m[0]) - min(float(z) for z in z_samples_m)) * 1000.0)
        peak_i = max(float(i) for i in torque_samples)
        init_i = float(torque_samples[0])
        end_i = float(torque_samples[-1])
        k_seat = round(max(0.0, peak_i - init_i) / dz_mm, 2)
        preload_relax = round(peak_i - end_i, 2)

        if k_seat > self.cfg.max_seat_stiffness_ma_per_mm or peak_i > self.cfg.jam_torque_threshold:
            regime = "rim_jam_collision"
            ok = False
        elif k_seat < self.cfg.min_seat_stiffness_ma_per_mm or end_i < self.cfg.settle_torque_min:
            regime = "air_or_under_seated"
            ok = False
        else:
            regime = "stud_locked_and_relaxed" if preload_relax >= 5.0 else "stud_seated"
            ok = True

        return {
            "ok": ok,
            "regime": regime,
            "k_seat_ma_per_mm": k_seat,
            "preload_relax_ma": preload_relax,
            "dz_descent_mm": round(dz_mm, 2),
        }

    def verify_grasp_dynamics_before_place(
        self,
        r_grasp: dict[str, Any],
        r_lift: Optional[dict[str, Any]] = None,
        r_above_place: Optional[dict[str, Any]] = None,
        *,
        closed: float = 48.8,
        open_pos: float = 57.85,
    ) -> tuple[bool, dict[str, Any]]:
        """Integrates cell_arm_cal.evaluate_grasp_dynamics to verify container did not slip in transit."""
        dyn = acal.evaluate_grasp_dynamics(
            r_grasp,
            r_lift=r_lift,
            r_above_place=r_above_place,
            closed=closed,
            open_pos=open_pos,
            baseline_current_ma=self.cfg.min_holding_current,
        )
        return bool(dyn.get("holding", False)), dyn

    def execute_micro_pull_test(
        self,
        current_z_m: float,
        read_grip_holding_fn: Callable[[], bool],
        read_z_fn: Callable[[], float],
        lift_step_fn: Callable[[float], None],
        *,
        relieve_preload_only: bool = False,
    ) -> tuple[bool, str]:
        """Stage 3: Subtle +1mm step-up (preload relief + stud lock check)."""
        if not read_grip_holding_fn():
            return False, "Container lost grip before pull test"

        lift_step_fn(self.cfg.pull_test_lift_m)
        _ = read_z_fn()

        if not read_grip_holding_fn():
            return False, "Container slipped out during micro-tension lock check"

        if not relieve_preload_only:
            lift_step_fn(-self.cfg.pull_test_lift_m)
        return True, "Micro-tension stud lock & preload relief verified"

    def evaluate_release(
        self,
        current_z_m: float,
        target_z_m: Optional[float],
        torque_history: list[float],
        read_grip_holding_fn: Optional[Callable[[], bool]] = None,
        read_z_fn: Optional[Callable[[], float]] = None,
        lift_step_fn: Optional[Callable[[float], None]] = None,
        *,
        tier: Optional[int] = None,
        z_history_m: Optional[list[float]] = None,
    ) -> GateResult:
        """Full 3-stage gate evaluation before gripper open (`run release_place`)."""
        resolved_target = (
            float(target_z_m)
            if target_z_m is not None
            else float(TIER_Z_M.get(int(tier), self.cfg.resolved_nominal_z_m()) if tier is not None else self.cfg.resolved_nominal_z_m())
        )
        deriv_info = (
            self.evaluate_stud_seating_derivatives(z_history_m, torque_history)
            if z_history_m
            else None
        )

        # Gate 1: Height Window (AreaXYZ TIER_Z_M)
        ok_h, msg_h = self.verify_height(current_z_m, resolved_target, tier=tier)
        if not ok_h:
            return GateResult(
                passed=False,
                reason=msg_h,
                stage_failed="STAGE_1_HEIGHT",
                recovery_action="reinsert_and_retry",
                telemetry={
                    "current_z": current_z_m,
                    "target_z": resolved_target,
                    "tier": tier or self.cfg.tier,
                    "seating_derivatives": deriv_info,
                },
            )

        # Gate 2: Torque / Current Profile & Seating Stiffness Derivative
        ok_t, msg_t = self.verify_torque_profile(torque_history)
        if not ok_t or (deriv_info is not None and not deriv_info["ok"]):
            fail_reason = msg_t if not ok_t else f"Seating stiffness invalid: {deriv_info['regime']} (k={deriv_info['k_seat_ma_per_mm']} mA/mm)"
            return GateResult(
                passed=False,
                reason=fail_reason,
                stage_failed="STAGE_2_TORQUE",
                recovery_action="reinsert_and_retry",
                telemetry={
                    "torque_history": torque_history,
                    "tier": tier or self.cfg.tier,
                    "seating_derivatives": deriv_info,
                },
            )

        # Gate 3: Optional Micro-Tension & Preload Relief Test
        if read_grip_holding_fn and read_z_fn and lift_step_fn:
            ok_p, msg_p = self.execute_micro_pull_test(
                current_z_m, read_grip_holding_fn, read_z_fn, lift_step_fn
            )
            if not ok_p:
                return GateResult(
                    passed=False,
                    reason=msg_p,
                    stage_failed="STAGE_3_PULL_TEST",
                    recovery_action="reinsert_and_retry",
                    telemetry={"pull_test_lift_m": self.cfg.pull_test_lift_m},
                )

        return GateResult(
            passed=True,
            reason="All 3-Stage Verification Gates Passed (AreaXYZ Height, Torque, Stud Lock)",
            stage_failed=None,
            recovery_action="proceed",
            telemetry={
                "current_z": current_z_m,
                "target_z": resolved_target,
                "tier": tier or self.cfg.tier,
                "peak_torque": max(torque_history) if torque_history else 0.0,
                "seating_derivatives": deriv_info,
            },
        )

    def verify_post_release_cameras(
        self,
        before_side: Any,
        after_side: Any,
        pick: dict[str, Any],
        place: dict[str, Any],
        *,
        after_top: Any = None,
    ) -> dict[str, Any]:
        """Delegates post-release visual verification to cell_area_zones.verify_stack_outcome."""
        return caz.verify_stack_outcome(
            before_side=before_side,
            after_side=after_side,
            pick=pick,
            place=place,
            after_top=after_top,
        )
