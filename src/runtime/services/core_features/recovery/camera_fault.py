"""Operator-selected actions for a camera-fault demo.

This module only reports eligibility. It never changes the active task or emits
motion commands; CORE must re-evaluate the evidence immediately before start.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class CameraFaultEvidence:
    active_task: Optional[str]
    selected_action: Optional[str]
    mode: str
    ir_calibrated: bool
    ir_calibration_revision: Optional[str]
    expected_ir_calibration_revision: Optional[str]
    ir_age_s: Optional[float]
    ir_line_valid: bool
    ir_line_age_s: Optional[float]
    lidar_age_s: Optional[float]
    localization_valid: bool
    stopped_readback: bool
    g4_passed: bool
    g5_passed: bool
    nav2_active: bool = False
    odom_age_s: Optional[float] = None
    tf_age_s: Optional[float] = None
    map_aligned: bool = False
    teleop_authorized: bool = False
    deadman_active: bool = False
    deadman_age_s: Optional[float] = None


@dataclass(frozen=True)
class CameraFaultEligibility:
    allowed_actions: tuple[str, ...]
    selected_action: Optional[str]
    reasons: tuple[str, ...]
    evidence_ages: tuple[tuple[str, Optional[float]], ...]
    expires_at: float


def _fresh(age: Optional[float], maximum: float) -> bool:
    return (isinstance(age, (int, float)) and not isinstance(age, bool)
            and math.isfinite(float(age)) and 0.0 <= float(age) <= maximum)


def evaluate_camera_fault(evidence: CameraFaultEvidence, *, now: float,
                          max_evidence_age_s: float = 0.25) -> CameraFaultEligibility:
    """Calculate currently eligible camera-free actions, without auto-selecting.

    The short expiry is an advisory lease only. A command path must fetch fresh
    CORE evidence and repeat this check before accepting a task.
    """
    if not isinstance(now, (int, float)) or isinstance(now, bool) or not math.isfinite(now):
        raise ValueError("now must be finite")
    if (not isinstance(max_evidence_age_s, (int, float))
            or isinstance(max_evidence_age_s, bool)
            or not math.isfinite(max_evidence_age_s) or max_evidence_age_s <= 0):
        raise ValueError("max_evidence_age_s must be positive and finite")

    reasons: set[str] = set()
    if evidence.active_task is not None:
        reasons.add("ACTIVE_TASK_NOT_CLEARED")
    if not evidence.stopped_readback:
        reasons.add("STOP_NOT_READ_BACK")
    if not evidence.g4_passed:
        reasons.add("G4_NOT_PASSED")
    if not evidence.g5_passed:
        reasons.add("G5_NOT_PASSED")
    if evidence.mode != "navigation":
        reasons.add("MOTOR_MODE")

    actions: list[str] = []
    calibration_matches = (
        isinstance(evidence.ir_calibration_revision, str)
        and isinstance(evidence.expected_ir_calibration_revision, str)
        and bool(evidence.ir_calibration_revision)
        and evidence.ir_calibration_revision == evidence.expected_ir_calibration_revision
    )
    if (evidence.ir_calibrated and calibration_matches
            and _fresh(evidence.ir_age_s, max_evidence_age_s)
            and _fresh(evidence.ir_line_age_s, max_evidence_age_s)
            and evidence.ir_line_valid and _fresh(evidence.lidar_age_s, max_evidence_age_s)):
        if not reasons:
            actions.append("IR_LINE")
    else:
        if not evidence.ir_calibrated:
            reasons.add("IR_NOT_CALIBRATED")
        if not calibration_matches:
            reasons.add("IR_CALIBRATION_REVISION_MISMATCH")
        if not _fresh(evidence.ir_age_s, max_evidence_age_s):
            reasons.add("IR_STALE")
        if not evidence.ir_line_valid:
            reasons.add("IR_LINE_NOT_VALID")
        if not _fresh(evidence.ir_line_age_s, max_evidence_age_s):
            reasons.add("IR_LINE_STALE")
        if not _fresh(evidence.lidar_age_s, max_evidence_age_s):
            reasons.add("LIDAR_STALE")

    if (evidence.nav2_active and evidence.localization_valid and evidence.map_aligned
            and _fresh(evidence.lidar_age_s, max_evidence_age_s)
            and _fresh(evidence.ir_age_s, max_evidence_age_s)
            and _fresh(evidence.odom_age_s, max_evidence_age_s)
            and _fresh(evidence.tf_age_s, max_evidence_age_s)
            and evidence.g4_passed and evidence.g5_passed and evidence.stopped_readback
            and evidence.mode == "navigation"
            and evidence.active_task is None):
        actions.append("NAV_GOAL")
    elif evidence.selected_action == "NAV_GOAL":
        reasons.add("NAV_NOT_ELIGIBLE")

    if (evidence.active_task is None and evidence.teleop_authorized
            and evidence.deadman_active and evidence.g4_passed
            and _fresh(evidence.deadman_age_s, max_evidence_age_s)
            and _fresh(evidence.lidar_age_s, max_evidence_age_s)
            and _fresh(evidence.ir_age_s, max_evidence_age_s)
            and evidence.stopped_readback and evidence.mode == "navigation"):
        actions.append("TELEOP")
    elif evidence.selected_action == "TELEOP":
        reasons.add("TELEOP_NOT_ELIGIBLE")

    selected = evidence.selected_action if evidence.selected_action in actions else None
    if evidence.selected_action and selected is None:
        reasons.add("SELECTED_ACTION_NOT_ELIGIBLE")
    return CameraFaultEligibility(
        allowed_actions=tuple(actions),
        selected_action=selected,
        reasons=tuple(sorted(reasons)),
        evidence_ages=(
            ("ir", evidence.ir_age_s), ("lidar", evidence.lidar_age_s),
            ("ir_line", evidence.ir_line_age_s), ("deadman", evidence.deadman_age_s),
            ("odom", evidence.odom_age_s), ("tf", evidence.tf_age_s),
        ),
        expires_at=float(now) + 0.25,
    )
