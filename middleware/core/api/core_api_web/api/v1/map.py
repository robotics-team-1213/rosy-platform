"""core_api_web.api.v1.map — MAP-003 점유맵·코스트맵 스냅샷 조회 및 site-map 교환."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query

from core_api_web.api.v1.common import robot_still, viewer
from core_api_web.api.deps import (
    AuthContext, CoreServicesLike, SiteMapRefused, get_services, require_stopped_for_site_map, valid_costmap_scope,
)
from core_api_web.api.errors import ApiError
from core_api_web.api.grants import LOCALIZE_ASSIST, require_grant
from core_api_web.api.host_agent_client import HostAgentClient
from core_common.protocol.site_map_bundle import SiteMapBundleBody, SiteMapBundleError, decode_site_map_pgm


map_router = APIRouter(prefix="/api/v1/map", tags=["map"])
assist = require_grant(LOCALIZE_ASSIST)
_BOOT_ID = Path("/proc/sys/kernel/random/boot_id")
_SITE_MAP_LOCK = threading.Lock()
_ACTIVATE_POLL_S = 0.25
_ACTIVATE_WAIT_S = 25.0


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
        pgm = decode_site_map_pgm(body)
    except SiteMapBundleError as exc:
        raise ApiError(exc.code, 400, str(exc)) from exc

    core_dir = Path(os.environ.get("STATE_DIRECTORY", "/var/lib/rosy/core"))
    spool = core_dir / "site-map-spool"
    meta_bytes = json.dumps(body.model_dump(exclude={"pgm_base64", "activate"})).encode("utf-8")
    agent = _host_agent(svc)

    def stage() -> Any:
        _atomic_core_file(spool / "site-map.pgm", pgm)
        _atomic_core_file(spool / "meta.json", meta_bytes)
        reply = agent.request("site_map.stage", role="machine", user_id="core-site-map")
        if not reply.ok:
            _raise_host_error(reply, "SITE_MAP_REFUSED", "the host did not stage the site map")
        return reply

    if not body.activate:
        with _SITE_MAP_LOCK:
            stage_reply = stage()
        return {"staged": True, "activated": False, "site_map": stage_reply.data, "activation": None}

    with svc.modes.idle_admission:
        try:
            zero_since, now_mono = require_stopped_for_site_map(svc, still=robot_still(svc))
        except SiteMapRefused as exc:
            raise ApiError(exc.code, 409, str(exc)) from exc
        if not svc.modes.reserve_idle_motion():
            raise ApiError("MODE_CONFLICT", 409, "motion or another host configuration update is active")
        try:
            boot_id = _BOOT_ID.read_text(encoding="ascii").strip()
        except OSError:
            boot_id = ""
        stop_doc = json.dumps({"written_at": now_mono, "zero_since": zero_since, "goal_active": False, "boot_id": boot_id}).encode("utf-8")

    try:
        with _SITE_MAP_LOCK:
            stage_reply = stage()
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
    return {"staged": True, "activated": True, "site_map": stage_reply.data, "activation": act_data}
