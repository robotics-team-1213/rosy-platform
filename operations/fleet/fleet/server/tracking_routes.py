"""Overhead markerless tracking routes (D-457 4-7).

Vision writes detections and reads its own tracking config with its source token; the
console reads tracking and calibrations (viewer) and approves, revokes and relearns
(operator). No path names a camera, image or video (test_no_video_relay) and none
contains "vision" (test_app_roles): Fleet never relays frames (D-318).
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from core_common.protocol.overhead_detections import OverheadDetectionsPayload
from fleet.server.site_auth import SitePrincipal
from fleet.server.tracking import TrackingError

_LOG = logging.getLogger(__name__)


class _ImageSize(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width: int = Field(gt=0, le=8192, strict=True)
    height: int = Field(gt=0, le=8192, strict=True)


class _Bounds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_x: float = Field(allow_inf_nan=False)
    min_y: float = Field(allow_inf_nan=False)
    max_x: float = Field(allow_inf_nan=False)
    max_y: float = Field(allow_inf_nan=False)


class _Lens(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(pattern=r"^[a-z_]{1,32}$")
    focal_mm: float = Field(gt=0.0, le=1000.0, allow_inf_nan=False)
    hfov_deg: float = Field(gt=0.0, lt=180.0, allow_inf_nan=False)


class CalibrationApproval(BaseModel):
    """The console's "추적 보정 적용" body: one accepted D-375 fit for one source."""

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, max_length=64)
    map_id: Optional[str] = Field(default=None, min_length=1, max_length=160)
    map_to_image: list[float] = Field(min_length=9, max_length=9)
    image: _ImageSize
    track_bounds_m: _Bounds
    fit_score: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    lens: Optional[_Lens] = None
    frame_seq: Optional[int] = Field(default=None, ge=0)


class RelearnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, max_length=64)


def _http(exc: TrackingError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)})


def install_tracking_routes(app, *, tracking, require_operator, read_guard, operator_guard) -> None:
    @app.post("/api/fleet/detections", tags=["tracking"])
    async def submit_detections(body: OverheadDetectionsPayload,
                                authorization: Optional[str] = Header(default=None)) -> dict:
        try:
            return tracking.accept(authorization, body)
        except TrackingError as exc:
            raise _http(exc) from exc

    @app.get("/api/fleet/detections/config", tags=["tracking"])
    async def detection_config(authorization: Optional[str] = Header(default=None)) -> dict:
        try:
            return tracking.config_for(authorization)
        except TrackingError as exc:
            raise _http(exc) from exc

    @app.get("/api/fleet/tracking", dependencies=read_guard, tags=["tracking"])
    async def tracking_readback() -> dict:
        return tracking.snapshot()

    @app.post("/api/fleet/tracking/relearn", tags=["tracking"])
    async def tracking_relearn(body: RelearnRequest,
                               principal: SitePrincipal = Depends(require_operator)) -> dict:
        try:
            result = tracking.request_relearn(body.source_id)
        except TrackingError as exc:
            raise _http(exc) from exc
        _LOG.info("tracking relearn requested: source_id=%s relearn_seq=%d principal_id=%s",
                  result["source_id"], result["relearn_seq"], principal.principal_id)
        return result

    @app.get("/api/fleet/calibrations", dependencies=read_guard, tags=["tracking"])
    async def calibration_listing() -> dict:
        return tracking.calibration_listing()

    @app.post("/api/fleet/calibrations", tags=["tracking"])
    async def approve_calibration(body: CalibrationApproval,
                                  principal: SitePrincipal = Depends(require_operator)) -> dict:
        try:
            return tracking.approve(body.model_dump(), approved_by=principal.principal_id)
        except TrackingError as exc:
            raise _http(exc) from exc

    @app.delete("/api/fleet/calibrations/{source_id}", tags=["tracking"])
    async def revoke_calibration(source_id: str,
                                 principal: SitePrincipal = Depends(require_operator)) -> dict:
        try:
            return tracking.revoke(source_id, principal_id=principal.principal_id)
        except TrackingError as exc:
            raise _http(exc) from exc
