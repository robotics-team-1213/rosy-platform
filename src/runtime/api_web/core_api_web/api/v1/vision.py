"""Observation-only front camera preview endpoints."""

import json
import re

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import FileResponse

from core_api_web.api.deps import (
    AuthContext,
    CoreServicesLike,
    VisionFrameAdvanced,
    VisionPullRateLimited,
    VisionPreviewStatus,
    VisionEvidenceRecord,
    VisionEvidenceList,
    get_services,
)
from core_api_web.api.errors import ApiError
from core_api_web.api.v1.common import operator, viewer
from core_api_web.api.v1 import vision_evidence


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


@vision_router.post("/front/evidence", status_code=201, response_model=VisionEvidenceRecord)
async def store_front_camera_evidence(
        request: Request,
        _: AuthContext = Depends(operator)):
    try:
        return await vision_evidence.save_evidence(
            request.stream(), vision_evidence.evidence_root())
    except vision_evidence.EvidenceError as exc:
        raise ApiError(exc.code, exc.status, str(exc)) from exc


@vision_router.get("/front/evidence", response_model=VisionEvidenceList)
def list_front_camera_evidence(
        _: AuthContext = Depends(operator)):
    return {"records": vision_evidence.list_evidence(vision_evidence.evidence_root())}


@vision_router.get("/front/evidence/{evidence_id}")
def download_front_camera_evidence(
        evidence_id: str,
        _: AuthContext = Depends(operator)):
    if not re.fullmatch(r"[0-9a-f]{24}", evidence_id):
        raise ApiError("CAMERA_EVIDENCE_NOT_FOUND", 404, "camera evidence was not found")
    root = vision_evidence.evidence_root()
    record_path = root / f"{evidence_id}.json"
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if record.get("id") != evidence_id:
            raise ValueError("camera evidence id mismatch")
        path = root / record["file_name"]
        if path.name != record["file_name"] or not path.is_file():
            raise ValueError("camera evidence file missing")
        return FileResponse(path, media_type=record["mime_type"], filename=path.name,
                            headers={"Cache-Control": "no-store"})
    except (OSError, ValueError, KeyError) as exc:
        raise ApiError("CAMERA_EVIDENCE_NOT_FOUND", 404, "camera evidence was not found") from exc
