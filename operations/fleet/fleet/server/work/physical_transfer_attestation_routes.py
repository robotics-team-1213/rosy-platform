"""D-977 5: named-operator attestation HTTP (device_trial only). A record for Harbor and the cell screen,
never a goal proof, claim release or dispatch authority."""
import asyncio
import sqlite3

from fastapi import Depends, HTTPException

from core_common.protocol.arm_transfer import ArmActionId
from core_common.protocol.arm_transfer_attestation import (
    ArmTransferOperatorAttestationCreate, ArmTransferOperatorAttestationResponse)
from .mission_store import MissionConflict


def install_operator_attestation_routes(app, *, attestations, store, require_viewer, require_named_operator, write_origin):
    path = "/api/fleet/arm-transfers/jobs/{mission_id}/operator-attestations"

    async def call(function):
        try:
            return await asyncio.to_thread(function)
        except KeyError:
            raise HTTPException(404, detail={"code": "ARM_TRANSFER_JOB_NOT_FOUND"}) from None
        except PermissionError:
            raise HTTPException(403, detail={"code": "ARM_TRANSFER_ATTESTATION_FORBIDDEN"}) from None
        except MissionConflict:
            raise HTTPException(409, detail={"code": "ARM_TRANSFER_ATTESTATION_CONFLICT"}) from None
        except (OSError, sqlite3.Error, ValueError):
            raise HTTPException(503, detail={"code": "ARM_TRANSFER_ATTESTATION_UNAVAILABLE"}) from None

    @app.post(path, response_model=ArmTransferOperatorAttestationResponse, tags=["fleet-work"],
              dependencies=[Depends(write_origin)])
    async def attest(mission_id: ArmActionId, body: ArmTransferOperatorAttestationCreate,
                     principal=Depends(require_named_operator)):
        # A named operator only: service and observer credentials never reach this route.
        return await call(lambda: {"attestation": attestations.record(mission_id, principal, body)})

    @app.get(path, tags=["fleet-work"])
    async def read(mission_id: ArmActionId, principal=Depends(require_viewer)):
        def list_():
            if store.get(mission_id, principal=principal) is None:
                raise KeyError(mission_id)
            return {"attestations": [a.model_dump(mode="json") for a in attestations.list(mission_id)]}
        return await call(list_)
