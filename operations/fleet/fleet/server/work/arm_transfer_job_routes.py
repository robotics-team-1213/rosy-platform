"""Installed simulation proposal/admission HTTP; no Action submission or claim release."""
import asyncio
import sqlite3
import time

from fastapi import Depends, HTTPException, Request

from core_common.protocol.arm_transfer import ArmActionId, ArmTransferCapability
from core_common.protocol.arm_transfer_jobs import (
    ArmTransferRequest, ArmTransferRequestKey, ArmTransferJobCreate, ArmTransferJobAdmit, ArmTransferJobResponse,
)
from .local_action_transport import LocalActionUnavailable, UnixLocalActionTransport
from .mission_store import MissionConflict
from .physical_transfer_store import PhysicalTransferStore
from .password_session import same_origin


def _view(job):
    fields = ("mission_id", "proposal_principal_id", "request_key", "request_digest", "proposal_digest",
              "status", "authority_epoch", "dispatch_generation", "approved_by", "reason")
    return {"job": {**{key: job[key] for key in fields}, "action_kind": "ARM_TRANSFER",
                    "transfer": job["request"],
                    "resource_policy_digest": job["installation"]["capabilities"][0]["resource_policy_digest"]}}


def install_arm_transfer_job_routes(app, *, installation, deployment_profile, journal_path, transport,
                                    socket_root, require_proposer, require_viewer, require_named_operator):
    store = reader = None
    if installation is not None:
        if deployment_profile != "simulation":
            raise ValueError("ARM transfer HTTP requires the simulation profile")
        if journal_path is None:
            raise ValueError("ARM transfer HTTP requires the shared Mission and API audit journal")
        reader = transport if transport is not None else UnixLocalActionTransport(socket_root)
        if not callable(getattr(reader, "transfer_capability", None)):
            raise ValueError("ARM transfer HTTP requires a capability SDK reader")
        store = PhysicalTransferStore(journal_path, installation=installation, deployment_profile=deployment_profile)
    app.state.arm_transfer_job_store = store

    def installed_store():
        if store is None:
            raise HTTPException(503, detail={"code": "ARM_TRANSFER_JOB_UNAVAILABLE"})
        return store

    async def call(function):
        try:
            result = await asyncio.to_thread(function)
            return ArmTransferJobResponse.model_validate(result)
        except KeyError:
            raise HTTPException(404, detail={"code": "ARM_TRANSFER_JOB_NOT_FOUND"}) from None
        except PermissionError:
            raise HTTPException(403, detail={"code": "ARM_TRANSFER_JOB_FORBIDDEN"}) from None
        except MissionConflict:
            raise HTTPException(409, detail={"code": "ARM_TRANSFER_JOB_CONFLICT"}) from None
        except (LocalActionUnavailable, OSError, sqlite3.Error, ValueError):
            raise HTTPException(503, detail={"code": "ARM_TRANSFER_JOB_UNAVAILABLE"}) from None

    path = "/api/fleet/arm-transfers/jobs"

    def write_origin(request: Request):
        if request.headers.get("origin") is not None and not same_origin(request):
            raise HTTPException(403, detail={"code": "ARM_TRANSFER_JOB_FORBIDDEN"})

    @app.post(path, response_model=ArmTransferJobResponse, tags=["fleet-work"], dependencies=[Depends(write_origin)])
    async def create(body: ArmTransferJobCreate, principal=Depends(require_proposer)):
        rows = installed_store()
        request = ArmTransferRequest.model_validate(body.model_dump(exclude={"request_key"}))
        return await call(lambda: _view(rows.create(principal=principal, request_key=body.request_key, request=request)))

    @app.get(path, response_model=ArmTransferJobResponse, tags=["fleet-work"])
    async def read_key(request_key: ArmTransferRequestKey, principal=Depends(require_viewer)):
        rows = installed_store()
        def read():
            job = rows.get_by_request_key(request_key, principal=principal)
            if job is None:
                raise KeyError(request_key)
            return _view(job)
        return await call(read)

    @app.get(path + "/{mission_id}", response_model=ArmTransferJobResponse, tags=["fleet-work"])
    async def read_id(mission_id: ArmActionId, principal=Depends(require_viewer)):
        rows = installed_store()
        def read():
            job = rows.get(mission_id, principal=principal)
            if job is None:
                raise KeyError(mission_id)
            return _view(job)
        return await call(read)

    @app.post(path + "/{mission_id}/admit", response_model=ArmTransferJobResponse, tags=["fleet-work"],
              dependencies=[Depends(write_origin)])
    async def admit(mission_id: ArmActionId, body: ArmTransferJobAdmit, principal=Depends(require_named_operator)):
        rows = installed_store()
        def approve():
            job = rows.get(mission_id, principal=principal)
            if job is None:
                raise KeyError(mission_id)
            if job["proposal_principal_id"] == principal.principal_id:
                raise PermissionError("proposer cannot approve itself")
            observed_at = time.time_ns()
            capabilities = []
            for participant in rows.installation.policy.participants:
                cap = ArmTransferCapability.model_validate(reader.transfer_capability(
                    participant.instance_id, workcell_id=participant.workcell_id))
                if (cap.workcell_id, cap.instance_id) != (participant.workcell_id, participant.instance_id):
                    raise LocalActionUnavailable("capability targets a different participant")
                capabilities.append(cap)
            return _view(rows.admit(mission_id, principal=principal,
                expected_proposal_digest=body.expected_proposal_digest, expected_generation=body.expected_generation,
                capabilities=tuple(capabilities), capabilities_observed_at_ns=observed_at))
        return await call(approve)
