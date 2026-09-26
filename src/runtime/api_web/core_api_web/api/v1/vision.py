"""Observation-only front camera preview endpoints."""

from fastapi import APIRouter, Depends, Query, Response

from core_api_web.api.deps import (
    AuthContext,
    CoreServicesLike,
    VisionFrameAdvanced,
    VisionPullRateLimited,
    VisionPreviewStatus,
    get_services,
)
from core_api_web.api.errors import ApiError
from core_api_web.api.v1.common import viewer


vision_router = APIRouter(prefix="/api/v1/vision", tags=["vision"])


@vision_router.get("/front/status", response_model=VisionPreviewStatus)
def get_front_camera_status(
        response: Response,
        _: AuthContext = Depends(viewer),
        svc: CoreServicesLike = Depends(get_services)):
    response.headers["Cache-Control"] = "no-store"
    return svc.vision.status()


@vision_router.get("/front/frame")
def get_front_camera_frame(
        sequence: int = Query(ge=1),
        auth: AuthContext = Depends(viewer),
        svc: CoreServicesLike = Depends(get_services)):
    try:
        frame = svc.vision.frame_for_viewer(
            auth.token_id, expected_sequence=sequence)
    except VisionFrameAdvanced as exc:
        raise ApiError(
            "CAMERA_FRAME_ADVANCED", 409,
            f"front camera advanced to sequence {exc.sequence}",
        ) from exc
    except VisionPullRateLimited as exc:
        raise ApiError(
            "CAMERA_RATE_LIMITED", 429,
            f"retry camera preview after {exc.retry_after_s:.3f}s",
        ) from exc
    if frame is None:
        raise ApiError(
            "CAMERA_FRAME_UNAVAILABLE", 404,
            "front camera preview is missing or stale",
        )
    return Response(
        content=frame.data,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-store",
            # JPEG is already compressed. This header keeps GZipMiddleware
            # from spending CORE CPU recompressing camera bytes.
            "Content-Encoding": "identity",
            "X-Rosy-Camera-Source": frame.source,
            "X-Rosy-Camera-Sequence": str(frame.sequence),
            "X-Rosy-Camera-Captured-At": str(frame.captured_at),
        },
    )
