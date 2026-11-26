"""Deliver incident-bound commands to compatible owners and mirror their verified clears."""
from fleet.server.sitemap.pipeline_evidence import cell_owner_principals
from core_common.protocol.arm_incident.home_recovery import HOME_RECOVERY_REASON


def verified_hold_reason(hold):
    outbox = hold.get("unsent_outbox")
    if hold.get("fleet_held") is True and type(outbox) is int and outbox == 0 and hold.get("fleet_reason"):
        return hold["fleet_reason"]
    reason = hold.get("local_reason") or hold.get("fleet_reason") or hold.get("reason")
    return "arm hold awaiting Fleet verification" if reason == HOME_RECOVERY_REASON else reason


def sync_home_receipts(app, request, body, human_hold, save, now):
    from fleet.server.pipeline.pipeline_recovery_policy import ARM_CELL, cell_quality_recovery_sync

    record_readiness(app.state, request, body, ARM_CELL, now)
    if "safe_home_acks" in body:
        body["safe_home_acks"] = [ack for ack in body["safe_home_acks"] or ()
                                  if bound_ack_allowed(app.state, request, body, ARM_CELL, ack)]
    pending = cell_quality_recovery_sync(app, request, body, human_hold=human_hold, save_fn=save, now=now)
    if not app.state._pipeline_ledger_fault and mirror_bound_clear(app.state, request, body, ARM_CELL):
        save()
    return deliver_bound(app.state, request, body, ARM_CELL, pending)


def record_readiness(state, request, body, arm_cells, now):
    if not hasattr(state, "bound_home_ready_at"):
        state.bound_home_ready_at = {}
    reported = body.get("incident_bound_home_arms")
    for arm, cell in arm_cells.items():
        if not is_owner(state, request, cell):
            continue
        if body.get("incident_bound_home") is True and isinstance(reported, list) and arm in reported:
            state.bound_home_ready_at[arm] = now
        else:
            state.bound_home_ready_at.pop(arm, None)


def is_owner(state, request, cell):
    principal = getattr(request.state, "site_principal", None)
    owners = cell_owner_principals(cell) | set(getattr(state, "omx_owner_principals", ()) or ())
    return principal is not None and principal.principal_id in owners


def bound_owner(state, request, body, cell):
    return body.get("incident_bound_home") is True and is_owner(state, request, cell)


def deliver_bound(state, request, body, arm_cells, pending):
    return {arm: spec for arm, spec in pending.items()
            if not str(spec.get("root_task_id", "")).startswith("home-recovery:")
            or (arm in arm_cells and isinstance(body.get("incident_bound_home_arms"), list)
                and arm in body["incident_bound_home_arms"] and bound_owner(state, request, body, arm_cells[arm]))}


def bound_ack_allowed(state, request, body, arm_cells, ack):
    if not isinstance(ack, dict) or not isinstance(ack.get("arm_id"), str):
        return False
    arm = ack["arm_id"]
    spec = (getattr(state, "pending_safe_home_arms", None) or {}).get(arm) or {}
    if not str(spec.get("root_task_id", "")).startswith("home-recovery:"):
        return True
    if arm not in arm_cells or not bound_owner(state, request, body, arm_cells[arm]):
        return False
    return ack.get("outcome") != "completed" or (
        bool(spec.get("incident_id")) and ack.get("cleared_incident_id") == spec["incident_id"])


def mirror_bound_clear(state, request, body, arm_cells):
    """A terminal receipt and an independent, empty owner hold readback must agree."""
    changed = False
    reports = body.get("arm_holds")
    sessions = getattr(state, "pipeline_homing_sessions", {}) or {}
    if not isinstance(reports, dict):
        return False
    for ack in body.get("safe_home_acks") or ():
        if not isinstance(ack, dict) or ack.get("outcome") != "completed":
            continue
        arm, incident = ack.get("arm_id"), ack.get("cleared_incident_id")
        if not isinstance(arm, str) or arm not in arm_cells or not isinstance(incident, str) or not incident:
            continue
        if not bound_owner(state, request, body, arm_cells[arm]):
            continue
        root = f"home-recovery:{arm}:{incident}"
        session = sessions.get(root) or {}
        if (session.get("arm_id") != arm or not ack.get("request_id")
                or session.get("active_request_id") != ack["request_id"]):
            continue
        hold, report = state.arm_holds.get(arm) or {}, reports.get(arm)
        if not isinstance(report, dict) or hold.get("incident_ids") != [incident] or hold.get("held") is not True:
            continue
        if (report.get("fleet_held") is not False or report.get("local_held") is not False
                or report.get("incident_ids") != [] or type(report.get("unsent_outbox")) is not int
                or report["unsent_outbox"] != 0):
            continue
        state.arm_holds[arm] = {"arm": arm, "held": False, "reason": None, "incident_ids": []}
        session.update(stage="CLEARED", last_outcome="completed", cleared_incident_id=incident)
        changed = True
    return changed
