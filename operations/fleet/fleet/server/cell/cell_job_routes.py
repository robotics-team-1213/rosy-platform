"""Operator recovery routes for a held Cell Job (C4b 1b A3, D-403 §6/§7(h)).

reconcile reads the current step back from the device owner now; resume re-approves a HOLD Job
under the current fence; cancel ends it and releases its claims in one transaction. Resume and
cancel need a named operator (the D-276 site principal model); the Rosy Cell service principal
and viewers are refused like they are for admit.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from .cell_job_store import CellJobStore
from .mission_routes import MissionAdmitRequest, redact_cell_job
from .mission_store import MissionConflict
from .site_auth import SitePrincipal

VIEWER_CLAIM_FIELDS = ("resource_key", "resource_kind", "resource_id", "phase")


def install_cell_job_routes(app, *, cell_job_store: CellJobStore, proposal_store, require_viewer,
                            require_named_operator, operator_guard, read_guard) -> None:
    def refused(exc: Exception) -> HTTPException:
        if isinstance(exc, KeyError):
            return HTTPException(status_code=404, detail={"code": "CELL_JOB_NOT_FOUND"})
        return HTTPException(status_code=409, detail={"code": "CELL_JOB_RECOVERY_REFUSED",
                                                      "message": str(exc)})

    @app.get("/api/fleet/resource-claims", dependencies=read_guard, tags=["fleet-cell-jobs"])
    def resource_claims(principal: SitePrincipal = Depends(require_viewer)) -> dict:
        """Who holds each workcell/pallet/object: a held Job's claims stay visible with their owner.

        Viewers see only which resource is held and its phase. An operator sees a Cell Job claim in full;
        a legacy Mission or Task owner id only its own proposer sees (D-763 4 review).
        """
        operator = principal.permits_site("fleet.operate", {"operator"})

        def full(claim: dict) -> bool:
            if claim["job_status"] is not None:
                return operator
            owner = proposal_store.get(claim["owner_id"]) if claim["owner_kind"] == "mission" else None
            return owner is not None and owner["principal_id"] == principal.principal_id

        return {"claims": [claim if full(claim) else {key: claim[key] for key in VIEWER_CLAIM_FIELDS}
                           for claim in cell_job_store.resource_claims()]}

    @app.post("/api/fleet/cell-jobs/{mission_id}/reconcile", dependencies=operator_guard,
              tags=["fleet-cell-jobs"])
    def cell_job_reconcile(mission_id: str, request: Request,
                           principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        dispatcher = getattr(request.app.state, "cell_job_dispatcher", None)
        if dispatcher is None:
            raise HTTPException(status_code=503, detail={"code": "CELL_JOB_DISPATCHER_DISABLED"})
        try:
            readback = dispatcher.reconcile(mission_id)
        except (KeyError, MissionConflict, ValueError) as exc:
            raise refused(exc) from exc
        return {"readback": readback, "job": redact_cell_job(cell_job_store.get(mission_id), principal)}

    @app.post("/api/fleet/cell-jobs/{mission_id}/resume", dependencies=operator_guard,
              tags=["fleet-cell-jobs"])
    def cell_job_resume(mission_id: str, body: MissionAdmitRequest,
                        principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        try:
            job = cell_job_store.resume(mission_id, actor_id=principal.principal_id,
                                        expected_generation=body.expected_generation)
        except (KeyError, MissionConflict, ValueError) as exc:
            raise refused(exc) from exc
        return {"job": redact_cell_job(job, principal)}

    @app.post("/api/fleet/cell-jobs/{mission_id}/cancel", dependencies=operator_guard,
              tags=["fleet-cell-jobs"])
    def cell_job_cancel(mission_id: str,
                        principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        try:
            job = cell_job_store.cancel(mission_id, actor_id=principal.principal_id)
        except (KeyError, MissionConflict, ValueError) as exc:
            raise refused(exc) from exc
        return {"job": redact_cell_job(job, principal)}


__all__ = ["install_cell_job_routes"]
