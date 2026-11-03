"""D-965: a top control unit without an ARM installation relays an app's ARM job to the owning cell.

The relay holds no ARM authority: the cell proposes under this unit's service principal and only the
cell's ARM admit approves. Job and receipt come back as the cell's delegation projection; evidence and
rechecks go through the cell's control-unit API for that delegation (peer credentials reach nothing else).
"""
from hashlib import sha256
import sqlite3

import httpx
from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from core_common.protocol.arm_transfer import ArmActionId
from core_common.protocol.arm_transfer_jobs import ArmTransferJobCreate, ArmTransferJobResponse, ArmTransferRequestKey
from core_common.protocol.arm_transfer_observations import ArmTransferCancelRequest, ArmTransferPhysicalReceiptResponse
from core_common.protocol.arm_transfer_recheck import ArmTransferRecheckCreate
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

    def unavailable(row=None):
        detail = {"code": "ARM_TRANSFER_JOB_UNAVAILABLE"}
        if row is not None:  # what this unit last saw, for operators; never a current job state
            detail["last_projection"] = {"status": row["status"], "updated_at": row["updated_at"],
                                         "job_status": row["result"].get("job", {}).get("status")}
        return HTTPException(503, detail=detail)

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
            raise unavailable(row)
        return result

    def mine(row, principal):
        key = row["request"]["transfer"]["request_key"]
        return row["delegation_id"] == delegation_id(principal.principal_id, key)

    def seen(row, principal):
        """At this Fleet the proposer is the app; the cell's own record names this unit's service principal."""
        job = projected(row)["job"]
        return {"job": dict(job, proposal_principal_id=principal.principal_id) if mine(row, principal) else job}

    def by_mission(mission_id, principal, *, own=False):
        try:
            row = control.store.by_result_mission(origin, mission_id)
        except KeyError:
            raise HTTPException(404, detail={"code": "ARM_TRANSFER_JOB_NOT_FOUND"}) from None
        except sqlite3.Error:
            raise unavailable() from None
        if "transfer" not in row["request"] or not (mine(row, principal) or not own and principal.role == "operator"):
            raise HTTPException(403, detail={"code": "ARM_TRANSFER_JOB_FORBIDDEN"})
        return row

    async def call(operation):
        try:
            return await operation
        except KeyError:
            raise HTTPException(404, detail={"code": "ARM_TRANSFER_JOB_NOT_FOUND"}) from None
        except ValueError:
            raise HTTPException(409, detail={"code": "ARM_TRANSFER_JOB_CONFLICT"}) from None
        except (ConnectionError, OSError, sqlite3.Error, RobotApiError, httpx.HTTPError):
            raise unavailable() from None

    async def forward(row, method, tail, body=None):
        if row["owner_unit"] != row["request"]["target_unit"]:
            # shortcut: forwards reach the direct child only; a deeper cell needs each hop to relay too.
            raise HTTPException(409, detail={"code": "ARM_TRANSFER_RELAY_DEPTH"})
        projected(row)
        status, value = await call(control.peer.arm_job(row["owner_unit"], method, origin, row["delegation_id"],
                                                        tail, body))
        return JSONResponse(value, status_code=status)

    @app.post(path, response_model=ArmTransferJobResponse, tags=["fleet-work"], dependencies=[Depends(write_origin)])
    async def create(body: ArmTransferJobCreate, principal=Depends(require_proposer)):
        request = ControlArmWorkRequest(delegation_id=delegation_id(principal.principal_id, body.request_key),
                                        target_unit=target(body.workcell_id), transfer=body,
                                        requested_by=principal.principal_id)
        reply = await call(control.submit(request))
        return seen(control.store.get(origin, reply["delegation"]["delegation_id"]), principal)

    @app.get(path, response_model=ArmTransferJobResponse, tags=["fleet-work"])
    async def read_key(request_key: ArmTransferRequestKey, principal=Depends(require_viewer)):
        try:
            row = control.store.get(origin, delegation_id(principal.principal_id, request_key))
        except KeyError:
            raise HTTPException(404, detail={"code": "ARM_TRANSFER_JOB_NOT_FOUND"}) from None
        except sqlite3.Error:
            raise unavailable() from None
        return seen(row, principal)

    @app.get(path + "/{mission_id}", response_model=ArmTransferJobResponse, tags=["fleet-work"])
    async def read_id(mission_id: ArmActionId, principal=Depends(require_viewer)):
        return seen(by_mission(mission_id, principal), principal)

    @app.get(path + "/{mission_id}/physical-receipt", response_model=ArmTransferPhysicalReceiptResponse,
             tags=["fleet-work"])
    async def receipt(mission_id: ArmActionId, principal=Depends(require_viewer)):
        result = projected(by_mission(mission_id, principal))
        if result.get("receipt") is None:
            raise HTTPException(409, detail={"code": "ARM_TRANSFER_PHYSICAL_RECEIPT_PENDING"})
        return {"receipt": result["receipt"]}

    @app.get(path + "/{mission_id}/physical-evidence", tags=["fleet-work"])
    async def evidence(mission_id: ArmActionId, principal=Depends(require_viewer)):
        return await forward(by_mission(mission_id, principal), "GET", "physical-evidence")

    @app.post(path + "/{mission_id}/rechecks", tags=["fleet-work"], dependencies=[Depends(write_origin)])
    async def request_recheck(mission_id: ArmActionId, body: ArmTransferRecheckCreate,
                              principal=Depends(require_proposer)):
        return await forward(by_mission(mission_id, principal, own=True), "POST", "rechecks",
                             body.model_dump(mode="json"))

    @app.get(path + "/{mission_id}/rechecks/{recheck_key}", tags=["fleet-work"])
    async def read_recheck(mission_id: ArmActionId, recheck_key: ArmTransferRequestKey,
                           principal=Depends(require_viewer)):
        return await forward(by_mission(mission_id, principal), "GET", "rechecks/" + recheck_key)

    @app.post(path + "/{mission_id}/cancel", response_model=ArmTransferJobResponse, tags=["fleet-work"],
              dependencies=[Depends(write_origin)])
    async def cancel(mission_id: ArmActionId, body: ArmTransferCancelRequest, principal=Depends(require_proposer)):
        row = by_mission(mission_id, principal, own=True)
        await call(control.cancel(origin, row["delegation_id"], reason=body.reason))
        return seen(control.store.get(origin, row["delegation_id"]), principal)
