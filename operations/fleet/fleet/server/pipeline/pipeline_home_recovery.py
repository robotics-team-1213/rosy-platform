"""Bind USB home recovery to the single open incident classified by the cell."""
from __future__ import annotations

import re

from core_common.protocol.arm_incident.home_recovery import HOME_RECOVERY_REASON


def is_home_hold(hold):
    return isinstance(hold, dict) and hold.get("held") is True and hold.get("reason") == HOME_RECOVERY_REASON


def incident_roots(arm_cells, holds):
    for arm, cell in arm_cells.items():
        hold = holds.get(arm)
        if is_home_hold(hold):
            ids = hold.get("incident_ids")
            if (isinstance(ids, list) and len(ids) == 1 and isinstance(ids[0], str)
                    and re.fullmatch(r"[0-9a-f]{32}", ids[0])):
                yield f"home-recovery:{arm}:{ids[0]}", arm, cell, ids[0]


def bound_home_worker_ready(state, arm, now):
    stamp = (getattr(state, "bound_home_ready_at", None) or {}).get(arm)
    return type(stamp) in (int, float) and 0 <= now - stamp <= 30


def limit_home_tools(eligible, strategies, incident_id, hold, arm, root, sessions, worker_ready):
    if not is_home_hold(hold):
        return
    if incident_id is None:
        blocked = {"allowed": False, "reason": "HOME_RECOVERY_INCIDENT_ROOT_REQUIRED"}
        for name in strategies:
            strategies[name] = blocked
        eligible["safe_fold_home"] = eligible["record_visual_checkpoint"] = blocked
        return
    blocked = {"allowed": False, "reason": "INCIDENT_AUTO_FOLD_ONLY"}
    for name in strategies.keys() - {"auto_fold"}:
        strategies[name] = blocked
    for name in eligible.keys() - {"inspect_failure_context", "escalate_human", "safe_fold_home"}:
        eligible[name] = blocked
    for key, session in sessions.items():
        if key != root and isinstance(session, dict) and session.get("arm_id") == arm:
            stage = session.get("stage")
            if stage and stage not in ("IDLE", "SKIPPED", "AUTO_FOLD_COMPLETED", "AFTER_PARK_VISUAL_FOLDED", "CLEARED"):
                strategies["auto_fold"] = {"allowed": False, "reason": f"HOMING_LOCKED:{stage}"}
                break
    if not worker_ready and strategies["auto_fold"]["allowed"]:
        strategies["auto_fold"] = {"allowed": False, "reason": "BOUND_HOME_WORKER_UNAVAILABLE"}
    eligible["safe_fold_home"] = strategies["auto_fold"]
