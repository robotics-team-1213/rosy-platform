"""Control-unit HTTP boundary: neighbor services propose; named humans admit."""

import re

import httpx
from fastapi import Depends, HTTPException

from core_common.protocol.control_units import ControlApproveRequest, ControlIngressRequest, ControlWorkRequest
from fleet.swarm.transport import RobotApiError


def install_control_unit_routes(app, service, *, authorize, require_viewer, require_named_operator):
    prefix = "/api/fleet/control-unit"

    def human(principal=Depends(require_named_operator)):
        if principal.role in {"service", "ai_observer"}:
            raise HTTPException(403, detail={"code": "LOCAL_HUMAN_APPROVAL_REQUIRED"})
        return principal

    def peer_id(principal):
        if principal.role != "service" or not principal.principal_id.startswith("control-unit:"):
            raise HTTPException(403, detail={"code": "CONTROL_UNIT_PEER_REQUIRED"})
        return principal.principal_id[len("control-unit:"):]

    def parent_scope(principal, origin):
        peer = peer_id(principal)
        if peer != service.unit.parent:
            raise HTTPException(403, detail={"code": "CONTROL_UNIT_NOT_DIRECT_PARENT"})
        ancestor = service.topology.unit(peer)
        while ancestor.unit_id != origin and ancestor.parent is not None:
            ancestor = service.topology.unit(ancestor.parent)
        if ancestor.unit_id != origin:
            raise HTTPException(403, detail={"code": "CONTROL_UNIT_ORIGIN_OUTSIDE_SCOPE"})
        return peer

    async def execute(operation):
        try:
            return await operation
        except KeyError:
            raise HTTPException(404, detail={"code": "CONTROL_UNIT_DELEGATION_NOT_FOUND"}) from None
        except ValueError as exc:
            code = str(exc)
            if not re.fullmatch(r"[A-Z_]+", code):
                code = "CONTROL_UNIT_REQUEST_CONFLICT"
            raise HTTPException(409, detail={"code": code}) from None
        except (ConnectionError, OSError, RobotApiError, httpx.RequestError):
            raise HTTPException(503, detail={"code": "CONTROL_UNIT_PEER_UNAVAILABLE"}) from None

    @app.get(prefix)
    async def summary(principal=Depends(require_viewer)):
        if principal.role == "service":
            raise HTTPException(403, detail={"code": "FORBIDDEN"})
        return {"unit_id": service.unit.unit_id, "config_revision": service.topology.revision,
                "parent": service.unit.parent, "resources": sorted(service.unit.resources),
                "children": sorted(unit.unit_id for unit in service.topology.units.values()
                                   if unit.parent == service.unit.unit_id)}

    @app.get(prefix + "/delegations")
    async def listing(principal=Depends(require_viewer)):
        if principal.role == "service":
            raise HTTPException(403, detail={"code": "FORBIDDEN"})
        return {"delegations": [service.reply(row["origin_id"], row["delegation_id"])
                                for row in service.store.list(limit=100)]}

    @app.post(prefix + "/delegations")
    async def submit(body: ControlWorkRequest, principal=Depends(human)):
        return await execute(service.submit(body))

    @app.post(prefix + "/inbox")
    async def inbox(body: ControlIngressRequest, principal=Depends(authorize)):
        parent = parent_scope(principal, body.origin_id)
        return await execute(service.receive(body, parent_id=parent))

    @app.get(prefix + "/delegations/{origin}/{identity}")
    async def read(origin: str, identity: str, principal=Depends(authorize)):
        if principal.role == "service":
            peer = peer_id(principal)
            if peer == service.unit.parent:
                parent_scope(principal, origin)
            else:
                if peer not in {u.unit_id for u in service.topology.units.values()
                                if u.parent == service.unit.unit_id}:
                    raise HTTPException(403, detail={"code": "CONTROL_UNIT_NEIGHBOR_REQUIRED"})
                try:
                    row = service.store.get(origin, identity)
                except KeyError:
                    raise HTTPException(404, detail={"code": "CONTROL_UNIT_DELEGATION_NOT_FOUND"}) from None
                if row["owner_unit"] != peer:
                    raise HTTPException(403, detail={"code": "CONTROL_UNIT_CHILD_READ_OUTSIDE_SCOPE"})
                return await execute(service.read(origin, identity, for_child=peer))
        else:
            require_viewer(principal)
        return await execute(service.read(origin, identity))

    @app.post(prefix + "/delegations/{origin}/{identity}/approve")
    async def approve(origin: str, identity: str, body: ControlApproveRequest, principal=Depends(human)):
        return await execute(service.approve(origin, identity, actor_id=principal.principal_id,
                                              expected_revision=body.expected_revision))

    @app.post(prefix + "/delegations/{origin}/{identity}/cancel")
    async def cancel(origin: str, identity: str, principal=Depends(authorize)):
        if principal.role == "service":
            parent_scope(principal, origin)
        else:
            human(require_named_operator(principal))
        return await execute(service.cancel(origin, identity))
