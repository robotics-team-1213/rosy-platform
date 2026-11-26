"""Overhead markerless tracking routes (D-457 4-7).

Vision writes detections and reads its own tracking config with its source token; the
console reads tracking and calibrations (viewer) and approves, revokes and relearns
(operator). No path names a camera, image or video (test_no_video_relay) and none
contains "vision" (test_app_roles): Fleet never relays frames (D-318).
"""

from __future__ import annotations

import logging
import math
from typing import Literal, Optional

from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from core_common.calibration_math import solve_planar_pose
from core_common.protocol.overhead_detections import OverheadDetectionsPayload
from fleet.server.site_auth import SitePrincipal
from fleet.server.identity import IdentityError
from fleet.server.tracking import TrackingError
from fleet.server.measured_calibration import (
    MeasuredCalibrationApproval, MeasuredCalibrationService, PreviewStatus,
)

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
    """The console's "추적 보정 적용" body: one accepted D-375 or manual/measured fit for one source."""

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, max_length=64)
    map_id: Optional[str] = Field(default=None, min_length=1, max_length=160)
    map_to_image: list[float] = Field(min_length=9, max_length=9)
    image: _ImageSize
    track_bounds_m: _Bounds
    fit_score: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    lens: Optional[_Lens] = None
    frame_seq: Optional[int] = Field(default=None, ge=0)
    lens_profile: Optional[dict] = None
    method: Optional[str] = Field(default=None, min_length=1, max_length=32)
    metrics: Optional[dict] = None
    frozen: bool = False
    auto: bool = False


class _Correspondence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_px: list[float] = Field(min_length=2, max_length=2)
    map_m: list[float] = Field(min_length=2, max_length=2)


class CalibrationFitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, max_length=64)
    map_id: Optional[str] = Field(default=None, min_length=1, max_length=160)
    image: _ImageSize
    track_bounds_m: _Bounds
    correspondences: list[_Correspondence] = Field(min_length=4, max_length=64)
    lens: Optional[_Lens] = None
    lens_profile: Optional[dict] = None


class CalibrationRollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_revision: Optional[str] = Field(default=None, min_length=1, max_length=160)


class CalibrationFreezeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frozen: bool


class RecalibrationCandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    map_id: Optional[str] = Field(default=None, min_length=1, max_length=160)
    map_to_image: list[float] = Field(min_length=9, max_length=9)
    image: _ImageSize
    track_bounds_m: _Bounds
    fit_score: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    lens: Optional[_Lens] = None
    frame_seq: Optional[int] = Field(default=None, ge=0)
    lens_profile: Optional[dict] = None
    rms_m: float = Field(default=0.0, ge=0.0, allow_inf_nan=False)
    spread_m: float = Field(default=0.0, ge=0.0, allow_inf_nan=False)
    hold_reason: Optional[str] = Field(default=None, min_length=1, max_length=64)
    route_active: bool = False


class RelearnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, max_length=64)


class IdentityVerdict(BaseModel):
    """D-472: Vision's answer to one identity challenge. Numbers only, never an image."""

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, max_length=64)
    map_id: str = Field(min_length=1, max_length=160)
    request_id: str = Field(min_length=1, max_length=64)
    processor_revision: str = Field(min_length=1, max_length=64)
    state: Literal["matched", "ambiguous"]
    reason: Optional[Literal["none", "multiple", "frames_missing", "stale", "calibration_changed"]] = None
    x: Optional[float] = Field(default=None, allow_inf_nan=False)
    y: Optional[float] = Field(default=None, allow_inf_nan=False)
    yaw: Optional[float] = Field(default=None, allow_inf_nan=False)  # map-frame rad; Vision's led_identity.decide sends it
    captured_at: Optional[float] = Field(default=None, allow_inf_nan=False)
    calibration_revision: Optional[str] = Field(default=None, max_length=160)
    evidence: dict = Field(default_factory=dict)


def _http(exc: TrackingError | IdentityError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)})


def install_tracking_routes(app, *, tracking, require_operator, read_guard, operator_guard,
                            require_named_operator=None, map_revision=None, map_pose=None,
                            console=None, site_maps=None) -> None:
    measured = MeasuredCalibrationService(tracking, map_revision=map_revision)
    from fleet.server.auto_locate_service import AutoLocateService
    tracking.auto_locate = app.state.auto_locate = AutoLocateService(tracking, map_pose=map_pose, console=console)
    app.state.measured_calibration = measured

    def named(principal):
        if require_named_operator is None:
            raise HTTPException(status_code=403, detail={'code': 'OPERATOR_IDENTITY_REQUIRED'})
        return require_named_operator(principal=principal)
    @app.post("/api/fleet/detections", tags=["tracking"])
    async def submit_detections(body: OverheadDetectionsPayload,
                                authorization: Optional[str] = Header(default=None)) -> dict:
        try:
            return tracking.accept(authorization, body)
        except TrackingError as exc:
            raise _http(exc) from exc

    @app.post("/api/fleet/detections/anchors", tags=["tracking"])
    async def submit_anchor_states(body: dict, authorization: Optional[str] = Header(default=None)) -> dict:
        """Vision's display-only head-tracker states; the source token is checked in accept_anchors."""
        try:
            return tracking.accept_anchors(authorization, body)
        except TrackingError as exc:
            raise _http(exc) from exc

    @app.get("/api/fleet/detections/config", tags=["tracking"])
    async def detection_config(authorization: Optional[str] = Header(default=None),
                               include_preview: bool = False) -> dict:
        try:
            result = tracking.config_for(authorization)
            if include_preview:
                result['measured_preview'] = measured.config(tracking.authenticate(authorization))
                if site_maps is not None:
                    try:
                        active = site_maps.active()
                        site = active[1] if isinstance(active, tuple) and len(active) > 1 else None
                        places = []
                        for p in (getattr(site, "places", None) or ())[:64]:
                            px, py = getattr(p, "x", None), getattr(p, "y", None)
                            if (isinstance(px, (int, float)) and isinstance(py, (int, float))
                                    and not isinstance(px, bool) and not isinstance(py, bool)
                                    and math.isfinite(px) and math.isfinite(py)):
                                pid = str(getattr(p, "place_id", None) or getattr(p, "id", None) or "")
                                places.append({
                                    "id": pid,
                                    "name": str(getattr(p, "name", None) or pid),
                                    "x": float(px),
                                    "y": float(py),
                                })
                        result["places"] = places
                    except Exception:
                        pass
            return result
        except TrackingError as exc:
            raise _http(exc) from exc

    @app.post('/api/fleet/detections/preview-status', tags=['tracking'])
    async def measured_status(body: PreviewStatus, authorization: Optional[str] = Header(default=None)):
        try:
            return measured.report(authorization, body)
        except TrackingError as exc:
            raise _http(exc) from exc

    @app.post("/api/fleet/detections/identity", tags=["tracking"])
    async def submit_identity_verdict(body: IdentityVerdict,
                                      authorization: Optional[str] = Header(default=None)) -> dict:
        try:
            source = tracking.authenticate(authorization)
            if body.source_id != source.source_id:
                raise TrackingError(403, "SOURCE_MISMATCH", "verdict source does not match the token")
            if tracking.identity is None:
                raise TrackingError(409, "IDENTIFY_NOT_PENDING", "no identity service")
            return tracking.identity.accept_verdict(source, body.model_dump())
        except (TrackingError, IdentityError) as exc:
            raise _http(exc) from exc

    @app.get("/api/fleet/tracking/identity", dependencies=read_guard, tags=["tracking"])
    async def identity_readback() -> dict:
        if tracking.identity is None:
            return {"use": "observation-only", "pending": None, "robots": []}
        return tracking.identity.snapshot()

    @app.get("/api/fleet/auto-locate", dependencies=read_guard, tags=["tracking"])
    async def auto_locate_readback() -> dict:
        return tracking.auto_locate.snapshot()

    @app.post("/api/fleet/auto-locate", tags=["tracking"])
    async def auto_locate_start(principal: SitePrincipal = Depends(require_operator)) -> dict:
        named(principal)
        watched = sorted({rid for source in tracking.sources for rid in source.robot_ids})
        result = tracking.auto_locate.start(watched)
        _LOG.info("auto locate started: robots=%d principal_id=%s", len(watched), principal.principal_id)
        return result

    @app.post("/api/fleet/auto-locate/{robot_id}/lift-block", tags=["tracking"])
    async def auto_locate_lift_block(robot_id: str, principal: SitePrincipal = Depends(require_operator)) -> dict:
        named(principal)
        if not tracking.auto_locate.lift_block(robot_id, principal.principal_id):
            raise HTTPException(status_code=409, detail={"code": "AUTO_LOCATE_NOT_ENABLED"})
        return {"robot_id": robot_id, "anchor_blocked": False}

    @app.get("/api/fleet/tracking", dependencies=read_guard, tags=["tracking"])
    async def tracking_readback() -> dict:
        anchors = getattr(tracking, "anchors_snapshot", None)
        return {**tracking.snapshot(), "anchors": anchors()["targets"] if callable(anchors) else []}

    @app.post("/api/fleet/tracking/relearn", tags=["tracking"])
    async def tracking_relearn(body: RelearnRequest,
                               principal: SitePrincipal = Depends(require_operator)) -> dict:
        try:
            result = tracking.request_relearn(body.source_id)
        except TrackingError as exc:
            raise _http(exc) from exc
        _LOG.info("tracking relearn requested: source_id=%s relearn_seq=%d occupied=%d unlocated=%s principal_id=%s",
                  result["source_id"], result["relearn_seq"], result["occupied"], result["unlocated"],
                  principal.principal_id)
        return result

    @app.get("/api/fleet/calibrations", dependencies=read_guard, tags=["tracking"])
    async def calibration_listing(purpose: Literal['tracking', 'preview'] = 'tracking',
                                  include_history: bool = False) -> dict:
        if purpose == 'preview':
            return measured.listing()
        return tracking.calibration_listing(include_history=include_history)

    @app.post("/api/fleet/calibrations", tags=["tracking"])
    async def approve_calibration(body: CalibrationApproval | MeasuredCalibrationApproval,
                                  principal: SitePrincipal = Depends(require_operator)) -> dict:
        try:
            if isinstance(body, MeasuredCalibrationApproval):
                return measured.approve(body, named(principal).principal_id)
            return tracking.approve(body.model_dump(), approved_by=principal.principal_id)
        except TrackingError as exc:
            raise _http(exc) from exc

    @app.post("/api/fleet/calibrations/fit", tags=["tracking"])
    async def fit_calibration(body: CalibrationFitRequest,
                              principal: SitePrincipal = Depends(require_operator)) -> dict:
        source = tracking._by_id.get(body.source_id)
        if source is None:
            raise _http(TrackingError(404, "UNKNOWN_SOURCE", "no configured source with this id"))
        map_id = body.map_id or source.map_id
        if map_id != source.map_id:
            raise _http(TrackingError(409, "MAP_MISMATCH", "calibration map does not match source configuration"))
        b = body.track_bounds_m
        try:
            return solve_planar_pose(
                [(c.image_px[0], c.image_px[1]) for c in body.correspondences],
                [(c.map_m[0], c.map_m[1]) for c in body.correspondences],
                image_size=(body.image.width, body.image.height),
                lens_profile=body.lens_profile,
                hfov_deg=body.lens.hfov_deg if body.lens is not None else None,
                track_bounds_m=(b.min_x, b.min_y, b.max_x, b.max_y),
            )
        except ValueError as exc:
            raise _http(TrackingError(422, "INVALID_CALIBRATION_FIT", str(exc))) from exc

    @app.post("/api/fleet/calibrations/{source_id}/rollback", tags=["tracking"])
    async def rollback_calibration(source_id: str,
                                   body: Optional[CalibrationRollbackRequest] = None,
                                   principal: SitePrincipal = Depends(require_operator)) -> dict:
        try:
            target = body.target_revision if body is not None else None
            return tracking.rollback(source_id, target_revision=target, principal_id=principal.principal_id)
        except TrackingError as exc:
            raise _http(exc) from exc

    @app.post("/api/fleet/calibrations/{source_id}/freeze", tags=["tracking"])
    async def freeze_calibration(source_id: str, body: CalibrationFreezeRequest,
                                 principal: SitePrincipal = Depends(require_operator)) -> dict:
        try:
            return tracking.set_frozen(source_id, body.frozen, principal_id=principal.principal_id)
        except TrackingError as exc:
            raise _http(exc) from exc

    @app.post("/api/fleet/calibrations/{source_id}/recalibrate/candidate", tags=["tracking"])
    async def submit_recal_candidate(source_id: str, body: RecalibrationCandidateRequest,
                                     principal: SitePrincipal = Depends(require_operator)) -> dict:
        try:
            return tracking.submit_recalibration_candidate(source_id, body.model_dump(), principal_id=principal.principal_id)
        except TrackingError as exc:
            raise _http(exc) from exc

    @app.post("/api/fleet/calibrations/{source_id}/recalibrate/accept", tags=["tracking"])
    async def accept_recal_candidate(source_id: str,
                                     principal: SitePrincipal = Depends(require_operator)) -> dict:
        try:
            return tracking.accept_recalibration_candidate(source_id, approved_by=principal.principal_id)
        except TrackingError as exc:
            raise _http(exc) from exc

    @app.post("/api/fleet/calibrations/{source_id}/recalibrate/dismiss", tags=["tracking"])
    async def dismiss_recal_candidate(source_id: str,
                                      principal: SitePrincipal = Depends(require_operator)) -> dict:
        try:
            return tracking.dismiss_recalibration_candidate(source_id, principal_id=principal.principal_id)
        except TrackingError as exc:
            raise _http(exc) from exc

    @app.delete("/api/fleet/calibrations/{source_id}", tags=["tracking"])
    async def revoke_calibration(source_id: str,
                                 purpose: Literal['tracking', 'preview'] = 'tracking',
                                 expected_revision: Optional[str] = None,
                                 principal: SitePrincipal = Depends(require_operator)) -> dict:
        try:
            if purpose == 'preview':
                return measured.revoke(source_id, expected_revision, named(principal).principal_id)
            return tracking.revoke(source_id, principal_id=principal.principal_id)
        except TrackingError as exc:
            raise _http(exc) from exc
