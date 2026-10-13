"""Read-only, bounded projection of existing Task and owner-scoped Mission ledgers."""

from datetime import datetime, timezone

from fastapi import Depends, Query

from core_common.protocol.schemas import FleetWorkOverview
from fleet.server.work_read import work_summaries


def install_work_routes(app, *, task_service, mission_service, require_viewer, read_guard):
    @app.get("/api/fleet/work", dependencies=read_guard,
             response_model=FleetWorkOverview, tags=["fleet-work"])
    def fleet_work(limit: int = Query(default=50, ge=1, le=100),
                   principal=Depends(require_viewer)) -> dict:
        rows = []
        truncated = []
        for source, service in (("task", task_service), ("mission", mission_service)):
            if service is None:
                continue
            options = {"limit": limit + 1}
            if source == "mission":
                options["principal_id"] = principal.principal_id
            summaries = work_summaries(service.store, source=source, **options)
            if len(summaries) > limit:
                truncated.append(source)
            rows.extend({"source": source, **row} for row in summaries[:limit])
        rows.sort(key=lambda row: (row["updated_at"], row["source"], row["source_id"]), reverse=True)
        return {"observed_at": datetime.now(timezone.utc).isoformat(), "rows": rows,
                "tasks_available": task_service is not None,
                "missions_available": mission_service is not None,
                "truncated_sources": truncated}
