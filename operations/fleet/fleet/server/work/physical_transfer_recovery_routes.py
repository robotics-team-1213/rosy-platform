"""Simulation recovery requests, independent reset facts and one separately approved child."""
import asyncio
import sqlite3

from fastapi import Depends, HTTPException

from core_common.protocol.arm_transfer import ArmActionId
from core_common.protocol.arm_transfer_jobs import ArmTransferJobResponse
from core_common.protocol.arm_transfer_recovery import (
    ArmTransferRecoveryCreate, ArmTransferRecoveryApprove, ArmTransferRecoveryRequestResponse,
    ArmTransferRecoveryPreviewResponse, ArmTransferRecoveryContextResponse,
    ArmTransferRecoveryObservationRequest, ArmTransferRecoveryObservationReply,
)
from .local_action_transport import LocalActionUnavailable
from .mission_store import MissionConflict
from .physical_transfer_evidence import PhysicalEvidenceRejected
from .physical_transfer_observations import world_observations
from .physical_transfer_recovery_requests import RecoveryRequestService


def install_transfer_recovery_routes(app, *, dispatcher, principals, observer_auth, job_view,
                                     require_viewer, require_proposer, require_named_operator, write_origin):
    def resolve(connection, name):
        sessions = app.state.password_sessions
        if sessions is not None:
            current = sessions.principal_by_id(name, db=connection)
            if current is not None:
                return current
            if sessions.migrated_principal(name, db=connection):
                return None
        return next((p for p in principals.values() if p.principal_id == name), None)

    service = None if dispatcher is None else RecoveryRequestService(dispatcher, resolve_proposer=resolve)

    def installed():
        if service is None:
            raise HTTPException(503, detail={"code": "ARM_TRANSFER_OBSERVER_UNAVAILABLE"})
        return service

    async def call(function):
        try:
            return await asyncio.to_thread(function)
        except KeyError:
            raise HTTPException(404, detail={"code": "ARM_TRANSFER_JOB_NOT_FOUND"}) from None
        except PermissionError:
            raise HTTPException(403, detail={"code": "ARM_TRANSFER_JOB_FORBIDDEN"}) from None
        except (MissionConflict, PhysicalEvidenceRejected):
            raise HTTPException(409, detail={"code": "ARM_TRANSFER_JOB_CONFLICT"}) from None
        except (LocalActionUnavailable, OSError, sqlite3.Error, ValueError):
            raise HTTPException(503, detail={"code": "ARM_TRANSFER_JOB_UNAVAILABLE"}) from None

    path = "/api/fleet/arm-transfers/jobs/{mission_id}/recovery"
    writes = [Depends(write_origin)]

    @app.get(path, response_model=ArmTransferRecoveryPreviewResponse, tags=["fleet-work"])
    async def preview(mission_id: ArmActionId, principal=Depends(require_viewer)):
        current = installed()
        return await call(lambda: {"recovery": current.preview(mission_id, principal)})

    @app.post(path, response_model=ArmTransferRecoveryRequestResponse, tags=["fleet-work"], dependencies=writes)
    async def request(mission_id: ArmActionId, body: ArmTransferRecoveryCreate, principal=Depends(require_proposer)):
        current = installed()
        return await call(lambda: {"request": current.request(mission_id, principal=principal,
            request_key=body.request_key, expected_context_digest=body.expected_context_digest)})

    @app.get("/api/fleet/arm-transfers/recovery-context", response_model=ArmTransferRecoveryContextResponse,
             tags=["fleet-work"])
    async def context(observer=Depends(observer_auth)):
        current = installed()
        return await call(lambda: {"context": current.pending_context()})

    @app.post(path + "/{request_id}/observations", response_model=ArmTransferRecoveryObservationReply,
              tags=["fleet-work"], dependencies=writes)
    async def observe(mission_id: ArmActionId, request_id: ArmActionId, body: ArmTransferRecoveryObservationRequest,
                      observer=Depends(observer_auth)):
        current = installed()
        return await call(lambda: current.observe(mission_id, request_id,
            expected_proposal_digest=body.expected_proposal_digest, observations=world_observations(body.observations),
            authenticated_producer_id=observer.observer.producer_id))

    @app.post(path + "/{request_id}/approve", response_model=ArmTransferJobResponse,
              tags=["fleet-work"], dependencies=writes)
    async def approve(mission_id: ArmActionId, request_id: ArmActionId, body: ArmTransferRecoveryApprove,
                      principal=Depends(require_named_operator)):
        current = installed()
        return await call(lambda: job_view(current.approve(mission_id, request_id, principal=principal,
            **body.model_dump())["job"]))
