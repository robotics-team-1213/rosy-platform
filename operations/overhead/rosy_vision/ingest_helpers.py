"""Per-source state dataclasses and HTTP/preview request handlers for :class:`IngestServer`.

Extracted from ``ingest.py`` to keep WebSocket connection lifecycle and HTTP preview
handlers modular; ``IngestServer`` binds the handler methods directly.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import cv2
from websockets.http11 import Response

from core_common.protocol.vision_preview import PreviewRectification, VisionLeaseError
from rosy_vision import ingest_proposals, protocol
from rosy_vision.ingest_proposals import _http_response
from rosy_vision.loops import readyz_body
from rosy_vision.preview_plane import map_plane_response, rectified_jpeg

if TYPE_CHECKING:
    from websockets.asyncio.server import ServerConnection

# D-484: a field-calibration report older than this no longer rectifies the
# preview (the worker stopped feeding detections; show the raw frame instead).
FIELD_REPORT_TTL_S = 5.0
_STATS_WINDOW_S = 1.0
# Minimum spacing between one viewer's frame reads of one source.
_FRAME_INTERVAL_S = 0.2
# Field proposals (D-360) are operator-requested and CPU-bound: own, slower bucket.
_FIELD_PROPOSAL_INTERVAL_S = 1.0
# D-341 11: an upgrade refused because the paired-credential state is unknown asks the phone
# to come back after one sync interval.
_PAIRING_RETRY_AFTER_S = 2


@dataclass
class SourceStats:
    """Rolling per-source counters. ``snapshot()`` is what the CLI/tests read."""

    frames: int = 0
    dropped_bad_header: int = 0
    oversize: int = 0
    last_seq: int | None = None
    seq_gaps: int = 0
    _window: deque[tuple[float, int, int]] = field(default_factory=deque)  # (ts, bytes, age_ms)

    def record_frame(self, ts: float, size: int, age_ms: int, seq: int) -> None:
        self.frames += 1
        if self.last_seq is not None:
            gap = (seq - self.last_seq - 1) & 0xFFFFFFFF
            # A wrap-to-zero restart (new connection) is not a gap.
            if seq > self.last_seq:
                self.seq_gaps += gap
        self.last_seq = seq
        self._window.append((ts, size, age_ms))
        self._trim(ts)

    def _trim(self, now: float) -> None:
        while self._window and now - self._window[0][0] > _STATS_WINDOW_S:
            self._window.popleft()

    def snapshot(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        self._trim(now)
        ages = sorted(age for _, _, age in self._window)
        sizes = [size for _, size, _ in self._window]
        mid = len(ages) // 2
        return {
            "frames": self.frames,
            "rx_fps": len(self._window),
            "bytes_per_s": sum(sizes),
            "age_ms_p50": ages[mid] if ages else 0,
            "age_ms_max": max(ages) if ages else 0,
            "dropped_bad_header": self.dropped_bad_header,
            "oversize": self.oversize,
            "last_seq": self.last_seq,
            "seq_gaps": self.seq_gaps,
        }


@dataclass
class LatestFrame:
    header: protocol.FrameHeader
    jpeg: bytes
    captured_at: float
    received_at: float


@dataclass
class _Source:
    name: str
    connection: ServerConnection
    stats: SourceStats = field(default_factory=SourceStats)
    latest: LatestFrame | None = None
    # (corner ids, robot ids, monotonic report time) from the Vision worker.
    markers: tuple[tuple[int, ...], tuple[str, ...], float] | None = None
    # D-484: the worker's last field-calibration report (dict + monotonic time).
    field: tuple[dict, float] | None = None
    # Optional hello.lens ({"kind", "focal_mm", "hfov_deg"}); None for older apps.
    lens: dict | None = None
    # D-341: SHA-256 of a paired phone's bearer (never the bearer) and its credential id.
    credential_digest: bytes | None = None
    credential_id: str | None = None
    # D-589: this connection's number (a reconnect gets a new one) and the phone's last
    # valid camera_state; None until the phone reports one (older apps never do).
    link: int = 0
    camera_state: protocol.CameraState | None = None
    # D-691: last demand.wanted sent on this connection. None until the first send.
    demand_sent: bool | None = None


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


async def _process_request(self, connection: ServerConnection, request):
    if request.path == "/healthz" and request.method == "GET":
        return connection.respond(200, '{"status":"ok"}\n')
    if request.path == "/readyz" and request.method == "GET":
        return connection.respond(*readyz_body(self.loop_watch))
    if request.path.startswith("/api/vision/sources/"):
        if request.method != "GET":
            return _http_response(404, b"not found\n")
        return await self._preview_response(request.path, request.headers.get("Authorization"))
    if request.path != protocol.WS_PATH:
        return connection.respond(404, "not found\n")
    auth = request.headers.get("Authorization")
    authorized = False
    for token in self.source_tokens.values():
        authorized |= hmac.compare_digest(auth or "", f"Bearer {token}")
    if authorized:
        return None
    if self.paired is not None:
        verdict = self.paired.check_any(_bearer_digest(auth))
        if verdict == "ok":
            return None
        if verdict == "unavailable":
            # Retryable (D-341 11): the phone keeps its credential and backs off.
            return _http_response(503, b"credential state unavailable\n",
                                  extra={"Retry-After": str(_PAIRING_RETRY_AFTER_S)})
    return connection.respond(401, "unauthorized\n")


async def _preview_response(self, path: str, authorization: str | None) -> Response:
    """Serve one authorized latest-frame read directly from Vision, never from Fleet."""
    prefix = "/api/vision/sources/"
    source, _, view = path[len(prefix):].partition("/") if path.startswith(prefix) else ("", "", "")
    if (not source or view not in ("frame", "field-proposal", "map-proposal", "draft-map", "measured-status")
            or self.preview_signer is None):
        return _http_response(404, b"not found\n")
    bearer = authorization[len("Bearer "):] if authorization and authorization.startswith("Bearer ") else ""
    try:
        lease = self.preview_signer.verify(bearer, source_id=source)
    except VisionLeaseError:
        return _http_response(401, b"unauthorized\n")
    # A missing, stale, or rate-limited frame is still a request (D-691).
    self.hold_stream(source)
    if view == 'measured-status':
        return _http_response(200, json.dumps(self.measured_status(source)).encode(), extra={
            'Content-Type': 'application/json', 'Cache-Control': 'no-store'})
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
    if view in ("map-proposal", "draft-map"):
        return await ingest_proposals.proposal_response(self, view, source, frame)
    jpeg = frame.jpeg
    if 'measured' in lease:
        from rosy_vision.measured_preview import frame_response
        return await frame_response(self, source, frame, lease)
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
                jpeg = await rectified_jpeg(self, source, frame, settings)
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


async def _map_plane_response(self, source, frame, age, lease=None):
    return await map_plane_response(self, source, frame, age, lease,
                                    unavailable=_plane_unavailable, response=_http_response,
                                    lens_header=_lens_header)


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


def _bearer_digest(authorization: str | None) -> bytes:
    bearer = authorization[len("Bearer "):] if authorization and authorization.startswith("Bearer ") else ""
    return hashlib.sha256(bearer.encode("utf-8")).digest()


def _lens_text(lens: dict) -> str:
    return f"kind={lens['kind']};focal_mm={lens['focal_mm']:g};hfov_deg={lens['hfov_deg']:g}"


def _lens_header(lens: dict | None) -> dict[str, str]:
    """``X-Source-Lens`` for preview readers; absent when the app did not report a lens."""
    return {"X-Source-Lens": _lens_text(lens)} if lens else {}


def _plane_unavailable() -> Response:
    return _http_response(409, b"map plane unavailable\n", extra={"X-Frame-State": "plane-unavailable"})
