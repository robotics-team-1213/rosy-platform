"""Observation-only front camera preview endpoints."""

import asyncio
import json
import re
import time

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import FileResponse, StreamingResponse

from core_api_web.api.deps import (
    AuthContext,
    CoreServicesLike,
    VisionFrameAdvanced,
    VisionPullRateLimited,
    VisionPreviewStatus,
    VisionStreamRefused,
    VisionEvidenceRecord,
    VisionEvidenceList,
    get_services,
)
from core_api_web.api.errors import ApiError
from core_api_web.api.v1.common import operator, viewer
from core_api_web.api.v1 import vision_evidence


vision_router = APIRouter(prefix="/api/v1/vision", tags=["vision"])

#: Sequence-check cadence for the driver stream (D-368 §1). The publisher's
#: frame rate bounds the emitted fps; this only decides how soon a new
#: sequence is noticed.
STREAM_POLL_S = 0.05


@vision_router.get("/front/status", response_model=VisionPreviewStatus)
def get_front_camera_status(
        response: Response,
        _: AuthContext = Depends(viewer),
        svc: CoreServicesLike = Depends(get_services)):
    response.headers["Cache-Control"] = "no-store"
    return svc.vision.status()


@vision_router.get("/models")
def get_model_status(
        response: Response,
        _: AuthContext = Depends(viewer),
        svc: CoreServicesLike = Depends(get_services)):
    """D-423 §3.6: per-task learned-model status the robot reports; read-only."""
    response.headers["Cache-Control"] = "no-store"
    return svc.vision.models.snapshot(now=time.monotonic())


@vision_router.get("/front/frame")
def get_front_camera_frame(
        sequence: int = Query(ge=1),
        overlay: bool = Query(default=True),
        auth: AuthContext = Depends(viewer),
        svc: CoreServicesLike = Depends(get_services)):
    try:
        frame = svc.vision.frame_for_viewer(
            auth.token_id, expected_sequence=sequence, overlay=overlay)
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
            "X-Rosy-Camera-Frame-Id": frame.frame_id,
            "X-Rosy-Camera-Variant": 'annotated' if overlay else 'raw',
        },
    )


@vision_router.get("/front/stream")
async def stream_front_camera(
        overlay: bool = Query(default=True),
        auth: AuthContext = Depends(operator),
        svc: CoreServicesLike = Depends(get_services)):
    """D-368: MJPEG stream for the current teleop driver only (no seat lease,
    D-460). Spectators keep the 0.4 s polling path. One stream at a time; a
    new accepted teleop from another token ends the previous stream."""
    try:
        svc.vision_stream.open(auth.token_id)
    except VisionStreamRefused as exc:
        raise ApiError(exc.code, exc.status, str(exc)) from exc
    token = auth.token_id

    async def parts():
        last_sequence = 0
        try:
            while True:
                if svc.vision_stream.driver() != token:
                    return  # seat changed (D-411 vocabulary): end the stream
                frame = svc.vision.latest_frame(overlay=overlay)
                if frame is not None and frame.sequence > last_sequence:
                    last_sequence = frame.sequence
                    headers = (
                        b"Content-Type: image/jpeg\r\n"
                        + f"Content-Length: {len(frame.data)}\r\n".encode("ascii")
                        + f"X-Rosy-Camera-Sequence: {frame.sequence}\r\n".encode("ascii")
                        + f"X-Rosy-Camera-Source: {frame.source}\r\n".encode("ascii")
                        + f"X-Rosy-Camera-Captured-At: {frame.captured_at:.3f}\r\n".encode("ascii")
                        + b"\r\n"
                    )
                    yield b"--frame\r\n" + headers + frame.data + b"\r\n"
                await asyncio.sleep(STREAM_POLL_S)
        finally:
            svc.vision_stream.close(token)

    return StreamingResponse(
        parts(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-store",
            # JPEG parts are already compressed; keep GZipMiddleware away.
            "Content-Encoding": "identity",
            "X-Accel-Buffering": "no",
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
