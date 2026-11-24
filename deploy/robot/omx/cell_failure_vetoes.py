#!/usr/bin/env python3
"""Deterministic redaction, 16 measured vetoes, and closed fallback menu policy (D-1072)."""
from __future__ import annotations

import re
from typing import Any

MAX_CHAIN_DEPTH = 2
HOME_POSE_TOL_UNITS = 8.0

FALLBACK_VERBS = (
    "reinsert",
    "release_and_rise",
    "align_push",
    "retry_ik_slower",
    "retry_ik_alt_axis",
    "redirect_alt_dest",
    "home_unwedge",
    "propose_ik_fallback_for_policy",
    "escalate_human",
)
MEASURED_VETO_CODES = (
    "OUT_OF_HOME_POSE",
    "TOP_CAMERA_SHIFTED",
    "MISSING_SITE_MAP",
    "ARM_INCIDENT_HELD",
    "LATCHED_HW_ERROR",
    "WINDUP_HIT",
    "CAPS_UNRESTORED",
    "EXTENDED_TORQUE_DROP_FORBIDDEN",
    "HOLDING_HIGH_NO_RELEASE",
    "REPEAT_UNKNOWN_ESCALATION",
    "AMR_BED_REQUIRES_FLEET_R",
    "MISSING_REQUIRED_CAMERA",
    "PENDING_INTENT_PRESENT",
    "PEER_ARM_LOCKED_OR_HELD",
    "FLEET_SAFETY_STOP_OR_ABORTED",
    "NO_MEASURED_OBJECTS",
)

_SECRET_KEY_RE = re.compile(r"(?:token|secret|authorization|api[-_]?key|password|cookie|private[-_]?key)", re.I)
_PRIVATE_IP_RE = re.compile(
    r"(?<![\d.])(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3})(?![\d.])"
)
_HOME_UNIX_RE = re.compile(r"/home/[A-Za-z0-9_.-]+")
_HOME_WIN_RE = re.compile(r"[A-Za-z]:\\Users\\[^\\/:*?\"<>|\s]+")
_BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._\-+/=]{8,}", re.I)
_HARD_BLOCKERS = {
    "LATCHED_HW_ERROR", "WINDUP_HIT", "CAPS_UNRESTORED", "FLEET_SAFETY_STOP_OR_ABORTED",
    "REPEAT_UNKNOWN_ESCALATION", "PENDING_INTENT_PRESENT", "PEER_ARM_LOCKED_OR_HELD",
}


def redact_context(value: Any) -> Any:
    """Strip private/Tailscale IPs, user home prefixes, bearer strings, and secret keys."""
    if isinstance(value, str):
        s = _PRIVATE_IP_RE.sub("[REDACTED_IP]", value)
        s = _HOME_UNIX_RE.sub("/home/[USER]", s)
        s = _HOME_WIN_RE.sub("[USER_HOME]", s)
        return _BEARER_RE.sub("Bearer [REDACTED]", s)
    if isinstance(value, list):
        return [redact_context(item) for item in value]
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if _SECRET_KEY_RE.search(str(k)) else redact_context(v)) for k, v in value.items()}
    return value


def _veto(code: str, severity: str, detail: str, path: str) -> dict[str, str]:
    return {"code": code, "severity": severity, "detail": detail[:300], "evidence_path": path[:120]}


def compute_measured_vetoes(
    measurement: dict[str, Any],
    spatial: dict[str, Any],
    visual: dict[str, Any],
    *,
    pending_intent_present: bool = False,
    repeat_unknown_tripped: bool = False,
) -> list[dict[str, str]]:
    """Evaluate all 16 deterministic vetoes from measured bundle sections."""
    vetoes: list[dict[str, str]] = []
    kin = measurement.get("kinematics_and_health") or {}
    if isinstance(kin.get("max_home_err_units"), (int, float)) and kin["max_home_err_units"] > HOME_POSE_TOL_UNITS:
        vetoes.append(_veto("OUT_OF_HOME_POSE", "hard", f"max_home_err_units={kin['max_home_err_units']}", "measurement.kinematics_and_health.max_home_err_units"))
    cal = spatial.get("calibration") or {}
    shift = cal.get("top_shift_px") or {}
    raw_lim = shift.get("limit_px")
    lim_px = raw_lim if isinstance(raw_lim, (int, float)) and not isinstance(raw_lim, bool) else 6.0
    max_px = shift.get("max_px")
    if shift.get("moved") is True or (isinstance(max_px, (int, float)) and not isinstance(max_px, bool) and max_px > lim_px):
        vetoes.append(_veto("TOP_CAMERA_SHIFTED", "hard", f"top shift max_px={max_px} limit={lim_px}", "spatial.calibration.top_shift_px"))
    if cal.get("missing_map"):
        vetoes.append(_veto("MISSING_SITE_MAP", "hard", f"missing_map={cal['missing_map']}", "spatial.calibration.missing_map"))
    inc = measurement.get("incident") or {}
    if inc.get("local_held") is True or inc.get("fleet_held") is True:
        vetoes.append(_veto("ARM_INCIDENT_HELD", "hard", f"held local={inc.get('local_held')} fleet={inc.get('fleet_held')}", "measurement.incident"))
    if inc.get("latched_motors"):
        vetoes.append(_veto("LATCHED_HW_ERROR", "hard", f"latched_motors={sorted(inc['latched_motors'])}", "measurement.incident.latched_motors"))
    if (inc.get("windup_hits_count") or 0) > 0:
        vetoes.append(_veto("WINDUP_HIT", "hard", f"windup_hits_count={inc['windup_hits_count']}", "measurement.incident.windup_hits_count"))
    if inc.get("caps_restored") is False:
        vetoes.append(_veto("CAPS_UNRESTORED", "hard", "servo caps not restored", "measurement.incident.caps_restored"))
    hf = measurement.get("holding_and_fold") or {}
    live_fold = hf.get("live_fold") or {}
    fold_rb = hf.get("fold_readback")
    if live_fold.get("folded") is False or live_fold.get("at_rest_tol_8") is False or (isinstance(fold_rb, dict) and fold_rb.get("folded") is False):
        vetoes.append(_veto("EXTENDED_TORQUE_DROP_FORBIDDEN", "hard", "arm extended; keep torque ON (D-1048)", "measurement.holding_and_fold.live_fold"))
    still = hf.get("still_holding") or {}
    if still.get("measured") is True and still.get("tcp_low_for_release") is not True:
        vetoes.append(_veto("HOLDING_HIGH_NO_RELEASE", "hard", "holding object high; release forbidden", "measurement.holding_and_fold.still_holding"))
    if repeat_unknown_tripped or measurement.get("repeat_unknown_tripped") is True:
        vetoes.append(_veto("REPEAT_UNKNOWN_ESCALATION", "hard", "unknown cause repeated twice", "history_and_constraints.repeat_unknown_tripped"))
    sites = spatial.get("sites") or {}
    if sites.get("is_amr_bed") is True:
        vetoes.append(_veto("AMR_BED_REQUIRES_FLEET_R", "hard", "AMR bed site requires Fleet-R claim path", "spatial.sites.is_amr_bed"))
    for cam, entry in sorted((visual.get("camera_manifest") or {}).items()):
        if isinstance(entry, dict) and entry.get("required_for_mode") is True and entry.get("status") != "ok":
            vetoes.append(_veto("MISSING_REQUIRED_CAMERA", "hard", f"{cam} status={entry.get('status')}", f"visual.camera_manifest.{cam}"))
            break
    outcome = measurement.get("outcome") or {}
    if pending_intent_present or measurement.get("pending_intent_present") is True or outcome.get("pending_intent_present") is True:
        vetoes.append(_veto("PENDING_INTENT_PRESENT", "hard", "D-911 pending intent unresolved", "measurement.outcome"))
    occ = spatial.get("workspace_occupancy") or {}
    arms_occ = occ.get("arms") or {}
    peer_blocked = occ.get("peer_ab_session_locked") is True or occ.get("whole_cell_lock_held") is True or any(
        isinstance(a, dict) and (a.get("held") is True or (a.get("session_lock_held") is True and a.get("folded") is not True))
        for a in arms_occ.values()
    )
    if peer_blocked:
        vetoes.append(_veto("PEER_ARM_LOCKED_OR_HELD", "hard", "peer arm or whole-cell lock active", "spatial.workspace_occupancy"))
    fs = occ.get("fleet_safety") or {}
    if fs.get("active_estop") is True or fs.get("human_detected") is True or fs.get("cell_aborted") is True:
        vetoes.append(_veto("FLEET_SAFETY_STOP_OR_ABORTED", "hard", "Fleet safety stop or cell ABORTED", "spatial.workspace_occupancy.fleet_safety"))
    perc = spatial.get("perception") or {}
    objs = perc.get("detected_objects")
    if isinstance(objs, list) and len(objs) == 0 and outcome.get("attempt_cause") in ("empty", "no_room", "no_progress"):
        vetoes.append(_veto("NO_MEASURED_OBJECTS", "soft", "zero catalog objects detected in ROI", "spatial.perception.detected_objects"))
    return vetoes


def _menu_item(verb: str, tier: int, stratum: str, surface: str, req_op: bool, req_sw: bool, active_codes: list[str], blockers: set[str]) -> dict[str, Any]:
    blocked_by = [c for c in active_codes if c in blockers]
    return {
        "verb": verb,
        "tier": tier,
        "stratum": stratum,
        "target_surface": surface,
        "requires_human_operator": req_op,
        "requires_person_at_switch": req_sw,
        "preconditions_met": len(blocked_by) == 0,
        "blocked_by": blocked_by,
    }


def build_allowed_fallback_menu(
    executor_mode: str,
    attempt_cause: str,
    vetoes: list[dict[str, Any]],
    *,
    fallback_chain_depth: int = 0,
    max_chain_depth: int = MAX_CHAIN_DEPTH,
    has_declared_alternates: bool = False,
    dest_full_pre_motion: bool = False,
    auto_fold_armed: bool = False,
) -> list[dict[str, Any]]:
    """Build closed fallback options; never emits Tier-2 policy->IK auto-swaps."""
    codes = [v["code"] for v in vetoes]
    if fallback_chain_depth >= max_chain_depth:
        codes.append("CHAIN_DEPTH_EXCEEDED")
    hard = _HARD_BLOCKERS | {"CHAIN_DEPTH_EXCEEDED"}
    motion_block = hard | {"OUT_OF_HOME_POSE", "TOP_CAMERA_SHIFTED", "MISSING_SITE_MAP", "ARM_INCIDENT_HELD", "MISSING_REQUIRED_CAMERA", "EXTENDED_TORQUE_DROP_FORBIDDEN", "HOLDING_HIGH_NO_RELEASE"}
    menu = [_menu_item("escalate_human", 0, "human_only", "human_request", False, False, codes, set())]

    if executor_mode in ("act_paced", "act_timed", "hybrid"):
        menu.append(_menu_item("propose_ik_fallback_for_policy", 1, "tier1_propose", "fleet_pipeline", True, False, codes, motion_block))
    if dest_full_pre_motion and has_declared_alternates:
        menu.append(_menu_item("redirect_alt_dest", 2, "tier2_auto", "fleet_pipeline", False, False, codes, motion_block - {"EXTENDED_TORQUE_DROP_FORBIDDEN", "HOLDING_HIGH_NO_RELEASE"}))
    if auto_fold_armed:
        menu.append(_menu_item("home_unwedge", 2, "tier2_auto", "cell_job_api", False, False, codes, hard | {"HOLDING_HIGH_NO_RELEASE"}))
    else:
        menu.append(_menu_item("home_unwedge", 3, "human_only", "cell_job_api", True, True, codes, {"LATCHED_HW_ERROR", "WINDUP_HIT", "FLEET_SAFETY_STOP_OR_ABORTED", "PEER_ARM_LOCKED_OR_HELD", "PENDING_INTENT_PRESENT", "CHAIN_DEPTH_EXCEEDED"}))

    if executor_mode in ("ik_auto_pick", "recovery"):
        if attempt_cause in ("lift_stall", "no_progress"):
            menu.append(_menu_item("retry_ik_slower", 1, "tier1_propose", "cell_job_api", True, True, codes, motion_block | {"AMR_BED_REQUIRES_FLEET_R", "NO_MEASURED_OBJECTS"}))
        if attempt_cause in ("no_room", "pile", "s3_packed_no_clearance", "s6_unseated_cone", "lift_stall", "misaligned", "unstable_grasp", "no_progress"):
            menu.append(_menu_item("align_push", 1, "tier1_propose", "cell_job_api", True, True, codes, motion_block | {"AMR_BED_REQUIRES_FLEET_R"}))
        if attempt_cause in ("empty", "unstable_grasp", "misaligned", "no_progress"):
            menu.append(_menu_item("retry_ik_alt_axis", 1, "tier1_propose", "cell_job_api", True, True, codes, motion_block | {"AMR_BED_REQUIRES_FLEET_R", "NO_MEASURED_OBJECTS"}))
    return menu
