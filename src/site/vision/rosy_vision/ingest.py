"""Receive-only WebSocket ingest server for ``rosy-overhead/1`` (D-261 A2).

Accepts one connection per ``source`` at :data:`rosy_vision.protocol.WS_PATH`,
keeps only the latest JPEG frame per source (never queues), and reports
per-source stats. No marker detection, no Fleet sightings — that is D-257
scope, not this ADR's. The Vision worker may hand back the marker ids it saw
(:meth:`IngestServer.report_markers`) so ``status`` can guide the installer.

Clock: ``captured_at`` is computed from this process's own wall clock
(``time.time()``) minus the frame's ``age_ms``, per design §3 — the phone's
clock is never trusted, only its reported elapsed time.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import json
import logging
import ssl
import time
from collections import deque
from concurrent.futures import BrokenExecutor, Executor
from dataclasses import dataclass, field
from typing import Mapping

import websockets
import cv2

try:
    from websockets.asyncio.server import Server, ServerConnection, serve
    from websockets.http11 import Headers, Response
except ImportError as exc:  # apt python3-websockets on Ubuntu 24.04 is 10.x
    raise ImportError(
        f"overhead needs websockets>=14 (found {websockets.__version__}); "
        "install it with pip in the site-PC venv"
    ) from exc

from rosy_vision import protocol
from core_common.protocol.vision_preview import (
    PreviewRectification, VisionLeaseError, VisionLeaseSigner,
)
from rosy_vision.field_detect import DETECTOR_VERSION, FieldDetection, detect_field_jpeg
from rosy_vision import map_worker
from rosy_vision.map_register import REGISTER_VERSION, MapPaint, RegistrationResult
from rosy_vision.pairing_sync import PairedCredentials
from rosy_vision.rectify import rectify_jpeg

logger = logging.getLogger(__name__)
# websockets logs every handshake header at DEBUG, the phone's Authorization included.
# The server gets its own logger pinned at INFO so no log level ever records a bearer.
_WS_LOGGER = logging.getLogger(__name__ + ".websocket")
_WS_LOGGER.setLevel(logging.INFO)

STATUS_INTERVAL_S = 1.0
# A marker report older than this is not repeated in ``status`` (worker stopped
# detecting, e.g. frames went stale); the phone then sees empty lists again.
MARKER_REPORT_TTL_S = 3.0
# A peer that upgrades but never sends hello is closed after this long, counted in
# steps of _HELLO_STEP_S so a stalled event loop cannot use the peer's time up.
HELLO_TIMEOUT_S = 5.0
_HELLO_STEP_S = 0.25
# Frames websockets may hold for one connection before it stops reading the
# socket (D-136 6항: latest only, no backlog). TCP flow control does the rest.
RECEIVE_QUEUE_FRAMES = 1
# Room above max_bytes so an oversize frame reaches _handle_frame and is
# dropped and counted instead of closing the connection with 1009.
_MAX_SIZE_MARGIN = 64 * 1024
# How long a replaced connection gets to finish its close handshake before
# its transport is aborted. Runs in the background; never delays the new one.
_REPLACED_CLOSE_TIMEOUT_S = 2.0
_STATS_WINDOW_S = 1.0
# Minimum spacing between one viewer's frame reads of one source.
_FRAME_INTERVAL_S = 0.2
# Field proposals (D-360) are operator-requested and CPU-bound: own, slower bucket.
_FIELD_PROPOSAL_INTERVAL_S = 1.0
# Field detection is ~30 ms of CPU per frame: at most one run per source per this
# interval, whoever asks; readers in between get the last result.
_FIELD_DETECT_INTERVAL_S = 1.0
# Map registration (D-375) is seconds of CPU per frame and runs in a separate worker
# process (never on this event loop's threads): one run in flight per source, the next
# at least this long after the last one finished, one worker for all sources.
_MAP_REGISTER_INTERVAL_S = 1.0
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


@dataclass
class _Source:
    name: str
    connection: ServerConnection
    stats: SourceStats = field(default_factory=SourceStats)
    latest: LatestFrame | None = None
    # (corner ids, robot ids, monotonic report time) from the Vision worker.
    markers: tuple[tuple[int, ...], tuple[str, ...], float] | None = None
    # Optional hello.lens ({"kind", "focal_mm", "hfov_deg"}); None for older apps.
    lens: dict | None = None
    # D-341: SHA-256 of a paired phone's bearer (never the bearer) and its credential id.
    credential_digest: bytes | None = None
    credential_id: str | None = None


class IngestServer:
    """One ``rosy-overhead/1`` receive-only endpoint. Latest-frame-per-source only."""

    def __init__(self, source_tokens: Mapping[str, str], config: dict | None = None,
                 *, preview_signer: VisionLeaseSigner | None = None,
                 preview_max_age_s: float = 1.0, map_paint: MapPaint | None = None,
                 paired: PairedCredentials | None = None) -> None:
        if not source_tokens and paired is None:
            raise ValueError("at least one source token or paired source is required")
        tokens = dict(source_tokens)
        if paired is not None:
            for source in paired.sources:
                if not protocol.SOURCE_PATTERN.fullmatch(source):
                    raise ValueError(f"invalid source name {source!r}")
            if paired.sources & set(tokens):
                raise ValueError("a source cannot be both static and paired")
        # D-341 12: paired sources authenticate by Fleet-synced digest, never a stored token.
        self.paired = paired
        for source, token in tokens.items():
            if not isinstance(source, str) or not protocol.SOURCE_PATTERN.fullmatch(source):
                raise ValueError(f"invalid source name {source!r}")
            if not isinstance(token, str) or not token:
                raise ValueError(f"source {source!r} needs a non-empty token")
        if len(set(tokens.values())) != len(tokens):
            raise ValueError("each source must have a unique token")
        self.source_tokens = tokens
        self.preview_signer = preview_signer
        if not isinstance(preview_max_age_s, (int, float)) or preview_max_age_s <= 0:
            raise ValueError("preview_max_age_s must be positive")
        self.preview_max_age_s = float(preview_max_age_s)
        self._preview_last_sent: dict[tuple[str, ...], float] = {}
        # Last detection per source, keyed by frame identity (a reconnect restarts seq);
        # dropped with the source.
        self._field_cache: dict[str, _FieldRun] = {}
        # D-375: site map lane paint for the map-proposal view; None disables the view.
        self.map_paint = map_paint
        self._map_cache: dict[str, _MapRun] = {}
        self._map_done: dict[str, _MapRun] = {}  # last successful run, served while the next runs
        # Started on the first map proposal; tests may swap in another executor or job.
        self._map_executor: Executor | None = None
        self._map_job = map_worker.register
        self.config: dict = dict(protocol.DEFAULT_CONFIG if config is None else config)
        self._sources: dict[str, _Source] = {}
        self._closing: set[asyncio.Task] = set()

    async def start(self, host: str, port: int, *, ssl_context: ssl.SSLContext | None = None) -> Server:
        return await serve(
            self._handler,
            host,
            port,
            process_request=self._process_request,
            max_size=self.config["max_bytes"] + protocol.HEADER_SIZE + _MAX_SIZE_MARGIN,
            max_queue=RECEIVE_QUEUE_FRAMES,
            ssl=ssl_context,
            logger=_WS_LOGGER,
        )

    def close_map_worker(self) -> None:
        """Stop the map-registration worker process (a new one starts on the next proposal)."""
        executor, self._map_executor = self._map_executor, None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    def source_names(self) -> list[str]:
        return list(self._sources)

    def stats(self, source: str) -> dict | None:
        src = self._sources.get(source)
        return src.stats.snapshot() if src is not None else None

    def latest_frame(self, source: str) -> LatestFrame | None:
        src = self._sources.get(source)
        return src.latest if src is not None else None

    def source_lens(self, source: str) -> dict | None:
        """The lens ``source`` reported in its hello, or None (older app, or not connected)."""
        return getattr(self._sources.get(source), "lens", None)

    def report_markers(self, source: str, corners_seen, robots_seen) -> None:
        """Record which configured marker ids the worker saw on ``source``'s latest frame."""
        src = self._sources.get(source)
        if src is None:
            return
        src.markers = (tuple(sorted(set(corners_seen))), tuple(sorted(set(robots_seen))),
                       time.monotonic())

    def _marker_status(self, src: _Source) -> tuple[list[int], list[str]]:
        if src.markers is None or time.monotonic() - src.markers[2] > MARKER_REPORT_TTL_S:
            return [], []
        return list(src.markers[0]), list(src.markers[1])

    # -- handshake --------------------------------------------------------

    async def _process_request(self, connection: ServerConnection, request):
        if request.path == "/healthz" and request.method == "GET":
            return connection.respond(200, '{"status":"ok"}\n')
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
        if (not source or view not in ("frame", "field-proposal", "map-proposal")
                or self.preview_signer is None):
            return _http_response(404, b"not found\n")
        bearer = authorization[len("Bearer "):] if authorization and authorization.startswith("Bearer ") else ""
        try:
            lease = self.preview_signer.verify(bearer, source_id=source)
        except VisionLeaseError:
            return _http_response(401, b"unauthorized\n")
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
        rectification_active = False
        if "rectification" in lease:
            try:
                settings = PreviewRectification.from_mapping(lease["rectification"])
                rectification_active = not settings.is_identity
                if rectification_active:
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
            "X-Frame-Rectified": "true" if rectification_active else "false",
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

    # -- per-connection lifecycle ------------------------------------------

    async def _handler(self, connection: ServerConnection) -> None:
        source_name: str | None = None
        try:
            raw = await _receive_hello(connection)
        except asyncio.TimeoutError:
            await connection.close(protocol.CLOSE_HELLO_TIMEOUT, "no hello in time; retry")
            return
        except websockets.exceptions.ConnectionClosed:
            return
        if not isinstance(raw, str):
            await connection.close(protocol.CLOSE_BAD_PROTO, "expected hello text message")
            return
        try:
            hello = json.loads(raw)
            protocol.validate_hello(hello)
        except (json.JSONDecodeError, protocol.HelloError) as exc:
            await connection.close(protocol.CLOSE_BAD_PROTO, str(exc))
            return

        source_name = hello["source"]
        auth = connection.request.headers.get("Authorization")
        credential_digest = credential_id = None
        if self.paired is not None and source_name in self.paired.sources:
            credential_digest = _bearer_digest(auth)
            verdict, credential_id = self.paired.check(source_name, credential_digest)
            if verdict == "unavailable":
                await connection.close(protocol.CLOSE_CREDENTIAL_UNKNOWN,
                                       "credential state unavailable; retry")
                return
            if verdict != "ok":
                await connection.close(protocol.CLOSE_UNAUTHORIZED, "token is not authorized for source")
                return
        else:
            expected = self.source_tokens.get(source_name)
            if expected is None or not hmac.compare_digest(auth or "", f"Bearer {expected}"):
                await connection.close(protocol.CLOSE_UNAUTHORIZED, "token is not authorized for source")
                return
        replaced = self._sources.get(source_name)
        src = _Source(name=source_name, connection=connection, lens=protocol.parse_hello_lens(hello),
                      credential_digest=credential_digest, credential_id=credential_id)
        sensor = hello["sensor"]
        # app_version/device are free text from the phone: repr and cap them in the log.
        logger.info("source %s connected app=%r device=%r sensor=%sx%s rot=%s lens=%s credential=%s",
                    source_name, str(hello.get("app_version"))[:64], str(hello.get("device"))[:64],
                    sensor["width"], sensor["height"], sensor["rotation_deg"],
                    _lens_text(src.lens) if src.lens else "unreported",
                    credential_id or "static")
        self._sources[source_name] = src
        self._field_cache.pop(source_name, None)
        self._map_cache.pop(source_name, None)
        self._map_done.pop(source_name, None)
        if replaced is not None:
            # Never await this inline: a half-open old peer (phone lost Wi-Fi)
            # never answers the close frame and would stall the new connection.
            task = asyncio.create_task(self._close_replaced(replaced.connection))
            self._closing.add(task)
            task.add_done_callback(self._closing.discard)

        try:
            await connection.send(json.dumps(protocol.make_config(**self.config)))
        except websockets.exceptions.ConnectionClosed:
            self._drop_if_current(source_name, connection)
            return

        status_task = asyncio.create_task(self._status_loop(src))
        try:
            async for message in connection:
                if isinstance(message, (bytes, bytearray)):
                    self._handle_frame(src, bytes(message))
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            status_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await status_task
            self._drop_if_current(source_name, connection)

    @staticmethod
    async def _close_replaced(connection: ServerConnection, code: int = protocol.CLOSE_REPLACED,
                              reason: str = "replaced by new connection") -> None:
        try:
            await asyncio.wait_for(connection.close(code, reason), _REPLACED_CLOSE_TIMEOUT_S)
        except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
            connection.transport.abort()

    def _paired_verdict(self, src: _Source) -> str:
        if src.credential_digest is None or self.paired is None:
            return "ok"
        return self.paired.check(src.name, src.credential_digest)[0]

    def enforce_paired_credentials(self) -> None:
        """Close paired connections whose credential left the synced list (D-341 11).

        Runs on the event loop after every sync cycle (the sync thread schedules it).
        Revoked or unknown -> 4401 (final); state unknown -> 4503 (retry). Never awaits
        the close inline, like a replaced connection.
        """
        for src in list(self._sources.values()):
            verdict = self._paired_verdict(src)
            if verdict == "ok":
                continue
            code, reason = ((protocol.CLOSE_UNAUTHORIZED, "credential revoked")
                            if verdict == "unknown" else
                            (protocol.CLOSE_CREDENTIAL_UNKNOWN, "credential state unavailable; retry"))
            logger.info("source %s closed code=%d credential=%s", src.name, code, src.credential_id)
            self._drop_if_current(src.name, src.connection)
            task = asyncio.create_task(self._close_replaced(src.connection, code, reason))
            self._closing.add(task)
            task.add_done_callback(self._closing.discard)

    def _drop_if_current(self, source_name: str, connection: ServerConnection) -> None:
        current = self._sources.get(source_name)
        if current is not None and current.connection is connection:
            del self._sources[source_name]
            self._field_cache.pop(source_name, None)
            self._map_cache.pop(source_name, None)
            self._map_done.pop(source_name, None)

    async def _status_loop(self, src: _Source) -> None:
        while True:
            await asyncio.sleep(STATUS_INTERVAL_S)
            snap = src.stats.snapshot()
            corners_seen, robots_seen = self._marker_status(src)
            status = {
                "type": "status",
                "corners_seen": corners_seen,
                "corners_needed": 4,
                "robots_seen": robots_seen,
                "rx_fps": snap["rx_fps"],
                "dropped": snap["dropped_bad_header"] + snap["oversize"],
            }
            try:
                await src.connection.send(json.dumps(status))
            except websockets.exceptions.ConnectionClosed:
                return

    def _handle_frame(self, src: _Source, message: bytes) -> None:
        if src.credential_digest is not None and self._paired_verdict(src) != "ok":
            return  # revoked or unknown since the last sync: never keep its frames
        now = time.time()
        try:
            header = protocol.parse_header(message)
        except protocol.HeaderError:
            src.stats.dropped_bad_header += 1
            return
        jpeg = message[protocol.HEADER_SIZE:]
        if len(jpeg) > self.config["max_bytes"]:
            src.stats.oversize += 1
            return
        captured_at = now - header.age_ms / 1000.0
        src.latest = LatestFrame(header=header, jpeg=jpeg, captured_at=captured_at, received_at=now)
        src.stats.record_frame(now, len(jpeg), header.age_ms, header.seq)


async def _receive_hello(connection: ServerConnection):
    """First message, or ``TimeoutError`` after ``HELLO_TIMEOUT_S`` of *responsive* waiting.

    Each step charges at most twice its length, so time the loop spent blocked on
    other work is not charged to the peer.
    """
    receive = asyncio.ensure_future(connection.recv())
    budget = HELLO_TIMEOUT_S
    try:
        while True:
            started = time.monotonic()
            done, _ = await asyncio.wait({receive}, timeout=min(_HELLO_STEP_S, budget))
            if done:
                return receive.result()
            budget -= min(time.monotonic() - started, 2 * _HELLO_STEP_S)
            if budget <= 0:
                raise asyncio.TimeoutError
    finally:
        if not receive.done():
            receive.cancel()

def _bearer_digest(authorization: str | None) -> bytes:
    bearer = authorization[len("Bearer "):] if authorization and authorization.startswith("Bearer ") else ""
    return hashlib.sha256(bearer.encode("utf-8")).digest()


def _lens_text(lens: dict) -> str:
    return f"kind={lens['kind']};focal_mm={lens['focal_mm']:g};hfov_deg={lens['hfov_deg']:g}"


def _lens_header(lens: dict | None) -> dict[str, str]:
    """``X-Source-Lens`` for preview readers; absent when the app did not report a lens."""
    return {"X-Source-Lens": _lens_text(lens)} if lens else {}


def _http_response(status: int, body: bytes, *, extra: Mapping[str, str] | None = None) -> Response:
    reason = {200: "OK", 401: "Unauthorized", 404: "Not Found",
              422: "Unprocessable Content", 429: "Too Many Requests",
              503: "Service Unavailable"}[status]
    headers = Headers({"Content-Length": str(len(body)), "X-Content-Type-Options": "nosniff",
                       "Cache-Control": "no-store", **dict(extra or {})})
    return Response(status, reason, headers, body)
