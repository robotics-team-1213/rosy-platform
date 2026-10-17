"""Operator recovery routes for a held Cell Job (C4b 1b A3, D-403 §6/§7(h)).

reconcile reads the current step back from the device owner now; resume re-approves a HOLD Job
under the current fence; cancel ends it and releases its claims in one transaction. Resume and
cancel need a named operator (the D-276 site principal model); the Rosy Cell service principal
and viewers are refused like they are for admit. A multi-arm Job (D-779) resumes every arm and
cancels as a whole through the same routes; reconcile reads back every arm Action in flight.
"""

from __future__ import annotations

from contextlib import closing

from fastapi import Depends, HTTPException, Request

from .cell_arm_store import ArmJobStore
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

    arm_jobs = ArmJobStore(cell_job_store)

    def store_for(mission_id: str):
        job = cell_job_store.get(mission_id)
        return arm_jobs if job is not None and "arms" in job else cell_job_store

    @app.get("/api/fleet/resource-claims", dependencies=read_guard, tags=["fleet-cell-jobs"])
    def resource_claims(principal: SitePrincipal = Depends(require_viewer)) -> dict:
        """Who holds what: a viewer sees resource and phase, an operator a Cell Job claim in full, and a legacy
        Mission or Task owner id only that Mission's proposer (D-763 4 review). Expired reads as None: no purge."""

        def full(claim: dict) -> bool:
            if claim["job_status"] is not None:
                return principal.permits_site("fleet.operate", {"operator"})
            if claim["owner_kind"] != "mission":
                return False
            owner = proposal_store.get_in_transaction(connection, claim["owner_id"])
            return owner is not None and owner["principal_id"] == principal.principal_id
        with closing(proposal_store._connect()) as connection:  # one read connection, no write per row
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
            job = store_for(mission_id).resume(mission_id, actor_id=principal.principal_id,
                                               expected_generation=body.expected_generation)
        except (KeyError, MissionConflict, ValueError) as exc:
            raise refused(exc) from exc
        return {"job": redact_cell_job(job, principal)}

    @app.post("/api/fleet/cell-jobs/{mission_id}/cancel", dependencies=operator_guard,
              tags=["fleet-cell-jobs"])
    def cell_job_cancel(mission_id: str,
                        principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        try:
            job = store_for(mission_id).cancel(mission_id, actor_id=principal.principal_id)
        except (KeyError, MissionConflict, ValueError) as exc:
            raise refused(exc) from exc
        return {"job": redact_cell_job(job, principal)}


__all__ = ["install_cell_job_routes"]
