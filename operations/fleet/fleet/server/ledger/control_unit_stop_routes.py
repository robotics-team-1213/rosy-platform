"""Explicit parent grants and named local operators for durable stop requests."""

import asyncio
import re
import sqlite3

from fastapi import Depends, HTTPException

from core_common.protocol.integrated_control import ControlStopIngress, ControlStopReconcile, ControlStopRequest


def install_control_stop_routes(app, service, *, authorize, require_viewer, require_named_operator):
    prefix = "/api/fleet/control-unit"

    def human(principal=Depends(require_named_operator)):
        if principal.role in {"service", "ai_observer"}:
            raise HTTPException(403, detail={"code": "LOCAL_HUMAN_APPROVAL_REQUIRED"})
        return principal

    def parent(principal, origin):
        if (not service.config.accept_parent_stop or service.unit.parent is None
                or principal.role != "service"
                or principal.principal_id != "control-unit:" + service.unit.parent):
            raise HTTPException(403, detail={"code": "CONTROL_UNIT_PARENT_STOP_NOT_ENABLED"})
        ancestor = service.config.topology.unit(service.unit.parent)
        while ancestor.unit_id != origin and ancestor.parent is not None:
            ancestor = service.config.topology.unit(ancestor.parent)
        if ancestor.unit_id != origin:
            raise HTTPException(403, detail={"code": "CONTROL_UNIT_ORIGIN_OUTSIDE_SCOPE"})

    async def execute(operation):
        try:
            return await operation
        except KeyError:
            raise HTTPException(404, detail={"code": "CONTROL_UNIT_STOP_NOT_FOUND"}) from None
        except sqlite3.Error:
            raise HTTPException(503, detail={"code": "CONTROL_UNIT_JOURNAL_UNAVAILABLE"}) from None
        except (ValueError, RuntimeError) as exc:
            code = str(exc)
            if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}", code):
                code = "CONTROL_UNIT_STOP_CONFLICT"
            raise HTTPException(409, detail={"code": code}) from None
        except (OSError, asyncio.TimeoutError):
            raise HTTPException(503, detail={"code": "CONTROL_UNIT_STOP_UNAVAILABLE"}) from None

    @app.post(prefix + "/stops")
    async def submit(body: ControlStopRequest, principal=Depends(human)):
        return await execute(service.submit(body, actor_id=principal.principal_id))

    @app.post(prefix + "/stop-inbox")
    async def inbox(body: ControlStopIngress, principal=Depends(authorize)):
        parent(principal, body.origin_id)
        return await execute(service.receive(body, actor_id=principal.principal_id))

    @app.get(prefix + "/stops")
    async def history(principal=Depends(require_viewer)):
        if principal.role in {"service", "ai_observer"}:
            raise HTTPException(403, detail={"code": "LOCAL_VIEWER_REQUIRED"})
        return await execute(asyncio.to_thread(service.store.history))

    @app.get(prefix + "/stops/{origin}/{identity}")
    async def read(origin: str, identity: str, principal=Depends(authorize)):
        if principal.role == "service":
            parent(principal, origin)
        else:
            require_viewer(principal)
        return await execute(service.read(origin, identity))

    @app.post(prefix + "/stops/{origin}/{identity}/reconcile")
    async def reconcile(origin: str, identity: str, body: ControlStopReconcile, principal=Depends(human)):
        return await execute(service.reconcile(origin, identity, body, actor_id=principal.principal_id))
