"""Independent fact ingress and scoped physical receipt/cancel HTTP routes."""
import asyncio
from contextlib import closing
import sqlite3
import time

from fastapi import Depends, Header, HTTPException, Request

from core_common.protocol.arm_transfer import ArmActionId
from core_common.protocol.arm_transfer_jobs import ArmTransferJobResponse
from core_common.protocol.arm_transfer_observations import (
    ArmTransferObservationContextResponse, ArmTransferObservationRequest, ArmTransferObservationReply,
    ArmTransferPhysicalReceiptResponse, ArmTransferCancelRequest)
from .local_action_transport import LocalActionUnavailable
from .mission_store import MissionConflict
from .physical_transfer_evidence import PhysicalEvidenceRejected


def install_physical_observer_routes(app, *, service, task_store, job_view, require_viewer,
                                     require_proposer, write_origin):
    def installed():
        if service is None:
            raise HTTPException(503, detail={"code": "ARM_TRANSFER_OBSERVER_UNAVAILABLE"})
        return service

    def authenticate(request: Request, x_physical_observation_token: str | None = Header(default=None)):
        current = installed()
        if not current.observer.authenticates(x_physical_observation_token, now=time.time()):
            raise HTTPException(401, detail={"code": "ARM_TRANSFER_OBSERVER_UNAUTHORIZED"})
        if request.method == "POST":
            try:
                request.state.site_api_audit_id = task_store.begin_api_audit(
                    principal_id=current.observer.producer_id, role="service", method="POST", path=request.url.path)
            except (OSError, sqlite3.Error, ValueError):
                raise HTTPException(503, detail={"code": "ARM_TRANSFER_OBSERVER_UNAVAILABLE"}) from None
        return current

    async def call(function):
        try:
            return await asyncio.to_thread(function)
        except KeyError:
            raise HTTPException(404, detail={"code": "ARM_TRANSFER_JOB_NOT_FOUND"}) from None
        except PermissionError:
            raise HTTPException(403, detail={"code": "ARM_TRANSFER_JOB_FORBIDDEN"}) from None
        except (MissionConflict, PhysicalEvidenceRejected):
            raise HTTPException(409, detail={"code": "ARM_TRANSFER_OBSERVATION_CONFLICT"}) from None
        except (LocalActionUnavailable, OSError, sqlite3.Error, ValueError):
            raise HTTPException(503, detail={"code": "ARM_TRANSFER_OBSERVER_UNAVAILABLE"}) from None

    path = "/api/fleet/arm-transfers/jobs/{mission_id}"

    @app.get("/api/fleet/arm-transfers/observation-context", response_model=ArmTransferObservationContextResponse,
             tags=["fleet-work"])
    async def context(current=Depends(authenticate)):
        return await call(lambda: {"context": current.context()})

    @app.post(path + "/observations", response_model=ArmTransferObservationReply, tags=["fleet-work"],
              dependencies=[Depends(write_origin)])
    async def observe(mission_id: ArmActionId, body: ArmTransferObservationRequest, current=Depends(authenticate)):
        def submit():
            current.observe(mission_id, body)
            with closing(current.store._journal._connect()) as connection:
                job = current._job(connection, mission_id)
            return {**job_view(job), "receipt": current.receipt(mission_id)}
        return await call(submit)

    @app.get(path + "/physical-receipt", response_model=ArmTransferPhysicalReceiptResponse, tags=["fleet-work"])
    async def receipt(mission_id: ArmActionId, principal=Depends(require_viewer)):
        current = installed()
        def read():
            if current.store.get(mission_id, principal=principal) is None:
                raise KeyError(mission_id)
            result = current.receipt(mission_id)
            if result is None:
                raise HTTPException(409, detail={"code": "ARM_TRANSFER_PHYSICAL_RECEIPT_PENDING"})
            return {"receipt": result}
        return await call(read)

    @app.post(path + "/cancel", response_model=ArmTransferJobResponse, tags=["fleet-work"],
              dependencies=[Depends(write_origin)])
    async def cancel(mission_id: ArmActionId, body: ArmTransferCancelRequest, principal=Depends(require_proposer)):
        current = installed()
        def withdraw():
            if current.store.get(mission_id, principal=principal) is None:
                raise KeyError(mission_id)
            try:
                current.execution.snapshot(mission_id)
            except KeyError:
                raise MissionConflict("an unprepared proposal has no physical attempt to cancel") from None
            current.dispatcher.cancel(mission_id, reason=body.reason)
            return job_view(current.store.get(mission_id, principal=principal))
        return await call(withdraw)
