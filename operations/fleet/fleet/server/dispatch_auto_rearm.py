"""Restart auto-rearm (2026-11-27 user decision): a process restart alone is not a human step.

Only a closed gate whose sole reason is this process's own restart reopens, once per start, through the same
rearm route handler an operator uses (so OMX workcell fences rearm and a refusal re-closes dispatch). Unresolved
actions, stop uncertainty, an open arm incident, unanswered owners and every manual close stay closed.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import closing
from typing import Mapping
from types import SimpleNamespace

from fastapi import HTTPException

_LOG = logging.getLogger(__name__)
AUTO_REARM_ACTOR = "system:auto-rearm-after-restart"
AUTO_REARM_REASON = "AUTO_REARM_AFTER_RESTART"
RESTART_CLASS_REASONS = frozenset({"PROCESS_RESTARTED", "STARTUP_HOLD"})
AUTO_REARM_READY_ATTEMPTS = 3
AUTO_REARM_READY_INTERVAL_S = 3.0


def startup_close(connect) -> tuple[bool, str, str]:
    """(auto-rearm eligible, actor, reason) for the startup close, read from the prior control row.

    A manual close (operator stop, e-stop, rearm rollback) keeps its own reason and actor and stays manual.
    """
    with closing(connect()) as connection:
        prior = connection.execute("SELECT dispatch_enabled, reason, actor_id FROM fleet_dispatch_control").fetchone()
    if prior["dispatch_enabled"] or prior["reason"] in RESTART_CLASS_REASONS:
        return True, "system", "PROCESS_RESTARTED"
    return False, prior["actor_id"], prior["reason"]


def rearm_reason(actor_id: str) -> str:
    return AUTO_REARM_REASON if actor_id == AUTO_REARM_ACTOR else "OPERATOR_REARM"


def auto_rearm_pending(store) -> dict | None:
    """The closed control row when the only close reason is this process's restart, else None (once per start)."""
    if not getattr(store, "auto_rearm_eligible", False):
        _LOG.warning("auto rearm after restart skipped: prior close was manual or auto rearm already tried")
        return None
    store.auto_rearm_eligible = False
    control = store.dispatch_control()
    if control["dispatch_enabled"] or control["reason"] != "PROCESS_RESTARTED" or not control["rearm_available"]:
        _LOG.warning("auto rearm after restart skipped: control=%s", control)
        return None
    return control


def install_auto_rearm(app, *, store, configured_omx, stop_targets, stop_transport) -> None:
    """Expose `app.state.auto_rearm_after_restart`; call after the dispatch routes are installed."""
    rearm = next(r.endpoint for r in app.routes if getattr(r, "path", None) == "/api/fleet/dispatch/rearm")

    async def auto_rearm_after_restart() -> dict | None:
        control = auto_rearm_pending(store)
        if control is None:
            return None
        incidents = getattr(app.state, "arm_incidents", None)
        if incidents is None and (stop_targets or configured_omx):
            _LOG.warning("auto rearm after restart skipped: arm incident store missing while OMX owners exist")
            return None

        def incident_blocks(when: str) -> bool:
            try:
                if incidents is not None and incidents.any_hold():
                    _LOG.warning("auto rearm after restart skipped: open arm incident (%s)", when)
                    return True
            except Exception:
                _LOG.exception("auto rearm after restart skipped: arm incident check failed (%s)", when)
                return True
            return False

        if incident_blocks("before readiness"):
            return None
        # The owners read Fleet's live fence while rearming; a refusal from a still-booting owner would roll back
        # to OMX_LOCAL_REARM_FAILED, so rearm only after every owner answers (bounded; else stay closed).
        for attempt in range(AUTO_REARM_READY_ATTEMPTS):
            await asyncio.sleep(AUTO_REARM_READY_INTERVAL_S)
            try:
                states = [await asyncio.to_thread(stop_transport.owner_state, workcell_id=w, instance_id=i)
                          for w, i in stop_targets]
                ready = all(isinstance(s, Mapping) and s.get("status") == 200 for s in states)
            except Exception:
                _LOG.exception("auto rearm readiness probe failed")
                ready = False
            if ready:
                break
            _LOG.warning("auto rearm after restart: owners not ready (attempt %d)", attempt + 1)
        else:
            _LOG.warning("auto rearm after restart skipped: owners never answered; dispatch stays closed")
            return None
        if incident_blocks("after readiness"):  # an incident may land while owners were booting
            return None
        audit_id = store.begin_api_audit(
            principal_id=AUTO_REARM_ACTOR, role="service", method="POST", path="/api/fleet/dispatch/rearm")
        status = 500
        try:
            result = await rearm(SimpleNamespace(expected_generation=control["generation"]),
                                 SimpleNamespace(principal_id=AUTO_REARM_ACTOR))
            status = 200
            return result
        except HTTPException as exc:
            status = exc.status_code
            _LOG.warning("auto rearm after restart refused: %s", exc.detail)
            return None
        finally:
            store.finish_api_audit(audit_id, status_code=status)

    app.state.auto_rearm_after_restart = auto_rearm_after_restart
