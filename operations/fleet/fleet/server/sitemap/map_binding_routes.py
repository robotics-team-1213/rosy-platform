"""D-1022 map binding API: read, approve, revoke, and a marker-free proposal from the robot map's walls.

Approval and revocation need a named operator and are site map events. The proposal reads the robot's map
and pose and returns point pairs only; nothing here moves a robot or changes a map. Errors use
``{"detail": {"code", "detail"}}`` like the site map routes.
"""

from __future__ import annotations

from typing import Optional

import base64
import hashlib
import math
import re

import httpx
from fastapi import Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from fleet.localization.map_binding import BindingError, bound_pose, fit_rigid, propose_from_walls
from fleet.localization.wall_grid import build as build_wall_grid
from fleet.server.http_errors import http_error
from fleet.server.site_auth import SitePrincipal
from fleet.server.site_map_routes import site_map_error
from fleet.swarm.transport import RobotApiError

Pair = dict  # {"site": [x, y], "robot": [x, y]}; checked by the store
MAX_MAP_BUNDLE_CELLS = 4096 * 4096


class BindingFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")
    site_map_id: str = Field(min_length=1)
    site_map_version: int = Field(strict=True, ge=1)
    robot_grid_id: str = Field(min_length=1)


class ApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pairs: list[Pair] = Field(min_length=3, max_length=32)
    holdout: list[Pair] = Field(min_length=1, max_length=32)
    expected_frame: BindingFrame | None = None


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


def _map_bundle(robot_id: str, grid: dict) -> dict:
    width, height, cells = grid["width"], grid["height"], grid["data"]
    if (type(width) is not int or type(height) is not int or width <= 0 or height <= 0
            or width * height > MAX_MAP_BUNDLE_CELLS or not isinstance(cells, list)
            or len(cells) != width * height):
        raise ValueError("invalid robot grid dimensions")
    if any(type(cell) is not int or not -1 <= cell <= 100 for cell in cells):
        raise ValueError("invalid occupancy cell")
    resolution = float(grid["resolution"])
    raw_origin = grid["origin"]
    origin = [float(raw_origin[key]) for key in ("x", "y", "yaw")]
    if not math.isfinite(resolution) or resolution <= 0 or not all(map(math.isfinite, origin)):
        raise ValueError("invalid grid resolution or origin")

    # PGM rows run top to bottom. CORE occupancy rows start at the bottom.
    pixels = bytes(0 if cell >= 65 else 254 if 0 <= cell <= 19 else 205
                   for row in range(height - 1, -1, -1)
                   for cell in cells[row * width:(row + 1) * width])
    pgm = f"P5\n{width} {height}\n255\n".encode("ascii") + pixels
    safe_id = re.sub(r"[^A-Za-z0-9._-]", "_", robot_id)
    return {"robot_id": robot_id, "map_id": grid.get("map_id"), "width": width, "height": height,
            "sha256": hashlib.sha256(pgm).hexdigest(), "pgm_base64": base64.b64encode(pgm).decode("ascii"),
            "yaml": {"image": f"robot_{safe_id}.pgm", "mode": "trinary", "resolution": resolution,
                     "origin": origin, "negate": 0, "occupied_thresh": 0.65, "free_thresh": 0.196}}


def install_map_binding_routes(app, *, console, site_maps, read_guard, require_named_operator) -> None:
    bindings = site_maps.map_bindings

    def fail(exc: BindingError, status: int = 409):
        return site_map_error(status, exc.code, str(exc))

    async def state_of(robot_id: str) -> dict:
        state, _ = await console._gather_state(robot_id)
        return state

    @app.get("/api/fleet/robots/{robot_id}/map/bundle", dependencies=read_guard, tags=["site-map"])
    async def robot_map_bundle(robot_id: str) -> dict:
        client = console.clients().get(robot_id)
        if client is None:
            raise site_map_error(404, "UNKNOWN_ROBOT", "robot is not registered")
        try:
            grid = await client.map()
        except RobotApiError as exc:
            if exc.status == 404:
                raise site_map_error(404, "NO_MAP", "robot has no occupancy map") from exc
            if exc.code == "BAD_RESPONSE":
                raise site_map_error(502, "INVALID_ROBOT_MAP", "robot returned an invalid occupancy grid") from exc
            raise http_error(exc) from exc
        except (OSError, httpx.RequestError) as exc:
            raise http_error(exc) from exc
        if grid is None or grid == {}:
            raise site_map_error(404, "NO_MAP", "robot has no occupancy map")
        try:
            return _map_bundle(robot_id, grid)
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise site_map_error(502, "INVALID_ROBOT_MAP", "robot returned an invalid occupancy grid") from exc

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
            cam = service.arbitrated_pose(robot_id) if service is not None else None  # D-989: the trip-only pose stays in the trip runner
            if cam is not None and cam.x is not None and cam.y is not None:
                body["camera_site_pose"] = {"x": cam.x, "y": cam.y, "yaw": cam.yaw, "state": cam.state}
                body["slam_camera_gap_m"] = math.hypot(bx - cam.x, by - cam.y)
        return body

    @app.get("/api/fleet/site-map/wall-grid", dependencies=read_guard, tags=["map-binding"])
    def site_map_wall_grid() -> dict:
        """The active site map's walls as a Nav2 map in the site frame: a fallback a robot can localize on (read-only)."""
        active = site_maps.active()
        if active is None:
            raise site_map_error(404, "SITE_MAP_NOT_ACTIVE", "activate a site map first")
        if not active[1].walls:
            raise site_map_error(404, "SITE_MAP_NO_WALLS", "the active site map has no walls")
        built = build_wall_grid(active[1].map_id, active[0], [w.face for w in active[1].walls])
        pgm = built.pop("pgm")
        return {**built, "pgm_base64": base64.b64encode(pgm).decode("ascii")}

    @app.post("/api/fleet/robots/{robot_id}/map-binding", tags=["map-binding"])
    async def map_binding_approve(robot_id: str, body: ApproveRequest,
                                  principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        state = await state_of(robot_id)
        site = _site(site_maps)
        if site is None:
            raise site_map_error(409, "SITE_MAP_NOT_ACTIVE", "activate a site map first")
        expected = body.expected_frame
        if expected is not None:
            if site != (expected.site_map_id, expected.site_map_version):
                raise site_map_error(409, "MAP_BINDING_SITE_CHANGED", "samples belong to a different site map revision")
            if state.get("map_grid_id") != expected.robot_grid_id:
                raise site_map_error(409, "MAP_BINDING_GRID_CHANGED", "samples belong to a different robot grid")
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
