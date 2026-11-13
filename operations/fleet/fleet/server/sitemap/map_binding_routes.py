"""D-1022 map binding API: read, approve, revoke, and a marker-free proposal from the robot map's walls.

Approval and revocation need a named operator and are site map events. The proposal reads the robot's map
and pose and returns point pairs only; nothing here moves a robot or changes a map. Errors use
``{"detail": {"code", "detail"}}`` like the site map routes.
"""

from __future__ import annotations

from typing import Optional

import math

from fastapi import Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from fleet.localization.map_binding import BindingError, bound_pose, fit_rigid, propose_from_walls
from fleet.server.site_auth import SitePrincipal
from fleet.server.site_map_routes import site_map_error

Pair = dict  # {"site": [x, y], "robot": [x, y]}; checked by the store


class ApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pairs: list[Pair] = Field(min_length=3, max_length=32)
    holdout: list[Pair] = Field(min_length=1, max_length=32)


class ProposeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: Where the robot stands now on the site map (its bay, a taped start); only picks the 0/180 degree fit.
    seed_site: tuple[float, float]
    #: (min_x, min_y, max_x, max_y) of the arena; default: the bounding box of the active site map's walls.
    arena: Optional[tuple[float, float, float, float]] = None


def _site(site_maps) -> Optional[tuple[str, int]]:
    active = site_maps.active()
    return None if active is None else (active[1].map_id, active[0])


def _arena(site_maps) -> Optional[tuple[float, float, float, float]]:
    active = site_maps.active()
    if active is None or not active[1].walls:
        return None
    xs = [p[0] for wall in active[1].walls for p in wall.face]
    ys = [p[1] for wall in active[1].walls for p in wall.face]
    return (min(xs), min(ys), max(xs), max(ys))


def _occupied(grid: dict) -> list[tuple[float, float]]:
    res, width = float(grid["resolution"]), int(grid["width"])
    origin = grid.get("origin") or {}
    ox, oy, oyaw = (float(origin.get(k, 0.0)) for k in ("x", "y", "yaw"))
    c, s = math.cos(oyaw), math.sin(oyaw)
    cells = [((i % width + 0.5) * res, (i // width + 0.5) * res)
             for i, v in enumerate(grid["data"]) if v is not None and v >= 65]
    return [(ox + c * gx - s * gy, oy + s * gx + c * gy) for gx, gy in cells]  # origin.yaw rotates the grid


def install_map_binding_routes(app, *, console, site_maps, read_guard, require_named_operator) -> None:
    bindings = site_maps.map_bindings

    def fail(exc: BindingError, status: int = 409):
        return site_map_error(status, exc.code, str(exc))

    async def state_of(robot_id: str) -> dict:
        state, _ = await console._gather_state(robot_id)
        return state

    @app.get("/api/fleet/robots/{robot_id}/map-binding", dependencies=read_guard, tags=["map-binding"])
    async def map_binding_read(robot_id: str, request: Request) -> dict:
        try:
            state = await state_of(robot_id)
        except Exception:  # a robot that does not answer still shows its binding
            state = {}
        fit, reason = bindings.matching_fit(robot_id, state, _site(site_maps))
        body = {"active": bindings.active(robot_id), "history": bindings.history(robot_id),
                "matches": reason == "", "reason": reason or None,
                "robot_grid_id": state.get("map_grid_id")}
        pose = state.get("pose") or {}
        if fit is not None and all(isinstance(pose.get(k), (int, float)) for k in ("x", "y", "yaw")):
            # The robot's own SLAM pose in site coordinates beside the camera's: read-only, it moves nothing.
            bx, by, byaw = bound_pose(fit, (pose["x"], pose["y"], pose["yaw"]))
            body["slam_site_pose"] = {"x": bx, "y": by, "yaw": byaw}
            service = getattr(request.app.state, "map_pose", None)
            cam = service.arbitrated_pose(robot_id) if service is not None else None  # D-989: driving_pose is trip-only
            if cam is not None and cam.x is not None and cam.y is not None:
                body["camera_site_pose"] = {"x": cam.x, "y": cam.y, "yaw": cam.yaw, "state": cam.state}
                body["slam_camera_gap_m"] = math.hypot(bx - cam.x, by - cam.y)
        return body

    @app.post("/api/fleet/robots/{robot_id}/map-binding", tags=["map-binding"])
    async def map_binding_approve(robot_id: str, body: ApproveRequest,
                                  principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        site = _site(site_maps)
        if site is None:
            raise site_map_error(409, "SITE_MAP_NOT_ACTIVE", "activate a site map first")
        state = await state_of(robot_id)  # one read: the grid bound is the grid these pairs were measured on
        try:
            return bindings.approve(robot_id, state, site, body.pairs, body.holdout, principal.principal_id)
        except BindingError as exc:
            raise fail(exc) from exc

    @app.delete("/api/fleet/robots/{robot_id}/map-binding", tags=["map-binding"])
    def map_binding_revoke(robot_id: str, reason: str = "revoked",
                           principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        return {"revoked": bindings.revoke(robot_id, principal.principal_id, reason)}

    @app.post("/api/fleet/robots/{robot_id}/map-binding/propose", dependencies=read_guard, tags=["map-binding"])
    async def map_binding_propose(robot_id: str, body: ProposeRequest) -> dict:
        arena = body.arena or _arena(site_maps)
        if arena is None:
            raise site_map_error(422, "ARENA_REQUIRED", "the active site map has no walls; give the arena")
        state = await state_of(robot_id)
        pose = state.get("pose") or {}
        loc = state.get("localization") or {}
        if loc.get("state") != "LOCALIZED" or not all(isinstance(pose.get(k), (int, float)) for k in ("x", "y")):
            raise site_map_error(409, "ROBOT_NOT_LOCALIZED", "the robot must be LOCALIZED in its map frame")
        grid = await console._client(robot_id).map()
        if not grid:
            raise site_map_error(409, "NO_WALLS", "the robot has no map loaded")
        try:
            robot, site = propose_from_walls(_occupied(grid), arena, seed_robot=(pose["x"], pose["y"]),
                                             seed_site=body.seed_site)
            fit = fit_rigid(robot, site)  # a preview only: approval judges again with a held-out pair
        except BindingError as exc:
            raise fail(exc, 422) from exc
        return {"pairs": [{"site": list(s), "robot": list(r)} for r, s in zip(robot, site)],
                "preview": {"yaw": fit.yaw, "tx": fit.tx, "ty": fit.ty},
                "robot_grid_id": state.get("map_grid_id"),
                "note": "add at least one held-out pair measured on the floor, then approve"}
