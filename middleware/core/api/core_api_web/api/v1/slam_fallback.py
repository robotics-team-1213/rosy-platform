"""SLAM fallback API (2026-11-18): status, the wall map push from Fleet, Fleet-fed health evidence, operator reset.

The switch itself is automatic and has no route: a person cannot start it, and nothing here can switch back to SLAM.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from core_api_web.api.deps import AuthContext, CoreServicesLike, get_services
from core_api_web.api.errors import ApiError
from core_api_web.api.grants import LOCALIZE_ASSIST, require_grant
from core_api_web.api.v1.common import operator, viewer

slam_fallback_router = APIRouter(prefix="/api/v1/navigation/slam-fallback", tags=["navigation"])

assist = require_grant(LOCALIZE_ASSIST)  # Fleet already holds it for the localization routes
MAX_PGM_B64 = 8_000_000
Coordinate = Annotated[float, Field(allow_inf_nan=False, ge=-1000.0, le=1000.0)]  # metres; the host checks the same bounds


class WallMapBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    map_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    version: int = Field(ge=0, strict=True)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")  # of the PGM bytes, as Fleet's wall-grid route reports it
    resolution: float = Field(ge=0.01, le=0.1, allow_inf_nan=False)
    origin: list[Coordinate] = Field(min_length=3, max_length=3)
    pgm_base64: str = Field(max_length=MAX_PGM_B64)


class EvidenceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gap_m: Optional[float] = Field(default=None, ge=0.0, allow_inf_nan=False)
    agreement: Optional[float] = Field(default=None, ge=0.0, le=1.0, allow_inf_nan=False)
    map_verdict: Optional[str] = Field(default=None, pattern=r"^(ok|warn|fail)$")


def _supervisor(svc: CoreServicesLike):
    supervisor = getattr(svc, "slam_fallback", None)
    if supervisor is None or not supervisor.enabled:
        raise ApiError("NOT_SLAM_BACKEND", 409, "this robot does not run the SLAM backend: there is nothing to fall back from")
    return supervisor


@slam_fallback_router.get("")
def read(_: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    supervisor = getattr(svc, "slam_fallback", None)
    return {"enabled": bool(supervisor and supervisor.enabled), "status": supervisor.status() if supervisor else None}


@slam_fallback_router.post("/wall-map", status_code=202)
def wall_map(body: WallMapBody, _: AuthContext = Depends(assist), svc: CoreServicesLike = Depends(get_services)):
    """Fleet pushes the active site map's wall grid ahead of time; CORE spools it, the host half re-verifies and installs it."""
    supervisor = _supervisor(svc)
    try:
        pgm = base64.b64decode(body.pgm_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ApiError("VALIDATION_ERROR", 400, "pgm_base64 is not base64") from exc
    if hashlib.sha256(pgm).hexdigest() != body.sha256:
        raise ApiError("SHA256_MISMATCH", 400, "the wall map image does not match its sha256")
    if not supervisor.spool(pgm, body.model_dump_json(exclude={"pgm_base64"}).encode("utf-8")):
        raise ApiError("SWITCH_RUNNING", 409, "a fallback switch is running: the wall map is not replaced now")
    reply = supervisor.stage()
    if not reply.ok:
        raise ApiError(reply.code or "WALL_MAP_REFUSED", 409, reply.detail or "the host did not stage the wall map")
    return {"staged": True, "wall_map": supervisor.wall_map}


@slam_fallback_router.post("/evidence", status_code=202)
def evidence(body: EvidenceBody, _: AuthContext = Depends(assist), svc: CoreServicesLike = Depends(get_services)):
    """Fleet-side health evidence (slam_camera_gap_m, scan agreement, the map verdict): kept for a few seconds, fed to slam_health."""
    getattr(_supervisor(svc), "evidence").note(body.gap_m, body.agreement, body.map_verdict)
    return {"accepted": True}


@slam_fallback_router.post("/reset")
def reset(_: AuthContext = Depends(operator), svc: CoreServicesLike = Depends(get_services),
          confirm: bool = Query(default=False)):
    """After a FAILED fallback a named operator resumes monitoring. The host's one-attempt-per-boot flag is root-only."""
    if not confirm:
        raise ApiError("CONFIRM_REQUIRED", 400, "add ?confirm=true")
    return {"reset": _supervisor(svc).reset()}
