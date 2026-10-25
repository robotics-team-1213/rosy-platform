"""Authorized preview and operator proposals; no station measurement transform."""
from __future__ import annotations

import asyncio
from concurrent.futures import BrokenExecutor
from dataclasses import dataclass
import json
import logging
import time
from typing import Mapping, TYPE_CHECKING

import cv2
from websockets.http11 import Headers, Response
from core_common.protocol.vision_preview import PreviewRectification, VisionLeaseError
from .field_detect import DETECTOR_VERSION, FieldDetection, detect_field_jpeg
from . import map_worker
from .map_register import REGISTER_VERSION, RegistrationResult
from .rectify import MapPlane, crop_map_plane, map_plane_jpeg, plane_observed_fraction, rectify_jpeg

if TYPE_CHECKING:
    from .ingest import LatestFrame

logger = logging.getLogger(__name__)
FIELD_REPORT_TTL_S = 5.0
_FRAME_INTERVAL_S = 0.2
_FIELD_PROPOSAL_INTERVAL_S = 1.0
_FIELD_DETECT_INTERVAL_S = 1.0
_MAP_REGISTER_INTERVAL_S = 1.0

@dataclass
class _FieldRun:
    """The last field detection for one source; ``detection`` is None while it runs or after it failed."""

    frame: LatestFrame
    started: float
    detection: FieldDetection | None = None


@dataclass
class _MapRun:
    """The last map registration for one source. ``finished`` is None while it runs (the
    next run may start ``_MAP_REGISTER_INTERVAL_S`` after it); ``failed`` marks an error."""

    frame: LatestFrame
    finished: float | None = None
    failed: bool = False
    result: RegistrationResult | None = None


def _field_corners(self, source: str) -> tuple[tuple[tuple[float, float], ...], str] | None:
    """Fresh auto-rectification corners and the calibration state, or None."""
    src = self._sources.get(source)
    report_state = getattr(src, "field", None) if src is not None else None
    if report_state is None:
        return None
    report, at = report_state
    if time.monotonic() - at > FIELD_REPORT_TTL_S:
        return None
    corners = report.get("corners_normalized")
    if not isinstance(corners, list) or len(corners) != 4:
        return None
    return tuple(tuple(point) for point in corners), str(report.get("state", ""))


async def _preview_response(self, path: str, authorization: str | None) -> Response:
    """Serve one authorized latest-frame read directly from Vision, never from Fleet."""
    prefix = "/api/vision/sources/"
    source, _, view = path[len(prefix):].partition("/") if path.startswith(prefix) else ("", "", "")
    if (not source or view not in ("frame", "field-proposal", "map-proposal")
            or self.preview_signer is None):
        return _http_response(404, b"not found\n")
    bearer = authorization[len("Bearer "):] if authorization and authorization.startswith("Bearer ") else ""
    try:
        lease = self.preview_signer.verify(bearer, source_id=source)
    except VisionLeaseError:
        return _http_response(401, b"unauthorized\n")
    # A missing, stale, or rate-limited frame is still a request (D-691).
    self._note_stream_request(source)
    if view == "map-proposal" and self.map_paint is None:
        return _http_response(404, b"site map paint not configured\n")
    if view == "frame":
        limited = self._rate_limited((str(lease["sub"]), source), _FRAME_INTERVAL_S)
    else:
        limited = self._rate_limited((str(lease["sub"]), source, view), _FIELD_PROPOSAL_INTERVAL_S)
    if limited is not None:
        return limited
    frame = self.latest_frame(source)
    if frame is None:
        return _http_response(404, b"frame unavailable\n")
    age = max(0.0, time.time() - frame.captured_at)
    if age > self.preview_max_age_s:
        return _http_response(404, b"frame stale\n", extra={"X-Frame-State": "stale"})
    if view == "field-proposal":
        return await self._field_proposal_response(source, frame)
    if view == "map-proposal":
        return await self._map_proposal_response(source, frame)
    jpeg = frame.jpeg
    rectified_header = "false"
    extra_state: dict[str, str] = {}
    if "rectification" in lease:
        try:
            settings = PreviewRectification.from_mapping(lease["rectification"])
            if settings.mode == "map":
                return await self._map_plane_response(source, frame, age, lease)
            if settings.mode == "auto":
                # D-484: swap the lease's corners for the calibration's accepted quad.
                field = self._field_corners(source)
                if field is None:
                    return _http_response(200, frame.jpeg, extra={
                        "Content-Type": "image/jpeg", "Cache-Control": "no-store",
                        "X-Frame-Seq": str(frame.header.seq),
                        "X-Frame-Age-Ms": str(round(age * 1000)),
                        "X-Frame-Rectified": "false",
                        "X-Frame-State": "field-unavailable",
                        **_lens_header(self.source_lens(source)),
                    })
                corners, calib_state = field
                settings = PreviewRectification(
                    mode="manual",
                    fx=settings.fx, fy=settings.fy, cx=settings.cx, cy=settings.cy,
                    k1=settings.k1, k2=settings.k2, p1=settings.p1, p2=settings.p2,
                    k3=settings.k3, corners=corners, output_aspect=settings.output_aspect)
                rectified_header = "auto"
                extra_state = {"X-Field-Calib": calib_state}
            elif not settings.is_identity:
                rectified_header = "true"
            if rectified_header != "false":
                jpeg = rectify_jpeg(frame.jpeg, settings)
        except (TypeError, ValueError, cv2.error):
            return _http_response(422, b"rectification failed\n",
                                  extra={"X-Frame-State": "rectification-error"})
    return _http_response(200, jpeg, extra={
        "Content-Type": "image/jpeg", "Cache-Control": "no-store",
        "X-Frame-Seq": str(frame.header.seq),
        "X-Frame-Age-Ms": str(round(age * 1000)),
        "X-Frame-Captured-At": str(frame.captured_at),
        "X-Frame-Width": str(frame.header.width),
        "X-Frame-Height": str(frame.header.height),
        "X-Frame-Rotation-Deg": str(frame.header.rotation_deg),
        "X-Frame-Rectified": rectified_header,
        **extra_state,
        **_lens_header(self.source_lens(source)),
    })


async def _map_plane_response(self, source: str, frame: LatestFrame, age: float,
                              lease: Mapping | None = None) -> Response:
    """D-560: the latest frame warped to the map plane, or 409; never the raw frame.

    The warp runs off the event loop, once per (frame, record revision) for all readers.
    """
    reported = self._plane_records.get(source)
    if reported is None:
        return _plane_unavailable()
    record, map_id = reported
    revision = str(record.get("calibration_revision"))
    crop_map = lease.get("crop_map") if lease else None
    if crop_map is not None and (lease.get("crop_map_id") != map_id
                                 or lease.get("crop_revision") != revision):
        return _plane_unavailable()
    cached = self._plane_cache.get(source)
    if cached is None or cached[0] is not frame or cached[1] != revision:
        task = asyncio.ensure_future(asyncio.to_thread(
            map_plane_jpeg, frame.jpeg, record, source_id=source, map_id=map_id,
            lens=self.source_lens(source)))
        # Retrieve a failure even when no reader is left to await it (no "never retrieved" log).
        task.add_done_callback(lambda t: t.cancelled() or t.exception())
        cached = (frame, revision, task)
        self._plane_cache[source] = cached
    plane: MapPlane | None = await asyncio.shield(cached[2])
    if plane is None:
        return _plane_unavailable()
    jpeg, size, bounds, rectified = plane.jpeg, plane.size, plane.bounds_m, "map"
    if crop_map is not None:
        cropped = await asyncio.to_thread(crop_map_plane, plane, *crop_map)
        if cropped is None:
            return _plane_unavailable()
        jpeg, size, bounds = cropped
        rectified = "map-crop"
    min_x, min_y, max_x, max_y = bounds
    return _http_response(200, jpeg, extra={
        "Content-Type": "image/jpeg", "Cache-Control": "no-store",
        "X-Frame-Seq": str(frame.header.seq),
        "X-Frame-Age-Ms": str(round(age * 1000)),
        "X-Frame-Captured-At": str(frame.captured_at),
        "X-Frame-Width": str(size[0]),
        "X-Frame-Height": str(size[1]),
        "X-Frame-Rotation-Deg": "0",
        "X-Frame-Rectified": rectified,
        "X-Frame-Plane": ",".join(f"{v:.4f}" for v in (min_x, min_y, max_x, max_y, plane.px_per_m)),
        "X-Frame-Calibration": plane.revision,
        "X-Frame-Observed-Fraction": f"{plane_observed_fraction(plane, crop_map):.6f}",
        **_lens_header(self.source_lens(source)),
    })


def _rate_limited(self, key: tuple[str, ...], interval_s: float) -> Response | None:
    now_mono = time.monotonic()
    previous = self._preview_last_sent.get(key)
    if previous is not None and now_mono - previous < interval_s:
        return _http_response(429, b"rate limited\n", extra={"Retry-After": "1"})
    if len(self._preview_last_sent) >= 512:
        self._preview_last_sent = {
            item: stamp for item, stamp in self._preview_last_sent.items()
            if now_mono - stamp < 10.0
        }
        if len(self._preview_last_sent) >= 512 and key not in self._preview_last_sent:
            return _http_response(429, b"preview capacity reached\n",
                                  extra={"Retry-After": "1"})
    self._preview_last_sent[key] = now_mono
    return None


async def _field_proposal_response(self, source: str, frame: LatestFrame) -> Response:
    """D-360: a field-corner proposal for operator review. Never applied to sightings.

    Detection runs off the event loop, at most once per source per
    ``_FIELD_DETECT_INTERVAL_S`` across all lease subjects.
    """
    run = self._field_cache.get(source)
    now_mono = time.monotonic()
    if run is None or (run.frame is not frame
                       and now_mono - run.started >= _FIELD_DETECT_INTERVAL_S):
        run = _FieldRun(frame=frame, started=now_mono)
        self._field_cache[source] = run
        try:
            run.detection = await asyncio.to_thread(detect_field_jpeg, frame.jpeg)
        except (ValueError, cv2.error):
            return _http_response(422, b"field detection failed\n",
                                  extra={"X-Frame-State": "detection-error"})
    detection = run.detection
    if detection is None:  # still running for another reader, or failed on this frame
        return _http_response(429, b"field detection busy\n", extra={"Retry-After": "1"})
    frame = run.frame
    age = max(0.0, time.time() - frame.captured_at)
    width, height = detection.image_size
    body = {
        "source": source,
        "frame_seq": frame.header.seq,
        "frame_age_ms": round(age * 1000),
        "image": {"width": width, "height": height},
        "proposal": detection.proposal.to_dict() if detection.proposal else None,
        "reason": detection.reason,
        "detector": {"version": DETECTOR_VERSION, "elapsed_ms": round(detection.elapsed_ms, 1)},
        "lens": self.source_lens(source),
    }
    return _http_response(200, (json.dumps(body, separators=(",", ":")) + "\n").encode(), extra={
        "Content-Type": "application/json", "Cache-Control": "no-store",
        "X-Frame-Seq": str(frame.header.seq),
        "X-Frame-Age-Ms": str(round(age * 1000)),
    })


async def _map_proposal_response(self, source: str, frame: LatestFrame) -> Response:
    """D-375: an image-to-map homography proposal from the lane paint, for operator review.

    Never applied to sightings or ``CameraMap``. ``proposal`` is set only when the fit
    passed every gate; a rejected fit is returned as ``rejected_fit`` with the reason
    (its coverage and cut sides still tell the installer where to move the camera).
    Runs off the event loop on one shared worker thread, single flight per source,
    and a new run only ``_MAP_REGISTER_INTERVAL_S`` after the last one finished. A read
    that arrives mid-run gets the source's last successful result (its own
    ``frame_seq``/age, ``X-Proposal-State: previous``), or 429 when there is none yet.
    A failed run answers 422 until the next run replaces it.
    """
    run = self._map_cache.get(source)
    state = "current"
    if run is not None and run.finished is None:  # single flight per source
        run = self._map_done.get(source)
        state = "previous"
        if run is None:
            return _http_response(429, b"map registration busy\n", extra={"Retry-After": "1"})
    elif run is None or (run.frame is not frame
                         and time.monotonic() - run.finished >= _MAP_REGISTER_INTERVAL_S):
        run = _MapRun(frame=frame)
        self._map_cache[source] = run
        try:
            if self._map_executor is None:
                self._map_executor = map_worker.start(self.map_paint)
            run.result = await asyncio.get_running_loop().run_in_executor(
                self._map_executor, self._map_job, frame.jpeg)
        except Exception as exc:  # noqa: BLE001 - any failure is a per-frame 422, never a crash
            logger.exception("map registration failed for source %s", source)
            run.failed = True
            if isinstance(exc, BrokenExecutor):  # worker died: start a fresh one next time
                self.close_map_worker()
        finally:
            run.finished = time.monotonic()
        # Only a run that is still this source's current one: a reconnect mid-run cleared
        # the caches, and the old connection's fit must not come back as "previous".
        if not run.failed and self._map_cache.get(source) is run:
            self._map_done[source] = run
    if run.failed:
        return _http_response(422, b"map registration failed\n",
                              extra={"X-Frame-State": "detection-error"})
    result = run.result
    frame = run.frame
    age = max(0.0, time.time() - frame.captured_at)
    width, height = result.image_size
    fit = result.registration.to_dict() if result.registration is not None else None
    body = {
        "source": source,
        "frame_seq": frame.header.seq,
        "frame_age_ms": round(age * 1000),
        "image": {"width": width, "height": height},
        "map_frame": "map",
        "accepted": result.accepted,
        "proposal": fit if result.accepted else None,
        # A rejected fit keeps only placement hints, never a homography to misuse.
        "rejected_fit": None if result.accepted or fit is None else {
            key: fit[key] for key in ("score", "precision", "coverage", "cut_sides",
                                      "cut_directions", "side_outside")},
        "reason": result.reason,
        "registrar": {"version": REGISTER_VERSION, "elapsed_ms": round(result.elapsed_ms, 1)},
    }
    return _http_response(200, (json.dumps(body, separators=(",", ":")) + "\n").encode(), extra={
        "Content-Type": "application/json", "Cache-Control": "no-store",
        "X-Frame-Seq": str(frame.header.seq),
        "X-Frame-Age-Ms": str(round(age * 1000)),
        "X-Proposal-State": state,
    })


def _lens_text(lens: dict) -> str:
    return f"kind={lens['kind']};focal_mm={lens['focal_mm']:g};hfov_deg={lens['hfov_deg']:g}"


def _lens_header(lens: dict | None) -> dict[str, str]:
    """``X-Source-Lens`` for preview readers; absent when the app did not report a lens."""
    return {"X-Source-Lens": _lens_text(lens)} if lens else {}


def _plane_unavailable() -> Response:
    return _http_response(409, b"map plane unavailable\n", extra={"X-Frame-State": "plane-unavailable"})


def _http_response(status: int, body: bytes, *, extra: Mapping[str, str] | None = None) -> Response:
    reason = {200: "OK", 401: "Unauthorized", 404: "Not Found", 409: "Conflict",
              422: "Unprocessable Content", 429: "Too Many Requests",
              503: "Service Unavailable"}[status]
    headers = Headers({"Content-Length": str(len(body)), "X-Content-Type-Options": "nosniff",
                       "Cache-Control": "no-store", **dict(extra or {})})
    return Response(status, reason, headers, body)
