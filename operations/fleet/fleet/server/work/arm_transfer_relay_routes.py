"""D-965: a top control unit without an ARM installation relays an app's ARM job to the owning cell.

The relay holds no ARM authority: the cell proposes under this unit's service principal and only the
cell's ARM admit approves. Job and receipt come back as the cell's delegation projection.
"""
from hashlib import sha256
import sqlite3

import httpx
from fastapi import Depends, HTTPException, Request

from core_common.protocol.arm_transfer import ArmActionId
from core_common.protocol.arm_transfer_jobs import ArmTransferJobCreate, ArmTransferJobResponse, ArmTransferRequestKey
from core_common.protocol.arm_transfer_observations import ArmTransferCancelRequest, ArmTransferPhysicalReceiptResponse
from core_common.protocol.control_units import ControlArmWorkRequest
from fleet.swarm.transport import RobotApiError
from .password_session import same_origin


def delegation_id(principal_id, request_key):
    return "arm-" + sha256((principal_id + "\0" + request_key).encode()).hexdigest()[:40]


def install_arm_transfer_relay_routes(app, *, control, require_viewer, require_proposer):
    path = "/api/fleet/arm-transfers/jobs"
    origin = control.unit.unit_id

    def write_origin(request: Request):
        if request.headers.get("origin") is not None and not same_origin(request):
            raise HTTPException(403, detail={"code": "ARM_TRANSFER_JOB_FORBIDDEN"})

    def unavailable(code="ARM_TRANSFER_JOB_UNAVAILABLE"):
        return HTTPException(503, detail={"code": code})

    def target(workcell_id):
        resource = "workcell:" + workcell_id
        for unit in control.topology.units.values():
            if resource in unit.resources and unit.unit_id != origin:
                return unit.unit_id
        raise HTTPException(404, detail={"code": "ARM_TRANSFER_WORKCELL_NOT_DELEGATED"})

    def projected(row):
        reply = control.snapshot(row)
        result = row["result"]
        if reply["stale"] or "job" not in result:
            raise unavailable()
        return result

    def mine(row, principal):
        key = row["request"]["transfer"]["request_key"]
        return row["delegation_id"] == delegation_id(principal.principal_id, key)

    def by_mission(mission_id, principal):
        try:
            rows = control.store.list(limit=1000)
        except sqlite3.Error:
            raise unavailable() from None
        # shortcut: linear scan of the newest 1000 delegations; index result mission IDs if the relay grows past that.
        for row in rows:
            if (row["origin_id"] == origin and "transfer" in row["request"]
                    and row["result"].get("job", {}).get("mission_id") == mission_id):
                if not (mine(row, principal) or principal.role == "operator"):
                    raise HTTPException(403, detail={"code": "ARM_TRANSFER_JOB_FORBIDDEN"})
                return row
        raise HTTPException(404, detail={"code": "ARM_TRANSFER_JOB_NOT_FOUND"})

    async def call(operation):
        try:
            return await operation
        except KeyError:
            raise HTTPException(404, detail={"code": "ARM_TRANSFER_JOB_NOT_FOUND"}) from None
        except ValueError:
            raise HTTPException(409, detail={"code": "ARM_TRANSFER_JOB_CONFLICT"}) from None
        except (ConnectionError, OSError, sqlite3.Error, RobotApiError, httpx.HTTPError):
            raise unavailable() from None

    @app.post(path, response_model=ArmTransferJobResponse, tags=["fleet-work"], dependencies=[Depends(write_origin)])
    async def create(body: ArmTransferJobCreate, principal=Depends(require_proposer)):
        request = ControlArmWorkRequest(delegation_id=delegation_id(principal.principal_id, body.request_key),
                                        target_unit=target(body.workcell_id), transfer=body)
        reply = await call(control.submit(request))
        return {"job": projected(control.store.get(origin, reply["delegation"]["delegation_id"]))["job"]}

    @app.get(path, response_model=ArmTransferJobResponse, tags=["fleet-work"])
    async def read_key(request_key: ArmTransferRequestKey, principal=Depends(require_viewer)):
        try:
            row = control.store.get(origin, delegation_id(principal.principal_id, request_key))
        except KeyError:
            raise HTTPException(404, detail={"code": "ARM_TRANSFER_JOB_NOT_FOUND"}) from None
        except sqlite3.Error:
            raise unavailable() from None
        return {"job": projected(row)["job"]}

    @app.get(path + "/{mission_id}", response_model=ArmTransferJobResponse, tags=["fleet-work"])
    async def read_id(mission_id: ArmActionId, principal=Depends(require_viewer)):
        return {"job": projected(by_mission(mission_id, principal))["job"]}

    @app.get(path + "/{mission_id}/physical-receipt", response_model=ArmTransferPhysicalReceiptResponse,
             tags=["fleet-work"])
    async def receipt(mission_id: ArmActionId, principal=Depends(require_viewer)):
        result = projected(by_mission(mission_id, principal))
        if result.get("receipt") is None:
            raise HTTPException(409, detail={"code": "ARM_TRANSFER_PHYSICAL_RECEIPT_PENDING"})
        return {"receipt": result["receipt"]}

    @app.post(path + "/{mission_id}/cancel", response_model=ArmTransferJobResponse, tags=["fleet-work"],
              dependencies=[Depends(write_origin)])
    async def cancel(mission_id: ArmActionId, body: ArmTransferCancelRequest, principal=Depends(require_proposer)):
        row = by_mission(mission_id, principal)
        if not mine(row, principal):
            raise HTTPException(403, detail={"code": "ARM_TRANSFER_JOB_FORBIDDEN"})
        # The app's reason stays here; the cell records its own cancel reason.
        await call(control.cancel(origin, row["delegation_id"]))
        return {"job": projected(control.store.get(origin, row["delegation_id"]))["job"]}
