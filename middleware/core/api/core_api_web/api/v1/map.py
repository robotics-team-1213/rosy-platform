"""core_api_web.api.v1.map — MAP-003 점유맵·코스트맵 스냅샷 조회 및 site-map 교환."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from core_api_web.api.v1.common import robot_still, viewer
from core_api_web.api.deps import AuthContext, CoreServicesLike, Mode, get_services, valid_costmap_scope
from core_api_web.api.errors import ApiError
from core_api_web.api.grants import LOCALIZE_ASSIST, require_grant
from core_api_web.api.host_agent_client import HostAgentClient
from core_common.protocol.schemas import NavigationState


map_router = APIRouter(prefix="/api/v1/map", tags=["map"])
assist = require_grant(LOCALIZE_ASSIST)
_BOOT_ID = Path("/proc/sys/kernel/random/boot_id")
_MAX_PGM_B64 = 8_000_000
_MAX_CELLS = 4096 * 4096
_SITE_MAP_LOCK = threading.Lock()
_STALE_VELOCITY_S = 0.5
_ACTIVATE_POLL_S = 0.25
_ACTIVATE_WAIT_S = 25.0
_PGM_HEADER_RE = re.compile(
    rb"P5(?:[ \t\r\n]+(?:#[^\r\n]*\r?\n[ \t\r\n]*)*|#[^\r\n]*\r?\n[ \t\r\n]*)"
    rb"(\d+)(?:[ \t\r\n]+(?:#[^\r\n]*\r?\n[ \t\r\n]*)*|#[^\r\n]*\r?\n[ \t\r\n]*)"
    rb"(\d+)(?:[ \t\r\n]+(?:#[^\r\n]*\r?\n[ \t\r\n]*)*|#[^\r\n]*\r?\n[ \t\r\n]*)"
    rb"255[ \t\r\n]"
)
_Coordinate = Annotated[float, Field(allow_inf_nan=False, ge=-1000.0, le=1000.0)]


class SiteMapBundleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    map_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    version: int = Field(ge=0, strict=True)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    resolution: float = Field(ge=0.005, le=0.2, allow_inf_nan=False)
    origin: list[_Coordinate] = Field(min_length=3, max_length=3)
    occupied_thresh: float = Field(default=0.65, ge=0.65, le=0.99, allow_inf_nan=False)
    free_thresh: float = Field(default=0.196, ge=0.01, le=0.196, allow_inf_nan=False)
    pgm_base64: str = Field(max_length=_MAX_PGM_B64)
    grid_id: Optional[str] = Field(default=None, max_length=64)
    source: str = Field(default="", max_length=256)
    alignment: Optional[dict[str, Any]] = None
    activate: bool = False


def _host_agent(svc: CoreServicesLike):
    injected = getattr(svc, "host_agent", None)
    if injected is not None:
        return injected
    host_cfg = (svc.config or {}).get("host_agent", {})
    return HostAgentClient(
        socket_path=host_cfg.get("socket_path", "/run/rosy/host-agent.sock"),
        timeout_s=float(host_cfg.get("timeout_s", 5.0)),
    )


def _atomic_core_file(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        temp.write_bytes(data)
        os.chmod(temp, 0o644)
        os.replace(temp, path)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def _raise_host_error(reply: Any, default_code: str, default_detail: str) -> None:
    raise ApiError(
        reply.code or default_code,
        409 if reply.reachable else 503,
        reply.detail or default_detail,
    )


@map_router.get("")
def current_map(_: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    grid = svc.maps.get_map()
    if grid is None:
        raise ApiError("NOT_FOUND", 404, "no occupancy map received yet")
    return {"map_id": svc.state.map_id, **grid}


@map_router.get("/costmap")
def costmap(scope: str | None = Query(default=None),
            _: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    if scope is None or not valid_costmap_scope(scope):
        raise ApiError("VALIDATION_ERROR", 400, "scope must be global or local")
    grid = svc.maps.get_costmap(scope)
    if grid is None:
        raise ApiError("NOT_FOUND", 404, f"no {scope} costmap received yet")
    return {"scope": scope, **grid}


@map_router.get("/site")
def site_map_status(auth: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    reply = _host_agent(svc).request("site_map.status", role="viewer", user_id=auth.token_id)
    if not reply.reachable:
        return {"available": False, "code": reply.code, "detail": reply.detail}
    payload = reply.data if isinstance(reply.data, dict) else {"data": reply.data}
    return {"available": True, "ok": reply.ok, "code": reply.code, "detail": reply.detail, **payload}


@map_router.post("/site", status_code=202)
def site_map_stage_and_activate(
    body: SiteMapBundleBody,
    _: AuthContext = Depends(assist),
    svc: CoreServicesLike = Depends(get_services),
):
    if abs(float(body.origin[2])) > 1e-6:
        raise ApiError("VALIDATION_ERROR", 400, "origin yaw must be 0.0 for site-aligned Nav2 map")
    if body.free_thresh >= body.occupied_thresh:
        raise ApiError("VALIDATION_ERROR", 400, "free_thresh must be below occupied_thresh")
    try:
        pgm = base64.b64decode(body.pgm_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ApiError("VALIDATION_ERROR", 400, "pgm_base64 is not base64") from exc
    if hashlib.sha256(pgm).hexdigest() != body.sha256:
        raise ApiError("SHA256_MISMATCH", 400, "the site map image does not match its sha256")
    match = _PGM_HEADER_RE.match(pgm)
    if not match:
        raise ApiError("VALIDATION_ERROR", 400, "the site map image is not a P5 PGM with maxval 255")
    width, height = int(match[1]), int(match[2])
    if not 0 < width * height <= _MAX_CELLS or len(pgm) - match.end() != width * height:
        raise ApiError("VALIDATION_ERROR", 400, "the site map image size does not match its header")

    core_dir = Path(os.environ.get("STATE_DIRECTORY", "/var/lib/rosy/core"))
    spool = core_dir / "site-map-spool"
    meta_bytes = json.dumps(body.model_dump(exclude={"pgm_base64", "activate"})).encode("utf-8")
    agent = _host_agent(svc)

    if not body.activate:
        with _SITE_MAP_LOCK:
            _atomic_core_file(spool / "site-map.pgm", pgm)
            _atomic_core_file(spool / "meta.json", meta_bytes)
            stage_reply = agent.request("site_map.stage", role="machine", user_id="core-site-map")
        if not stage_reply.ok:
            _raise_host_error(stage_reply, "SITE_MAP_REFUSED", "the host did not stage the site map")
        return {
            "staged": True,
            "activated": False,
            "site_map": stage_reply.data,
            "activation": None,
        }

    with svc.modes.idle_admission:
        if svc.safety.estop:
            raise ApiError("ESTOP_ACTIVE", 409, "release E-stop before site map activation")
        if svc.modes.mode is not Mode.IDLE:
            raise ApiError("MODE_CONFLICT", 409, "select IDLE mode before site map activation")
        if svc.calibration.current() is not None:
            raise ApiError("CALIBRATION_ACTIVE", 409, "finish calibration before site map activation")
        if getattr(svc, "trip_lease", None) is not None and svc.trip_lease.current() is not None:
            raise ApiError("TRIP_LEASE_ACTIVE", 409, "release active trip lease before site map activation")
        goal_active = (
            getattr(svc.nav, "nav_state", None) in (NavigationState.PLANNING, NavigationState.NAVIGATING)
            or bool(getattr(svc.line_follow, "active", False))
            or bool(getattr(svc.docking, "active", False))
            or bool(getattr(svc.swarm, "active", False))
        )
        vel_age = svc.state.received_age("velocity")
        zero_since = getattr(svc.state, "zero_velocity_since", None)
        now_mono = getattr(svc.state, "_monotonic", time.monotonic)()
        if (
            goal_active
            or vel_age is None
            or vel_age > _STALE_VELOCITY_S
            or zero_since is None
            or (now_mono - zero_since) < 2.0
            or not robot_still(svc)
        ):
            raise ApiError("ROBOT_NOT_STOPPED", 409,
                           "robot must be idle with fresh zero velocity >= 2.0 s before site map activation")
        if not svc.modes.reserve_idle_motion():
            raise ApiError("MODE_CONFLICT", 409, "motion or another host configuration update is active")
        try:
            boot_id = _BOOT_ID.read_text(encoding="ascii").strip()
        except OSError:
            boot_id = ""
        stop_doc = json.dumps({
            "written_at": now_mono,
            "zero_since": zero_since,
            "goal_active": False,
            "boot_id": boot_id,
        }).encode("utf-8")

    try:
        with _SITE_MAP_LOCK:
            _atomic_core_file(spool / "site-map.pgm", pgm)
            _atomic_core_file(spool / "meta.json", meta_bytes)
            stage_reply = agent.request("site_map.stage", role="machine", user_id="core-site-map")
            if not stage_reply.ok:
                _raise_host_error(stage_reply, "SITE_MAP_REFUSED", "the host did not stage the site map")
            _atomic_core_file(core_dir / "site-map-stop.json", stop_doc)
            act_reply = agent.request("site_map.activate", role="machine", user_id="core-site-map")
        if not act_reply.ok:
            _raise_host_error(act_reply, "SITE_MAP_ACTIVATE_REFUSED", "the host refused site map activation")
        act_data = act_reply.data if isinstance(act_reply.data, dict) else {}
        deadline = time.monotonic() + _ACTIVATE_WAIT_S
        while act_data.get("phase") == "ACTIVATING":
            if time.monotonic() >= deadline:
                raise ApiError("SITE_MAP_ACTIVATE_TIMEOUT", 504, "site map activation did not finish in time")
            time.sleep(_ACTIVATE_POLL_S)
            st_reply = agent.request("site_map.status", role="machine", user_id="core-site-map")
            if not st_reply.ok:
                _raise_host_error(st_reply, "SITE_MAP_STATUS_FAILED", "host agent status poll failed during activation")
            act_data = st_reply.data if isinstance(st_reply.data, dict) else {}
        if act_data.get("phase") != "ACTIVE":
            raise ApiError(
                "SITE_MAP_ACTIVATE_FAILED", 409,
                act_data.get("reason") or f"site map activation ended in phase {act_data.get('phase')}",
            )
    finally:
        svc.modes.release_idle_motion()
    return {
        "staged": True,
        "activated": True,
        "site_map": stage_reply.data,
        "activation": act_data,
    }
