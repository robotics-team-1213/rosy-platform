"""Guarded recovery failure detector, staged homing visual state machine, policy & tool catalog."""
from __future__ import annotations

import math

from fleet.pipeline.cell_site_targets import ARM_CELL, act_fallback_refusal
from core_common.protocol.cell_failure_context import canonical_sha256
from core_common.protocol.pipeline_recovery_tools import (
    MAX_ACT_FALLBACK_CHUNKS,
    MAX_RECOVERIES_PER_ROOT,
    MAX_SAFE_HOME_PER_ARM_24H,
    RECOVERY_TOOLS_SCHEMA,
    REQUIRED_HOMING_CAMERAS,
)
from fleet.server.sitemap import pipeline_auto_events, pipeline_repark
from .pipeline_home_recovery import bound_home_worker_ready, incident_roots, limit_home_tools

CELL_ARMS = {"cell_s": ("arm_s",), "cell_ab": ("arm_a", "arm_b")}
CAM_CELL = {"arm_s_top": "cell_s", "arm_s_wrist": "cell_s", "top": "cell_ab", "side": "cell_ab",
            "arm_a_wrist": "cell_ab", "arm_b_wrist": "cell_ab"}
_HW_VETO_WORDS = ("latched", "windup", "holding_high", "overload", "hw_error")
_CAMERA_MAX_AGE_S = 15.0
_VISUAL_CLEAR_MAX_AGE_S = 60.0
_SEQ_WINDOW = 5


def effective_stop_fence(state) -> tuple[bool, int | None]:
    """Read durable stop authority across human holds, pipeline governance, and Fleet dispatch latch."""
    if getattr(state, "_pipeline_ledger_fault", False) or getattr(state, "_fleet_estop_latch_unresolved", False):
        return True, None
    held = bool(
        any(bool(v) for v in (getattr(state, "human_detected", None) or {}).values())
        or any((s or {}).get("phase") == "HUMAN_HOLD" for s in (getattr(state, "omx_cell_states", None) or {}).values())
    )
    gov = getattr(state, "pipeline_governance", None)
    gov_gen = gov_epoch = 0
    if gov is not None:
        try:
            snap = gov.snapshot()
            gov_gen, gov_epoch = int(snap["stop_generation"]), int(snap["authority_epoch"])
        except Exception:
            return True, None
    mem_gen = int(getattr(state, "safety_stop_generation", 0))
    task_svc = getattr(state, "task_service", None)
    dispatch_gen = dispatch_epoch = 0
    if task_svc is not None:
        try:
            ctrl = task_svc.store.dispatch_control()
        except Exception:
            return True, None
        if not isinstance(ctrl, dict):
            return True, None
        if ctrl.get("dispatch_enabled") is not True:
            held = True
        raw_gen = ctrl.get("generation")
        if raw_gen is not None:
            if type(raw_gen) is not int:
                return True, None
            dispatch_gen = raw_gen
        raw_ep = ctrl.get("authority_epoch")
        if type(raw_ep) is int:
            dispatch_epoch = raw_ep
    return held, max(gov_gen, mem_gen) + dispatch_gen + (gov_epoch + dispatch_epoch) * 1_000_000


def arm_folded_fresh(state, arm_id: str, now: float) -> bool:
    arm = (getattr(state, "arm_live_states", None) or {}).get(arm_id) or {}
    ts = arm.get("folded_updated_at")
    return (
        arm.get("folded") is True
        and isinstance(ts, (int, float)) and not isinstance(ts, bool)
        and math.isfinite(ts) and (-5.0 <= (now - ts) <= 120.0)
    )


def camera_snapshot_meta(state, arm_id: str | None, now: float) -> dict:
    req_cams = REQUIRED_HOMING_CAMERAS.get(arm_id or "", ())
    cam_map = getattr(state, "cell_camera_quality", None) or {}
    seqs: dict[str, int] = {}
    missing: list[str] = []
    for cam in req_cams:
        entry = cam_map.get(cam)
        if not isinstance(entry, dict) or entry.get("fresh") is not True:
            missing.append(cam)
            continue
        rec_at = entry.get("recorded_at")
        if (isinstance(rec_at, bool) or not isinstance(rec_at, (int, float))
                or not math.isfinite(rec_at) or not (-5.0 <= (now - rec_at) <= _CAMERA_MAX_AGE_S)):
            missing.append(cam)
            continue
        age = entry.get("receipt_age_s")
        if age is not None and (isinstance(age, bool) or not isinstance(age, (int, float)) or age > _CAMERA_MAX_AGE_S):
            missing.append(cam)
            continue
        seq = entry.get("sequence")
        if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0:
            missing.append(cam)
            continue
        seqs[cam] = seq
    return {
        "required_cameras": list(req_cams),
        "all_fresh": bool(req_cams) and not missing,
        "sequences": seqs,
        "missing_or_stale": missing,
    }


def apply_safe_home_acks(state, acks, now: float) -> bool:
    """Apply request-bound OMX safe-home acks and advance staged homing sessions; True if state mutated."""
    if not isinstance(acks, list) or not acks:
        return False
    pending = getattr(state, "pending_safe_home_arms", None)
    sessions = getattr(state, "pipeline_homing_sessions", None)
    if sessions is None:
        sessions = state.pipeline_homing_sessions = {}
    changed = False
    for raw in acks:
        if not isinstance(raw, dict):
            continue
        arm_id = str(raw.get("arm_id") or "")
        req_id = str(raw.get("request_id") or "")
        if not arm_id or not req_id or not isinstance(pending, dict):
            continue
        cur = pending.get(arm_id)
        if not isinstance(cur, dict) or cur.get("request_id") != req_id:
            continue
        strategy = str(cur.get("strategy") or "auto_fold")  # always trust server-issued strategy, never ack payload
        raw_out = raw.get("outcome")
        outcome = raw_out.strip() if isinstance(raw_out, str) and raw_out.strip() else "missing_outcome"
        root = str(cur.get("root_task_id") or f"arm:{arm_id}")
        session = dict(sessions.get(root) or {"root_task_id": root, "arm_id": arm_id})
        session.update({"arm_id": arm_id, "last_request_id": req_id, "last_strategy": strategy,
                        "last_outcome": outcome, "updated_at": round(now, 3)})
        if isinstance(raw.get("telemetry"), dict):
            session["last_telemetry"] = raw["telemetry"]
        if outcome in ("in_flight", "started"):
            if not cur.get("started"):
                cur["started"] = True
                session["stage"] = f"RUNNING_{strategy.upper()}"
                sessions[root] = session
                changed = True
            continue
        pending.pop(arm_id, None)
        changed = True
        cam_meta = camera_snapshot_meta(state, arm_id, now)
        session["stage_completed_at"] = round(now, 3)
        if outcome in ("held_guard_tripped", "failed"):
            session["stage"] = "HOLD_GUARD_TRIPPED"
            session["last_error"] = str(raw.get("detail") or outcome)[:120]
            pipeline_auto_events.add(state, [{
                "kind": "recovery_escalation", "arm": arm_id, "batch_id": req_id,
                "result": "escalated", "why": f"HOMING_GUARD_TRIPPED:{session['last_error']}",
                "person_needed": True, "t": now,
            }], "fleet")
        elif outcome == "skipped":
            session["stage"] = "SKIPPED"
            session["last_error"] = str(raw.get("detail") or "skipped")[:120]
        elif strategy == "release_and_lift" and outcome in ("completed", "risen_for_visual_verify"):
            session["stage"] = "AWAITING_LIFT_VISUAL_VERIFY"
            session["min_camera_seqs"] = dict(cam_meta["sequences"])
        elif strategy == "guarded_slow_park" and outcome == "completed":
            session["stage"] = "AWAITING_PARK_VISUAL_VERIFY"
            session["min_camera_seqs"] = dict(cam_meta["sequences"])
        elif strategy == "auto_fold" and outcome == "completed":
            session["stage"] = "AUTO_FOLD_COMPLETED"
        else:
            session["stage"] = "HOLD_GUARD_TRIPPED"
            session["last_error"] = f"UNEXPECTED_ACK:{strategy}:{outcome}"[:120]
            pipeline_auto_events.add(state, [{
                "kind": "recovery_escalation", "arm": arm_id, "batch_id": req_id,
                "result": "escalated", "why": session["last_error"], "person_needed": True, "t": now,
            }], "fleet")
        sessions[root] = session
    return changed


def evaluate_visual_checkpoint(state, failure: dict, args, now: float) -> tuple[bool, str | None, dict]:
    """Validate camera freshness + strictly advancing monotonic sequence and advance or lock homing session."""
    arm_id = failure.get("arm_id")
    if not arm_id:
        return False, "NO_OMX_ARM_FAILURE", {}
    if args.stage in ("pre_park", "after_lift") and args.verdict == "FOLDED_HOME":
        return False, "INVALID_VERDICT_FOR_STAGE", {"stage": args.stage, "verdict": args.verdict}
    if args.stage == "after_park" and args.verdict == "CLEAR":
        return False, "INVALID_VERDICT_FOR_STAGE", {"stage": args.stage, "verdict": args.verdict}

    cam_meta = camera_snapshot_meta(state, arm_id, now)
    if not cam_meta["all_fresh"]:
        return False, "CAMERA_STALE_OR_MISSING", {"missing_or_stale": cam_meta["missing_or_stale"]}

    sessions = getattr(state, "pipeline_homing_sessions", None)
    if sessions is None:
        sessions = state.pipeline_homing_sessions = {}
    root = failure["root_task_id"]
    session = dict(sessions.get(root) or {"root_task_id": root, "arm_id": arm_id, "stage": "IDLE"})
    cur_stage = session.get("stage") or "IDLE"
    if args.stage == "after_lift" and cur_stage != "AWAITING_LIFT_VISUAL_VERIFY":
        return False, "HOMING_STAGE_INVALID", {"expected_stage": "AWAITING_LIFT_VISUAL_VERIFY", "actual_stage": cur_stage}
    if args.stage == "after_park" and cur_stage != "AWAITING_PARK_VISUAL_VERIFY":
        return False, "HOMING_STAGE_INVALID", {"expected_stage": "AWAITING_PARK_VISUAL_VERIFY", "actual_stage": cur_stage}
    if args.stage == "pre_park" and cur_stage not in ("IDLE", "SKIPPED"):
        return False, "HOMING_STAGE_INVALID", {"expected_stage": "IDLE", "actual_stage": cur_stage}

    min_seqs = session.get("min_camera_seqs") or {}
    for cam in cam_meta["required_cameras"]:
        if cam not in args.cameras_checked:
            return False, "CAMERA_STALE_OR_MISSING", {"missing_camera": cam}
        checked = args.cameras_checked[cam]
        current = cam_meta["sequences"][cam]
        min_req = int(min_seqs.get(cam, -1))
        if (args.stage in ("after_lift", "after_park") and checked <= min_req) or checked > current or (current - checked) > _SEQ_WINDOW:
            return False, "VISUAL_CHECKPOINT_SEQUENCE_STALE", {"camera": cam, "checked": checked, "min_after": min_req, "current": current}

    session["last_visual"] = {"stage": args.stage, "verdict": args.verdict, "cargo_detached": args.cargo_detached,
                               "gripper_open": args.gripper_open, "overhead_clear": args.overhead_clear,
                               "cameras_checked": dict(args.cameras_checked), "summary": args.observation_summary,
                               "at": round(now, 3)}
    blocked_motion = args.verdict in ("OBSTRUCTED", "UNCERTAIN") or (
        args.stage in ("pre_park", "after_lift")
        and (not args.cargo_detached or not args.overhead_clear or args.gripper_open is False)
    ) or (args.stage == "after_lift" and args.gripper_open is not True)
    if blocked_motion or (args.stage == "after_park" and args.verdict != "FOLDED_HOME"):
        session["stage"] = "HOLD_VISUAL_BLOCKED"
        sessions[root] = session
        return True, None, {"stage": "HOLD_VISUAL_BLOCKED", "park_allowed": False, "recommend": "escalate_human"}

    if args.stage == "pre_park":
        session["stage"] = "DIRECT_PARK_VISUAL_CLEAR"
        session["visual_clear_at"] = round(now, 3)
        sessions[root] = session
        return True, None, {"stage": "DIRECT_PARK_VISUAL_CLEAR", "park_allowed": True}
    if args.stage == "after_lift":
        session["stage"] = "AFTER_LIFT_VISUAL_CLEAR"
        session["visual_clear_at"] = round(now, 3)
        sessions[root] = session
        return True, None, {"stage": "AFTER_LIFT_VISUAL_CLEAR", "park_allowed": True}

    arm_live = (getattr(state, "arm_live_states", None) or {}).get(arm_id) or {}
    folded_ts = float(arm_live.get("folded_updated_at") or 0.0) if isinstance(arm_live.get("folded_updated_at"), (int, float)) else 0.0
    stage_done_ts = float(session.get("stage_completed_at") or 0.0)
    if not arm_folded_fresh(state, arm_id, now) or folded_ts < stage_done_ts:
        return False, "FOLD_READBACK_NOT_CONFIRMED", {"arm_id": arm_id}
    session["stage"] = "AFTER_PARK_VISUAL_FOLDED"
    sessions[root] = session
    return True, None, {"stage": "AFTER_PARK_VISUAL_FOLDED", "ready_for_hold_clear": True}


def _hard_hw_veto(state, arm_id: str, task: dict | None) -> str | None:
    hold = (getattr(state, "arm_holds", None) or {}).get(arm_id) or {}
    reason = str(hold.get("reason") or "").lower()
    if hold.get("held") and any(w in reason for w in _HW_VETO_WORDS):
        return "LATCHED_HW_ERROR" if "latched" in reason or "hw_error" in reason else "WINDUP_HIT"
    tel = (task or {}).get("hardware_telemetry") or {}
    err = str(tel.get("error") or "").lower()
    if any(w in err for w in _HW_VETO_WORDS):
        return "HOLDING_HIGH_NO_RELEASE" if "holding_high" in err else "LATCHED_HW_ERROR"
    return None


def _root_of(task: dict) -> str:
    return str(task.get("fallback_from_task_id") or task.get("repark_root") or task["task_id"])


def _task_trigger(task: dict) -> str:
    err = str((task.get("hardware_telemetry") or {}).get("error") or "")
    reason = str((task.get("receipt") or {}).get("reason") or "")
    if "FOLD_READBACK_MISSING" in (err, reason):
        return "FOLD_READBACK_MISSING"
    if reason == "REVIEW_REQUIRED":
        return "REVIEW_REQUIRED"
    if "UNCALIBRATED_DISPLACED_SITE" in (err, reason):
        return "UNCALIBRATED_DISPLACED_SITE"
    return "CELL_ABORTED"


def collect_unresolved_failures(state, now: float, *, human_detected: bool, active=None,
                                dispatch_enabled: bool = False) -> list[dict]:
    """Detect unresolved failures across cells/tasks/Pinky and compute eligible tools + CAS sha256."""
    tasks = list((getattr(state, "omx_cell_tasks", None) or {}).values())
    cells = getattr(state, "omx_cell_states", None) or {}
    holds = getattr(state, "arm_holds", None) or {}
    reparks = getattr(state, "repark_requests", None) or {}
    budgets_map = getattr(state, "pipeline_recovery_budgets", None) or {}
    fence_held, cur_gen = effective_stop_fence(state)
    human_detected = bool(human_detected or fence_held)
    pending_home = {} if cur_gen is None else {
        a: r for a, r in (getattr(state, "pending_safe_home_arms", None) or {}).items()
        if isinstance(r, dict)
        and (not isinstance(r.get("expires_at"), (int, float)) or isinstance(r.get("expires_at"), bool) or now <= float(r["expires_at"]))
        and r.get("stop_generation") == cur_gen
    }
    home_hist = getattr(state, "safe_home_history", None) or {}
    sessions = getattr(state, "pipeline_homing_sessions", None) or {}
    completed_roots = {_root_of(t) for t in tasks if t.get("status") == "COMPLETED"}

    out: list[dict] = []
    for root, arm, cell, incident in incident_roots(ARM_CELL, holds):
        out.append(_build_failure_entry(
            state, now, human_detected=human_detected, active=active, dispatch_enabled=dispatch_enabled,
            root=root, trigger="HOME_RECOVERY_REQUIRED", cell_id=cell, arm_id=arm, robot_id=None, task=None,
            budgets=budgets_map.get(root) or {}, holds=holds, cells=cells, repark_req=None,
            pending_home=pending_home, home_hist=home_hist, session=sessions.get(root) or {}, incident_id=incident,
        ))
    seen_roots: set[str] = set()
    for t in reversed(tasks):
        if t.get("status") != "ABORTED":
            continue
        root = _root_of(t)
        if root.startswith("home-recovery:") or root in seen_roots or root in completed_roots:
            continue
        seen_roots.add(root)
        cell_id = t.get("cell_id") or "cell_s"
        arm_id = t.get("arm_id") or CELL_ARMS.get(cell_id, ("arm_s",))[0]
        trigger = _task_trigger(t)
        req_for_robot = reparks.get(t.get("robot_id"))
        if trigger != "FOLD_READBACK_MISSING":
            if req_for_robot and req_for_robot.get("state") == "FAILED" and req_for_robot.get("root") == root:
                trigger = "REPARK_FAILED"
            elif any(e.get("kind") == "auto_repark" and e.get("why") == "REPARK_LIMIT"
                     for e in (getattr(state, "cell_auto_events", None) or [])):
                if t.get("repark_root") or req_for_robot:
                    trigger = "REPARK_LIMIT"
        out.append(_build_failure_entry(
            state, now, human_detected=human_detected, active=active, dispatch_enabled=dispatch_enabled,
            root=root, trigger=trigger, cell_id=cell_id, arm_id=arm_id, robot_id=t.get("robot_id"), task=t,
            budgets=budgets_map.get(root) or {}, holds=holds, cells=cells, repark_req=req_for_robot,
            pending_home=pending_home, home_hist=home_hist, session=sessions.get(root) or {},
        ))

    for cid, cstate in cells.items():
        if cstate.get("phase") == "ABORTED" and not any(f["cell_id"] == cid and not f.get("incident_id") for f in out):
            root = f"cell:{cid}"
            out.append(_build_failure_entry(
                state, now, human_detected=human_detected, active=active, dispatch_enabled=dispatch_enabled,
                root=root, trigger="CELL_ABORTED", cell_id=cid, arm_id=CELL_ARMS.get(cid, ("arm_s",))[0],
                robot_id=(cstate.get("docked_robot") or {}).get("robot_id") or cstate.get("robot_id"),
                task=None, budgets=budgets_map.get(root) or {}, holds=holds, cells=cells, repark_req=None,
                pending_home=pending_home, home_hist=home_hist, session=sessions.get(root) or {},
            ))

    pinky_by_root: dict[str, dict] = {}
    for pt in (getattr(state, "pinky_tasks", None) or {}).values():
        if pt.get("robot_id") or pt.get("fallback_from_task_id"):
            p_root = str(pt.get("fallback_from_task_id") or f"pinky:{pt['task_id']}")
            pinky_by_root[p_root] = pt
    for p_root, pt in pinky_by_root.items():
        if not p_root.startswith("home-recovery:") and pt.get("status") in ("FAILED", "REFUSED"):
            trig = "PINKY_FAILED" if pt["status"] == "FAILED" else "PINKY_REFUSED"
            out.append(_build_failure_entry(
                state, now, human_detected=human_detected, active=active, dispatch_enabled=dispatch_enabled,
                root=p_root, trigger=trig, cell_id=None, arm_id=None, robot_id=pt.get("robot_id"), task=pt,
                budgets=budgets_map.get(p_root) or {}, holds=holds, cells=cells, repark_req=None,
                pending_home=pending_home, home_hist=home_hist, session=sessions.get(p_root) or {},
            ))
    return out


def _gate(allowed: bool, reason: str | None = None) -> dict:
    return {"allowed": allowed, "reason": None if allowed else reason}


def _build_failure_entry(state, now: float, *, human_detected: bool, active, dispatch_enabled: bool, root: str,
                         trigger: str, cell_id: str | None, arm_id: str | None, robot_id: str | None,
                         task: dict | None, budgets: dict, holds: dict, cells: dict, repark_req: dict | None,
                         pending_home: dict, home_hist: dict, session: dict, incident_id: str | None = None) -> dict:
    tasks = list((getattr(state, "omx_cell_tasks", None) or {}).values())
    arms = CELL_ARMS.get(cell_id, (arm_id,) if arm_id else ())
    cell_active = bool(cell_id and any(t.get("cell_id") == cell_id and t.get("status") in ("RUNNING", "PAUSED_HUMAN") for t in tasks))
    human_hold = bool(human_detected or any((c or {}).get("phase") == "HUMAN_HOLD" for c in cells.values()))
    in_progress = bool(any(a in pending_home for a in arms))
    cam_meta = camera_snapshot_meta(state, arm_id, now)
    homing_stage = str(session.get("stage") or "IDLE")
    depth = int((task or {}).get("fallback_chain_depth") or 0)

    vetoes: list[str] = []
    if human_hold or (cell_id and (cells.get(cell_id) or {}).get("phase") == "ABORTED"):
        vetoes.append("FLEET_SAFETY_STOP_OR_ABORTED")
    if arm_id and (holds.get(arm_id) or {}).get("held"):
        vetoes.append("ARM_INCIDENT_HELD")
    if any(a != arm_id and (holds.get(a) or {}).get("held") for a in arms):
        vetoes.append("PEER_ARM_LOCKED_OR_HELD")
    if in_progress:
        vetoes.append("AUTO_FOLD_IN_PROGRESS")
    if arm_id and not arm_folded_fresh(state, arm_id, now):
        vetoes.append("OUT_OF_HOME_POSE")
    hw_veto = _hard_hw_veto(state, arm_id, task) if arm_id else None
    if hw_veto and hw_veto not in vetoes:
        vetoes.append(hw_veto)
    if trigger == "REPARK_LIMIT" or (task and task.get("reason") in ("DISPATCH_INTERRUPTED", "TRIP_UNKNOWN")):
        vetoes.append("REPEAT_UNKNOWN_ESCALATION")

    recent_24h = [ts for ts in (home_hist.get(arm_id) or []) if isinstance(ts, (int, float)) and now - ts < 86400.0]
    stage_res = (task or {}).get("stage_result") or {}
    has_fix = bool((isinstance(stage_res, dict) and (stage_res.get("reach_fix") or stage_res.get("zone_fix")))
                   or (repark_req and repark_req.get("need_arm_dxdy_m")))
    repark_done = sum(1 for r in (getattr(state, "repark_done", None) or []) if r.get("root") == root)

    is_omx = bool(arm_id and cell_id)
    homing_strategies: dict[str, dict] = {}
    if not is_omx:
        pk_why = ("HUMAN_HOLD_ACTIVE" if human_hold else "PINKY_DISPATCH_DISABLED" if not dispatch_enabled
                  else "NO_ACTIVE_MAP" if active is None
                  else "RECOVERY_CAP_EXCEEDED" if budgets.get("dispatch_pinky_reroute", 0) >= MAX_RECOVERIES_PER_ROOT
                  else None)
        eligible = {
            "inspect_failure_context": _gate(True), "safe_fold_home": _gate(False, "NO_OMX_ARM_FAILURE"),
            "record_visual_checkpoint": _gate(False, "NO_OMX_ARM_FAILURE"),
            "enqueue_displaced_recovery": _gate(False, "NO_OMX_ARM_FAILURE"),
            "request_repark": _gate(False, "NO_OMX_ARM_FAILURE"),
            "enqueue_vla_act_fallback": _gate(False, "NO_OMX_ARM_FAILURE"),
            "dispatch_pinky_reroute": _gate(pk_why is None, pk_why), "escalate_human": _gate(True),
        }
    else:
        folded = arm_folded_fresh(state, arm_id, now)
        held_any = any((holds.get(a) or {}).get("held") for a in arms)
        all_folded = all(arm_folded_fresh(state, a, now) for a in arms)
        common_block = ("HUMAN_HOLD_ACTIVE" if human_hold else "CELL_TASK_ACTIVE" if cell_active
                        else "AUTO_FOLD_IN_PROGRESS" if in_progress else hw_veto)

        def _cap_why(strat: str) -> str | None:
            if common_block:
                return common_block
            if budgets.get(f"safe_fold_home:{strat}", 0) >= MAX_RECOVERIES_PER_ROOT:
                return "RECOVERY_CAP_EXCEEDED"
            if len(recent_24h) >= MAX_SAFE_HOME_PER_ARM_24H:
                return "SAFE_HOME_CAP_EXCEEDED"
            return None

        staged_entered = (
            homing_stage in ("AWAITING_LIFT_VISUAL_VERIFY", "AFTER_LIFT_VISUAL_CLEAR", "DIRECT_PARK_VISUAL_CLEAR",
                             "AWAITING_PARK_VISUAL_VERIFY", "HOLD_VISUAL_BLOCKED", "HOLD_GUARD_TRIPPED")
            or budgets.get("safe_fold_home:release_and_lift", 0) > 0
            or budgets.get("safe_fold_home:guarded_slow_park", 0) > 0
            or session.get("visual_clear_at") is not None
            or session.get("last_strategy") in ("release_and_lift", "guarded_slow_park")
        )
        af_why = (f"HOMING_LOCKED:{homing_stage}" if staged_entered else
                  (None if folded and incident_id is None else _cap_why("auto_fold")))
        rl_why = (_cap_why("release_and_lift") or ("ARM_ALREADY_FOLDED" if folded else None)
                  or (f"HOMING_LOCKED:{homing_stage}" if homing_stage in (
                      "HOLD_VISUAL_BLOCKED", "HOLD_GUARD_TRIPPED", "AWAITING_LIFT_VISUAL_VERIFY",
                      "AFTER_LIFT_VISUAL_CLEAR", "AWAITING_PARK_VISUAL_VERIFY", "AFTER_PARK_VISUAL_FOLDED") else None))
        vis_clear_ts = session.get("visual_clear_at")
        vis_clear_fresh = (isinstance(vis_clear_ts, (int, float)) and not isinstance(vis_clear_ts, bool)
                           and -5.0 <= (now - vis_clear_ts) <= _VISUAL_CLEAR_MAX_AGE_S)
        sp_why = (_cap_why("guarded_slow_park") or ("ARM_ALREADY_FOLDED" if folded else None)
                  or ("VISUAL_CLEAR_CHECKPOINT_REQUIRED" if (homing_stage not in ("AFTER_LIFT_VISUAL_CLEAR", "DIRECT_PARK_VISUAL_CLEAR") or not vis_clear_fresh) else None)
                  or (None if cam_meta["all_fresh"] else "CAMERA_STALE_OR_MISSING"))
        fh_why = ("HUMAN_HOLD_ACTIVE" if human_hold else None if (folded and homing_stage == "AFTER_PARK_VISUAL_FOLDED")
                  else "FINALIZE_HOME_VISUAL_REQUIRED")
        homing_strategies = {
            "auto_fold": _gate(af_why is None, af_why), "release_and_lift": _gate(rl_why is None, rl_why),
            "guarded_slow_park": _gate(sp_why is None, sp_why), "finalize_home_verify": _gate(fh_why is None, fh_why),
        }
        home_allowed = any(g["allowed"] for g in homing_strategies.values())
        home_why = next((g["reason"] for g in homing_strategies.values() if g["reason"]), None) if not home_allowed else None
        vis_why = ("HUMAN_HOLD_ACTIVE" if human_hold else "AUTO_FOLD_IN_PROGRESS" if in_progress
                   else f"HOMING_LOCKED:{homing_stage}" if homing_stage in ("HOLD_VISUAL_BLOCKED", "HOLD_GUARD_TRIPPED")
                   else None if cam_meta["all_fresh"] else "CAMERA_STALE_OR_MISSING")

        disp_why = vla_why = None
        if trigger == "FOLD_READBACK_MISSING":
            disp_why = vla_why = "PLACEMENT_ALREADY_VERIFIED_HOME_ONLY"
        elif common_block:
            disp_why = vla_why = common_block
        elif depth >= 1:
            disp_why = vla_why = "FALLBACK_DEPTH_EXCEEDED"
        elif held_any or not folded:
            disp_why = vla_why = "ARM_NOT_FOLDED_OR_HELD"
        else:
            if budgets.get("enqueue_displaced_recovery", 0) >= MAX_RECOVERIES_PER_ROOT:
                disp_why = "RECOVERY_CAP_EXCEEDED"
            if budgets.get("enqueue_vla_act_fallback", 0) >= MAX_RECOVERIES_PER_ROOT:
                vla_why = "RECOVERY_CAP_EXCEEDED"

        if disp_why is None and (cell_id, arm_id) != ("cell_s", "arm_s"):
            disp_why = "CELL_S_ONLY"
        if vla_why is None:
            vla_why = act_fallback_refusal(cell_id, task)

        rp_why = ("PLACEMENT_ALREADY_VERIFIED_HOME_ONLY" if trigger == "FOLD_READBACK_MISSING"
                  else common_block if common_block else "NO_REACH_FIX" if not has_fix
                  else "ARM_NOT_FOLDED_OR_HELD" if (held_any or not all_folded)
                  else "REPARK_LIMIT_EXCEEDED" if (repark_done >= pipeline_repark.MAX_REPARK or trigger == "REPARK_LIMIT")
                  else None)

        eligible = {
            "inspect_failure_context": _gate(True),
            "safe_fold_home": _gate(home_allowed, home_why),
            "record_visual_checkpoint": _gate(vis_why is None, vis_why),
            "enqueue_displaced_recovery": _gate(disp_why is None, disp_why),
            "request_repark": _gate(rp_why is None, rp_why),
            "enqueue_vla_act_fallback": _gate(vla_why is None, vla_why),
            "dispatch_pinky_reroute": _gate(False, "PINKY_FAILURE_ONLY"),
            "escalate_human": _gate(True),
        }

    worker_ready = bool(incident_id and bound_home_worker_ready(state, arm_id, now))
    limit_home_tools(eligible, homing_strategies, incident_id, holds.get(arm_id), arm_id, root,
                     getattr(state, "pipeline_homing_sessions", None) or {}, worker_ready)
    needs_human = (
        trigger in ("REVIEW_REQUIRED", "REPARK_LIMIT", "REPARK_FAILED", "PINKY_FAILED", "PINKY_REFUSED")
        or homing_stage in ("HOLD_VISUAL_BLOCKED", "HOLD_GUARD_TRIPPED")
        or not any(eligible[k]["allowed"] for k in ("safe_fold_home", "enqueue_displaced_recovery", "request_repark",
                                                    "enqueue_vla_act_fallback", "dispatch_pinky_reroute"))
    )
    snap = {
        "root_task_id": root, "task_id": (task or {}).get("task_id"), "trigger_code": trigger,
        "cell_id": cell_id, "arm_id": arm_id, "robot_id": robot_id, "status": (task or {}).get("status"),
        "fallback_chain_depth": depth, "vetoes": vetoes, "budgets_used": dict(budgets),
        "folded": bool(arm_id and arm_folded_fresh(state, arm_id, now)),
        "pending_safe_home": in_progress, "homing_stage": homing_stage,
        "camera_sequences": cam_meta["sequences"], "has_fix": has_fix,
    }
    if incident_id:
        snap["incident_id"] = incident_id
        snap["bound_home_worker_ready"] = worker_ready
    return {
        **snap,
        "reason": holds[arm_id]["reason"] if incident_id else (task or {}).get("reason") or ((task or {}).get("receipt") or {}).get("reason"),
        "state": "HUMAN_REQUIRED" if needs_human else "READY",
        "cameras_fresh": cam_meta["all_fresh"],
        "homing_strategies": homing_strategies,
        "eligible_tools": eligible,
        "context_sha256": canonical_sha256(snap),
    }


def cell_quality_key_allowed(app, request, cell_id: str | None) -> bool:
    """Enforce per-cell owner principals for cameras/arm_states when cell owners are registered."""
    from fleet.server.sitemap.pipeline_evidence import cell_owner_principals

    principal_obj = getattr(request.state, "site_principal", None)
    if principal_obj is None or getattr(principal_obj, "role", None) == "operator":
        return True
    extra = set(getattr(app.state, "omx_owner_principals", None) or ())
    any_owners = cell_owner_principals("cell_s") | cell_owner_principals("cell_ab") | extra
    if not any_owners:
        return True
    allowed = (cell_owner_principals(cell_id) if cell_id else any_owners) | extra
    return getattr(principal_obj, "principal_id", None) in allowed


def ensure_clearable_after_homing(state, arms: list[str]) -> None:
    """Block POST /arm-holds/clear unless any started staged homing reached AFTER_PARK_VISUAL_FOLDED/CLEARED."""
    for sess in (getattr(state, "pipeline_homing_sessions", None) or {}).values():
        if isinstance(sess, dict) and sess.get("arm_id") in arms:
            st = sess.get("stage")
            if st and st not in ("IDLE", "AUTO_FOLD_COMPLETED", "AFTER_PARK_VISUAL_FOLDED", "CLEARED"):
                from fastapi import HTTPException

                raise HTTPException(409, detail={"code": "STAGED_HOMING_VISUAL_VERIFY_REQUIRED",
                                                 "arm_id": sess["arm_id"], "stage": st})


def mark_homing_cleared(state, arms: list[str]) -> None:
    for sess in (getattr(state, "pipeline_homing_sessions", None) or {}).values():
        if isinstance(sess, dict) and sess.get("arm_id") in arms and sess.get("stage") == "AFTER_PARK_VISUAL_FOLDED":
            sess["stage"] = "CLEARED"


def cell_quality_recovery_sync(app, request, body: dict, *, human_hold: bool, save_fn, now: float) -> dict:
    """Prune expired/preempted requests first, then apply per-cell owner/operator safe-home acks."""
    from fleet.server.sitemap.pipeline_evidence import cell_owner_principals

    pending_home = getattr(app.state, "pending_safe_home_arms", None)
    fence_held, cur_gen = effective_stop_fence(app.state)
    sessions = getattr(app.state, "pipeline_homing_sessions", None) or {}
    changed = False
    if isinstance(pending_home, dict) and cur_gen is not None:
        for arm_id in [a for a, r in pending_home.items()
                       if not isinstance(r, dict)
                       or (isinstance(r.get("expires_at"), (int, float)) and not isinstance(r.get("expires_at"), bool) and now > float(r["expires_at"]))
                       or r.get("stop_generation") != cur_gen]:
            row = pending_home.pop(arm_id, None) or {}
            root = row.get("root_task_id")
            if root and isinstance(sessions.get(root), dict):
                sessions[root]["stage"] = "SKIPPED"
                sessions[root]["last_error"] = "EXPIRED_OR_STOP_PREEMPTED"
            changed = True

    principal_obj = getattr(request.state, "site_principal", None)
    is_op = principal_obj is None or getattr(principal_obj, "role", None) == "operator"
    pid = getattr(principal_obj, "principal_id", None) if principal_obj is not None else None
    extra_owners = set(getattr(app.state, "omx_owner_principals", None) or ())
    filtered_acks = []
    for raw in body.get("safe_home_acks") or ():
        if not isinstance(raw, dict):
            continue
        cell_id = ARM_CELL.get(str(raw.get("arm_id") or ""))
        allowed_ids = (cell_owner_principals(cell_id) if cell_id else frozenset()) | extra_owners
        if is_op or (pid and pid in allowed_ids):
            filtered_acks.append(raw)
    if apply_safe_home_acks(app.state, filtered_acks, now):
        changed = True
    if changed and not getattr(app.state, "_pipeline_ledger_fault", False):
        save_fn()
    return {} if (human_hold or fence_held or cur_gen is None or getattr(app.state, "_pipeline_ledger_fault", False)) else dict(pending_home or {})
