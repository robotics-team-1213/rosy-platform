"""Read-only, bounded projection of Task, owner-scoped Mission, trip and Cell Job ledgers (D-664, D-763 4)."""

import asyncio
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Query

from core_common.protocol.schemas import FleetWorkOverview
from fleet.server.console_view import trip_caps
from fleet.server.step_action_kinds import open_kinds, required_approval
from fleet.server.work_read import work_summaries

#: D-763 8: the visible state of a ledger status; an open trip whose wait answer is ``waiting`` shows 기다림.
_SHOWN = {"PROPOSED": "approval_pending",
          **dict.fromkeys(("REQUESTED", "QUEUED", "DISPATCHING", "ACCEPTED", "READY", "RUNNING", "ACTION_SUCCEEDED",
                           "started", "running", "link_wait"), "in_progress"),
          **dict.fromkeys(("HOLD", "UNKNOWN", "FAILED", "EXPIRED", "stopped", "failed"), "intervention"),
          **dict.fromkeys(("GOAL_CONFIRMED", "COMPLETED", "CANCELED", "arrived", "canceled"), "ended")}


def _shown(row: dict) -> dict:
    state = _SHOWN.get(row["status"])
    if state == "in_progress" and (row.get("wait") or {}).get("waiting"):
        state = "waiting"  # past its bound it is a warning on the row, not 개입 (rev 2 Q7)
    if row["status"] == "HOLD" and row["reason"] == "CANCELLED_BY_OPERATOR":
        state = "ended"  # a cancelled or rejected Cell Job (no CANCELLED status, cell_job_store)
    try:
        approval = required_approval(row["action_kind"].split(",")) if state == "approval_pending" else None
    except ValueError:  # an unregistered kind: admit answers APPROVAL_RULE_UNREGISTERED; the list still reads
        approval = None
    return {**row, "visible_state": state, "approval": approval}


def _trip_row(view: dict) -> dict:
    # A closed trip keeps its last wait answer in storage; only an open trip has a wait to show (as f79947c25)
    wait = view.get("wait") if view["state"] in ("started", "running", "link_wait") else None
    return {"source": "trip", "source_id": view["trip_id"], "action_kind": "trip", "status": view["state"],
            "device_id": view["robot_id"], "workcell_id": None, "reason": view.get("reason"),
            "updated_at": datetime.fromtimestamp(view["updated_at"], timezone.utc).isoformat(timespec="milliseconds"),
            "wait": {key: wait.get(key) for key in ("reason", "waiting", "bound_s", "over_bound")} if wait else None}


def install_work_routes(app, *, task_service, mission_service, require_viewer, require_named, read_guard):
    if task_service is not None:
        # D-793: learned-policy governance needs only the task ledger, not the Mission API.
        from fleet.server.policy_governance import PolicyGovernanceStore
        from fleet.server.policy_governance_routes import install_policy_governance_routes
        app.state.policy_governance = PolicyGovernanceStore(task_service.store.path)
        install_policy_governance_routes(app, store=app.state.policy_governance, configured_omx=app.state.omx_instances,
                                         stop_transport=app.state.omx_stop_transport, require_viewer=require_viewer,
                                         require_named_operator=require_named[1])
        # D-891: perception promotion decisions share the governance file and roles; approval deploys nothing.
        from fleet.server.perception_promotion import PerceptionPromotionStore, install_perception_promotion_routes
        install_perception_promotion_routes(app, store=PerceptionPromotionStore(app.state.policy_governance),
                                            require_viewer=require_viewer)

    def named(principal) -> bool:
        try:
            require_named[1](require_named[0](principal))
            return True
        except HTTPException:
            return False

    async def kinds() -> list[str]:
        """D-763 9: only kinds that run here now: a trip needs active-map places and a robot with trip caps."""
        state, found = app.state, []
        active = state.site_maps.active()
        if active is not None and active[1].places:
            shown = await asyncio.gather(*(state.console._shown_capabilities(r) for r in state.console.robot_ids))
            found += ["trip"] if any(trip_caps(caps) is not None for caps in shown) else []
        if (getattr(state, "cell_job_dispatcher", None) is not None and state.omx_instances
                and "CELL_TRANSFER" in open_kinds(state.deployment_profile)):
            found.append("CELL_TRANSFER")
        return found

    def stored(cells, scoped: dict, limit: int) -> tuple[list, list, list]:
        """Every SQLite read of this route (ledgers, stored trips). It runs in a worker thread
        (``asyncio.to_thread``), never on the event loop the trip runner's timing and lease renewal share."""
        rows, truncated = [], []
        for source, service in (("task", task_service), ("mission", mission_service), ("cell_job", cells)):
            if service is None:
                continue
            summaries = work_summaries(service.store, source=source, limit=limit + 1, **scoped.get(source, {}))
            if len(summaries) > limit:
                truncated.append(source)
            rows.extend({"source": source, **row} for row in summaries[:limit])
        return rows, truncated, app.state.site_maps.trips(limit=limit + 1)

    @app.get("/api/fleet/work", dependencies=read_guard,
             response_model=FleetWorkOverview, tags=["fleet-work"])
    async def fleet_work(limit: int = Query(default=50, ge=1, le=100),
                         principal=Depends(require_viewer)) -> dict:
        cells = mission_service if getattr(app.state, "cell_job_store", None) is not None else None
        owner = {"principal_id": principal.principal_id}
        scoped = {"mission": owner, "cell_job": {**owner, "named": named(principal),
                                                 "operator": principal.permits_site("fleet.operate", {"operator"})}}
        # Open trips are copied on the loop (the runner mutates them there); D-517 1: one may be older than the stored ones
        live = {view["trip_id"]: _trip_row(view) for view in app.state.trip_runner.open_trips()}
        rows, truncated, saved = await asyncio.to_thread(stored, cells, scoped, limit)
        trips = {view["trip_id"]: _trip_row(view) for view in saved} | live
        if len(trips) > limit:
            truncated.append("trip")
        rows.extend(sorted(trips.values(), key=lambda row: row["updated_at"], reverse=True)[:limit])
        rows = sorted(map(_shown, rows), key=lambda row: (row["updated_at"], row["source"], row["source_id"]),
                      reverse=True)
        return {"observed_at": datetime.now(timezone.utc).isoformat(), "rows": rows, "kinds": await kinds(),
                "tasks_available": task_service is not None, "missions_available": mission_service is not None,
                "cell_jobs_available": cells is not None, "truncated_sources": truncated}
