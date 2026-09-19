"""core_api_web.api.v1.waypoints — WPT-002 웨이포인트 CRUD."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from core_api_web.api.v1.common import operator, viewer
from core_api_web.api.deps import AuthContext, get_services, CoreServicesLike
from core_features.waypoints.manager import Waypoint


waypoints_router = APIRouter(prefix="/api/v1/waypoints", tags=["waypoints"])


@waypoints_router.get("")
def list_waypoints(_: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    return {"waypoints": [w.model_dump() for w in svc.waypoints.list()]}


@waypoints_router.post("", status_code=201)
def create_waypoint(body: Waypoint, auth: AuthContext = Depends(operator),
                    svc: CoreServicesLike = Depends(get_services)):
    return svc.waypoints.create(body).model_dump()


@waypoints_router.put("/{name}")
def update_waypoint(name: str, body: dict, auth: AuthContext = Depends(operator),
                    svc: CoreServicesLike = Depends(get_services)):
    return svc.waypoints.update(name, body).model_dump()


@waypoints_router.delete("/{name}", status_code=204)
def delete_waypoint(name: str, auth: AuthContext = Depends(operator),
                    svc: CoreServicesLike = Depends(get_services)):
    svc.waypoints.delete(name)
