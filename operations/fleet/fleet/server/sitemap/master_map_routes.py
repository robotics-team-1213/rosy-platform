"""Fleet <-> CORE bidirectional master-map exchange routes (2026-11-23).

Bridges ``GET /api/v1/map`` (robot SLAM/localization occupancy snapshot -> PGM/YAML
bundle) and ``POST /api/v1/map/site`` (site-aligned master grid upload/activation),
storing one SQLite-persisted master grid bound to the active site map version.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import time
from typing import Annotated, Any, Optional

from fastapi import Depends, Request
import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from fleet.server.http_errors import http_error
from fleet.server.site_auth import SitePrincipal
from fleet.server.site_map_routes import invalid_errors, site_map_error
from fleet.swarm.transport import RobotApiError

MAX_MASTER_GRID_BYTES = 10_000_000
_MAX_PGM_B64 = 8_000_000
_MAX_CELLS = 4096 * 4096
_Coordinate = Annotated[float, Field(allow_inf_nan=False, ge=-1000.0, le=1000.0)]
_PGM_HEADER_RE = re.compile(
    rb"P5(?:[ \t\r\n]+(?:#[^\r\n]*\r?\n[ \t\r\n]*)*|#[^\r\n]*\r?\n[ \t\r\n]*)"
    rb"(\d+)(?:[ \t\r\n]+(?:#[^\r\n]*\r?\n[ \t\r\n]*)*|#[^\r\n]*\r?\n[ \t\r\n]*)"
    rb"(\d+)(?:[ \t\r\n]+(?:#[^\r\n]*\r?\n[ \t\r\n]*)*|#[^\r\n]*\r?\n[ \t\r\n]*)"
    rb"255[ \t\r\n]"
)


class MasterGridUploadBody(BaseModel):
    """Site-aligned yaw=0 master occupancy grid uploaded to Fleet for distribution."""

    model_config = ConfigDict(extra="forbid")

    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    resolution: float = Field(ge=0.005, le=0.2, allow_inf_nan=False)
    origin: list[_Coordinate] = Field(min_length=3, max_length=3)
    occupied_thresh: float = Field(default=0.65, ge=0.65, le=0.99, allow_inf_nan=False)
    free_thresh: float = Field(default=0.196, ge=0.01, le=0.196, allow_inf_nan=False)
    pgm_base64: str = Field(max_length=_MAX_PGM_B64)
    grid_id: Optional[str] = Field(default=None, max_length=64)
    site_map_id: Optional[str] = Field(default=None, max_length=64)
    version: Optional[int] = Field(default=None, ge=0, strict=True)
    source: str = Field(default="", max_length=256)
    alignment: Optional[dict[str, Any]] = None


class MasterMapPushBody(BaseModel):
    """Optional body for pushing the master grid to a robot."""

    model_config = ConfigDict(extra="forbid")

    activate: bool = False


def _clean_zero(value: float) -> float:
    return 0.0 if value == 0.0 else float(value)


def _grid_digest(width: int, height: int, resolution: float, origin: list[float], data: list[int]) -> str:
    payload = json.dumps(
        {
            "width": int(width),
            "height": int(height),
            "resolution": _clean_zero(round(float(resolution), 6)),
            "origin": {
                "x": _clean_zero(float(origin[0])),
                "y": _clean_zero(float(origin[1])),
                "yaw": _clean_zero(float(origin[2])),
            },
            "data": data,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"occupancy:{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:12]}"


def _pgm_to_cells_and_id(
    pgm: bytes, resolution: float, origin: list[float], occ_t: float, free_t: float,
) -> tuple[int, int, str]:
    match = _PGM_HEADER_RE.match(pgm)
    if not match:
        raise ValueError("image is not an 8-bit P5 PGM with maxval 255")
    width, height = int(match[1]), int(match[2])
    pixels = pgm[match.end():]
    if not 0 < width * height <= _MAX_CELLS or len(pixels) != width * height:
        raise ValueError("PGM pixel payload length does not match width x height")
    data: list[int] = []
    for row_idx in range(height - 1, -1, -1):
        start = row_idx * width
        for px in pixels[start:start + width]:
            prob = (255 - px) / 255.0
            if prob > occ_t:
                data.append(100)
            elif prob < free_t:
                data.append(0)
            else:
                data.append(-1)
    return width, height, _grid_digest(width, height, resolution, origin, data)


def _ros_grid_to_bundle(robot_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    width = int(raw["width"])
    height = int(raw["height"])
    raw_data = raw["data"]
    if width < 1 or height < 1 or width * height > _MAX_CELLS or len(raw_data) != width * height:
        raise ValueError("robot map dimensions do not match occupancy data")
    res = _clean_zero(round(float(raw["resolution"]), 6))
    raw_origin = raw.get("origin") or {}
    if isinstance(raw_origin, dict):
        origin = [_clean_zero(float(raw_origin.get(k, 0.0))) for k in ("x", "y", "yaw")]
    elif isinstance(raw_origin, (list, tuple)) and len(raw_origin) == 3:
        origin = [_clean_zero(float(v)) for v in raw_origin]
    else:
        raise ValueError("robot map origin is malformed")
    cells = [100 if int(v) >= 65 else (0 if 0 <= int(v) <= 19 else -1) for v in raw_data]
    px_map = {0: 254, 100: 0, -1: 205}
    top_rows = [
        bytes(px_map[c] for c in cells[r * width:(r + 1) * width])
        for r in range(height - 1, -1, -1)
    ]
    stem = f"robot_{re.sub(r'[^A-Za-z0-9._-]', '_', robot_id)}"
    pgm = f"P5\n# robot {robot_id}\n{width} {height}\n255\n".encode("ascii") + b"".join(top_rows)
    sha = hashlib.sha256(pgm).hexdigest()
    grid_id = _grid_digest(width, height, res, origin, cells)
    return {
        "robot_id": robot_id,
        "map_id": raw.get("map_id"),
        "grid_id": grid_id,
        "width": width,
        "height": height,
        "resolution": res,
        "origin": origin,
        "sha256": sha,
        "pgm_base64": base64.b64encode(pgm).decode("ascii"),
        "yaml": {
            "image": f"{stem}.pgm",
            "mode": "trinary",
            "resolution": res,
            "origin": origin,
            "negate": 0,
            "occupied_thresh": 0.65,
            "free_thresh": 0.196,
        },
    }


class _MasterGridStore:
    """SQLite persistence for the active site map's master occupancy grid."""

    def __init__(self, site_maps) -> None:
        self._db = site_maps._db
        self._lock = site_maps._lock
        self._event = site_maps._event
        self._clock = getattr(site_maps, "clock", time.time)
        with self._lock, self._db:
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS site_master_grids (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    site_map_id TEXT NOT NULL,
                    site_map_version INTEGER NOT NULL,
                    grid_id TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    resolution REAL NOT NULL,
                    origin_json TEXT NOT NULL,
                    occupied_thresh REAL NOT NULL,
                    free_thresh REAL NOT NULL,
                    pgm_base64 TEXT NOT NULL,
                    source TEXT NOT NULL,
                    alignment_json TEXT,
                    uploaded_by TEXT NOT NULL,
                    uploaded_at REAL NOT NULL
                )""")

    def put(
        self, *, site_map_id: str, version: int, body: MasterGridUploadBody,
        width: int, height: int, grid_id: str, principal_id: str,
    ) -> dict[str, Any]:
        res = _clean_zero(round(float(body.resolution), 6))
        origin = [_clean_zero(float(v)) for v in body.origin]
        now = float(self._clock())
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO site_master_grids VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (1, site_map_id, int(version), grid_id, body.sha256, int(width), int(height), res,
                 json.dumps(origin), float(body.occupied_thresh), float(body.free_thresh),
                 body.pgm_base64, body.source,
                 json.dumps(body.alignment) if body.alignment is not None else None,
                 principal_id, now),
            )
            self._event("master_grid_uploaded", principal_id, {
                "site_map_id": site_map_id, "version": int(version),
                "grid_id": grid_id, "sha256": body.sha256,
            })
        return {
            "site_map_id": site_map_id, "version": int(version), "grid_id": grid_id, "sha256": body.sha256,
            "width": int(width), "height": int(height), "resolution": res, "origin": origin,
            "occupied_thresh": float(body.occupied_thresh), "free_thresh": float(body.free_thresh),
            "source": body.source, "alignment": body.alignment, "uploaded_by": principal_id, "uploaded_at": now,
        }

    def get(self, *, site_map_id: str, version: int) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._db.execute(
                "SELECT site_map_id, site_map_version, grid_id, sha256, width, height, resolution, "
                "origin_json, occupied_thresh, free_thresh, pgm_base64, source, alignment_json, "
                "uploaded_by, uploaded_at FROM site_master_grids WHERE id = 1"
            ).fetchone()
        if row is None or row[0] != site_map_id or int(row[1]) != int(version):
            return None
        return {
            "site_map_id": row[0], "version": int(row[1]), "grid_id": row[2], "sha256": row[3],
            "width": int(row[4]), "height": int(row[5]), "resolution": float(row[6]),
            "origin": json.loads(row[7]), "occupied_thresh": float(row[8]), "free_thresh": float(row[9]),
            "pgm_base64": row[10], "source": row[11],
            "alignment": json.loads(row[12]) if row[12] is not None else None,
            "uploaded_by": row[13], "uploaded_at": float(row[14]),
        }


def install_master_map_routes(app, *, console, site_maps, read_guard, require_named_operator) -> None:
    """Register Fleet endpoints for pulling robot maps, hosting the master grid, and pushing to CORE."""
    store = _MasterGridStore(site_maps)

    async def _read_bounded(request: Request) -> bytes:
        declared = request.headers.get("content-length")
        if declared and (len(declared) > 12 or not declared.isdigit() or int(declared) > MAX_MASTER_GRID_BYTES):
            raise site_map_error(413, "SITE_MAP_TOO_LARGE", f"body is limited to {MAX_MASTER_GRID_BYTES} bytes")
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_MASTER_GRID_BYTES:
                raise site_map_error(413, "SITE_MAP_TOO_LARGE", f"body is limited to {MAX_MASTER_GRID_BYTES} bytes")
            chunks.append(chunk)
        return b"".join(chunks)

    def _require_active():
        active = site_maps.active()
        if active is None:
            raise site_map_error(404, "SITE_MAP_NOT_ACTIVE", "activate a site map first")
        return active[1].map_id, int(active[0])

    @app.get("/api/fleet/robots/{robot_id}/map/bundle", dependencies=read_guard, tags=["site-map"])
    async def fleet_robot_map_bundle(robot_id: str) -> dict[str, Any]:
        client = console.clients().get(robot_id)
        if client is None:
            raise site_map_error(404, "UNKNOWN_ROBOT", f"unknown robot: {robot_id}")
        try:
            raw = await client.map()
        except RobotApiError as exc:
            if exc.status == 404:
                raise site_map_error(404, "NO_MAP", "robot has not published an occupancy map yet") from exc
            raise http_error(exc) from exc
        except (OSError, httpx.RequestError) as exc:
            raise http_error(exc) from exc
        if not raw or not raw.get("data") or int(raw.get("width") or 0) < 1 or int(raw.get("height") or 0) < 1:
            raise site_map_error(404, "NO_MAP", "robot has not published an occupancy map yet")
        try:
            return _ros_grid_to_bundle(robot_id, raw)
        except (KeyError, TypeError, ValueError) as exc:
            raise site_map_error(502, "VALIDATION_ERROR", f"robot returned malformed map data: {exc}") from exc

    @app.put("/api/fleet/site-map/master-grid", tags=["site-map"])
    async def fleet_upload_master_grid(
        request: Request, principal: SitePrincipal = Depends(require_named_operator),
    ) -> dict[str, Any]:
        site_map_id, version = _require_active()
        raw_bytes = await _read_bounded(request)
        try:
            body = MasterGridUploadBody.model_validate_json(raw_bytes)
        except ValidationError as exc:
            raise site_map_error(422, "VALIDATION_ERROR", json.dumps(invalid_errors(exc))) from exc
        if abs(float(body.origin[2])) > 1e-6:
            raise site_map_error(422, "VALIDATION_ERROR", "origin yaw must be 0.0 for site-aligned Nav2 map")
        if body.free_thresh >= body.occupied_thresh:
            raise site_map_error(422, "VALIDATION_ERROR", "free_thresh must be below occupied_thresh")
        if body.site_map_id is not None and body.site_map_id != site_map_id:
            raise site_map_error(422, "VALIDATION_ERROR", f"site_map_id does not match active {site_map_id!r}")
        if body.version is not None and body.version != version:
            raise site_map_error(422, "VALIDATION_ERROR", f"version does not match active version {version}")
        try:
            pgm = base64.b64decode(body.pgm_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise site_map_error(422, "VALIDATION_ERROR", "pgm_base64 is not valid base64") from exc
        if hashlib.sha256(pgm).hexdigest() != body.sha256:
            raise site_map_error(422, "VALIDATION_ERROR", "master grid image does not match its sha256")
        try:
            width, height, computed_grid_id = _pgm_to_cells_and_id(
                pgm, body.resolution, [float(v) for v in body.origin], body.occupied_thresh, body.free_thresh,
            )
        except ValueError as exc:
            raise site_map_error(422, "VALIDATION_ERROR", str(exc)) from exc
        if body.grid_id is not None and body.grid_id != computed_grid_id:
            raise site_map_error(422, "VALIDATION_ERROR",
                                 f"grid_id {body.grid_id!r} does not match computed {computed_grid_id!r}")
        return store.put(
            site_map_id=site_map_id, version=version, body=body,
            width=width, height=height, grid_id=computed_grid_id, principal_id=principal.principal_id,
        )

    @app.get("/api/fleet/site-map/master-grid", dependencies=read_guard, tags=["site-map"])
    async def fleet_get_master_grid() -> dict[str, Any]:
        site_map_id, version = _require_active()
        row = store.get(site_map_id=site_map_id, version=version)
        if row is None:
            raise site_map_error(404, "MASTER_GRID_NOT_SET", "no master grid uploaded for the active site map")
        return row

    @app.post("/api/fleet/robots/{robot_id}/master-map/push", tags=["site-map"])
    async def fleet_push_master_map(
        robot_id: str, request: Request, principal: SitePrincipal = Depends(require_named_operator),
    ) -> dict[str, Any]:
        client = console.clients().get(robot_id)
        if client is None:
            raise site_map_error(404, "UNKNOWN_ROBOT", f"unknown robot: {robot_id}")
        site_map_id, version = _require_active()
        row = store.get(site_map_id=site_map_id, version=version)
        if row is None:
            raise site_map_error(404, "MASTER_GRID_NOT_SET", "no master grid uploaded for the active site map")
        raw_body = await _read_bounded(request)
        try:
            body = MasterMapPushBody.model_validate_json(raw_body) if raw_body.strip() else MasterMapPushBody()
        except ValidationError as exc:
            raise site_map_error(422, "VALIDATION_ERROR", json.dumps(invalid_errors(exc))) from exc
        if body.activate:
            if busy := console.trip_refusal([robot_id]):
                raise site_map_error(409, busy.code, f"{robot_id} is on a running trip")
        push = getattr(client, "site_map_push", None)
        if push is None:
            raise site_map_error(501, "SITE_MAP_PUSH_UNSUPPORTED", "robot client does not support site_map_push")
        payload = {
            "map_id": site_map_id,
            "version": version,
            "sha256": row["sha256"],
            "resolution": row["resolution"],
            "origin": row["origin"],
            "occupied_thresh": row["occupied_thresh"],
            "free_thresh": min(float(row["free_thresh"]), 0.196),
            "pgm_base64": row["pgm_base64"],
            "grid_id": row["grid_id"],
            "source": row["source"],
            "alignment": row["alignment"],
            "activate": bool(body.activate),
        }
        try:
            reply = await push(payload)
        except (RobotApiError, OSError, httpx.RequestError) as exc:
            raise http_error(exc) from exc
        with site_maps._lock, site_maps._db:
            site_maps._event("master_grid_pushed", principal.principal_id, {
                "robot_id": robot_id, "grid_id": row["grid_id"], "activate": bool(body.activate),
            })
        return {
            "robot_id": robot_id,
            "site_map_id": site_map_id,
            "version": version,
            "grid_id": row["grid_id"],
            "sha256": row["sha256"],
            "activate": bool(body.activate),
            "robot_reply": reply,
        }
