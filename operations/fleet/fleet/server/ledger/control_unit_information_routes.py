"""Local viewers and explicitly enabled direct-parent information readers."""

import asyncio
import sqlite3

import httpx
from fastapi import Depends, HTTPException


def install_control_information_routes(app, collection, *, authorize, require_viewer):
    prefix = "/api/fleet/control-unit"

    def reader(principal=Depends(authorize)):
        if principal.role == "service":
            if (not collection.config.share_information_with_parent
                    or collection.unit.parent is None
                    or principal.principal_id != "control-unit:" + collection.unit.parent):
                raise HTTPException(403, detail={"code": "CONTROL_UNIT_PARENT_INFORMATION_NOT_ENABLED"})
        else:
            require_viewer(principal)
        return principal

    def scope(unit_id):
        if unit_id not in collection.scope:
            raise HTTPException(404, detail={"code": "CONTROL_UNIT_NOT_FOUND"})

    async def execute(operation):
        try:
            return await operation
        except ValueError:
            raise HTTPException(503, detail={"code": "CONTROL_UNIT_INVALID_INFORMATION"}) from None
        except (OSError, sqlite3.Error, httpx.HTTPError, asyncio.TimeoutError):
            raise HTTPException(503, detail={"code": "CONTROL_UNIT_INFORMATION_UNAVAILABLE"}) from None

    @app.get(prefix + "/overview")
    async def overview(principal=Depends(reader)):
        await collection.refresh_local()
        return collection.overview()

    @app.get(prefix + "/units/{unit_id}")
    async def detail(unit_id: str, principal=Depends(reader)):
        scope(unit_id)
        return await execute(collection.detail(unit_id))

    @app.get(prefix + "/units/{unit_id}/map")
    async def map_snapshot(unit_id: str, principal=Depends(reader)):
        scope(unit_id)
        result = await execute(collection.map(unit_id))
        if result is None:
            raise HTTPException(404, detail={"code": "CONTROL_UNIT_NO_ACTIVE_MAP"})
        return result
