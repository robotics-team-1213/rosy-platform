"""D-856 authenticated simulation planning; does not install a dispatcher."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import Depends, HTTPException

from core_common.protocol.schemas import ArmTransferCheckRequest, ArmTransferCheckResult, ArmTransferCheckResponse

from .local_action_transport import ArmPreflightRejected, UnixLocalActionTransport


def install_arm_transfer_preflight_routes(app, *, instances, deployment_profile, transport,
                                         socket_root, require_proposer):
    installed = dict(instances)
    reader = transport if transport is not None else UnixLocalActionTransport(socket_root)

    @app.post("/api/fleet/arm-transfers/preflight", response_model=ArmTransferCheckResponse, tags=["fleet-work"])
    async def check_transfer(request: ArmTransferCheckRequest, principal=Depends(require_proposer)):
        if deployment_profile != "simulation":
            raise HTTPException(503, detail={"code": "ARM_PREFLIGHT_CLOSED"})
        if installed.get(request.workcell_id) != request.instance_id:
            raise HTTPException(404, detail={"code": "ARM_PREFLIGHT_TARGET_UNAVAILABLE"})
        try:
            result = ArmTransferCheckResult.model_validate(await asyncio.to_thread(reader.check_transfer, request))
            if result.request != request:
                raise ValueError("preflight facts do not match this request")
        except ArmPreflightRejected as exc:
            raise HTTPException(exc.status, detail={"code": exc.code, "reason": exc.reason}) from None
        except Exception:
            raise HTTPException(503, detail={"code": "ARM_PREFLIGHT_UNAVAILABLE"}) from None
        return {"check": result, "received_at": datetime.now(timezone.utc)}
