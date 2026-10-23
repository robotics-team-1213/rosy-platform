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
import itertools
import json
import logging
import re
import ssl
import time
from collections import deque
from concurrent.futures import Executor
from dataclasses import dataclass, field
from typing import Mapping

import websockets

try:
    from websockets.asyncio.server import Server, ServerConnection, serve
    from websockets.http11 import Headers, Response
except ImportError as exc:  # apt python3-websockets on Ubuntu 24.04 is 10.x
    raise ImportError(
        f"overhead needs websockets>=14 (found {websockets.__version__}); "
        "install it with pip in the site-PC venv"
    ) from exc

from rosy_vision import protocol
from core_common.protocol.vision_preview import VisionLeaseSigner
from rosy_vision import map_worker
from rosy_vision.map_register import MapPaint
from rosy_vision.pairing_sync import PairedCredentials
from rosy_vision import ingest_preview
from rosy_vision.ingest_preview import _FieldRun, _MapRun, _http_response, _lens_text, FIELD_REPORT_TTL_S
from rosy_vision.stream_demand import StreamDemand

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
# D-341 11: an upgrade refused because the paired-credential state is unknown asks the phone
# to come back after one sync interval.
_PAIRING_RETRY_AFTER_S = 2
# D-560: a calibration revision travels in X-Frame-Calibration; anything else is no record.
_REVISION = re.compile(r"[A-Za-z0-9._:-]{1,96}")


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


class IngestServer:
    """One ``rosy-overhead/1`` receive-only endpoint. Latest-frame-per-source only."""

    def __init__(self, source_tokens: Mapping[str, str], config: dict | None = None,
                 *, preview_signer: VisionLeaseSigner | None = None,
                 preview_max_age_s: float = 1.0, map_paint: MapPaint | None = None,
                 paired: PairedCredentials | None = None,
                 measurement_sources: frozenset[str] = frozenset(),
                 source_widths: Mapping[str, int] | None = None) -> None:
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
        configured_sources = set(tokens) | (paired.sources if paired is not None else set())
        self._measurement_sources = frozenset(measurement_sources)
        self._source_widths = dict(source_widths or {})
        if (self._measurement_sources - configured_sources or self._source_widths.keys() - configured_sources
                or any(type(width) is not int or not 32 <= width <= 8192 for width in self._source_widths.values())):
            raise ValueError('STATION_MEASUREMENT_SOURCE_CONFIG_INVALID')
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
        # D-560: the approved tracking record per source as the track worker last read it
        # from Fleet ((record, the worker's map_id)), and the last map plane per source,
        # keyed by frame identity and record revision.
        self._plane_records: dict[str, tuple[Mapping, str]] = {}
        self._plane_cache: dict[str, tuple[LatestFrame, str, asyncio.Future]] = {}
        self.config: dict = dict(protocol.DEFAULT_CONFIG if config is None else config)
        self._sources: dict[str, _Source] = {}
        self._closing: set[asyncio.Task] = set()
        self._links = itertools.count(1)
        # D-691: authorized preview reads keep the phone sending for a hold.
        self._demand = StreamDemand()
        self._demand_tasks: set[asyncio.Task] = set()

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

    def camera_link(self, source: str) -> tuple[int | None, protocol.CameraState | None]:
        """D-589: (connection number, last valid camera_state) of ``source``; (None, None) when
        it is not connected."""
        src = self._sources.get(source)
        return (None, None) if src is None else (src.link, src.camera_state)

    async def send_camera(self, source: str, message: dict) -> bool:
        """D-589: send a downlink ``camera`` text message on ``source``'s connection."""
        src = self._sources.get(source)
        if src is None:
            return False
        try:
            await src.connection.send(json.dumps(message, separators=(",", ":")))
        except websockets.exceptions.ConnectionClosed:
            return False
        return True

    def report_markers(self, source: str, corners_seen, robots_seen) -> None:
        """Record which configured marker ids the worker saw on ``source``'s latest frame."""
        src = self._sources.get(source)
        if src is None:
            return
        src.markers = (tuple(sorted(set(corners_seen))), tuple(sorted(set(robots_seen))),
                       time.monotonic())

    def report_field(self, source: str, report: dict) -> None:
        """Record the worker's latest field-boundary calibration report (D-484)."""
        src = self._sources.get(source)
        if src is None:
            return
        src.field = (dict(report), time.monotonic())

    def report_calibration(self, source: str, record: Mapping | None, map_id: str) -> None:
        """Record the approved tracking calibration the track worker read from Fleet (D-560)."""
        revision = record.get("calibration_revision") if isinstance(record, Mapping) else None
        if isinstance(revision, str) and _REVISION.fullmatch(revision):
            self._plane_records[source] = (record, map_id)
        else:
            self._plane_records.pop(source, None)

    _field_corners = ingest_preview._field_corners

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

    _preview_response = ingest_preview._preview_response

    _map_plane_response = ingest_preview._map_plane_response

    _rate_limited = ingest_preview._rate_limited

    _field_proposal_response = ingest_preview._field_proposal_response

    _map_proposal_response = ingest_preview._map_proposal_response

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
                      credential_digest=credential_digest, credential_id=credential_id,
                      link=next(self._links))
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
        self._plane_cache.pop(source_name, None)
        if replaced is not None:
            # Never await this inline: a half-open old peer (phone lost Wi-Fi)
            # never answers the close frame and would stall the new connection.
            task = asyncio.create_task(self._close_replaced(replaced.connection))
            self._closing.add(task)
            task.add_done_callback(self._closing.discard)

        try:
            source_config = self.config | ({'width': self._source_widths[source_name]}
                if source_name in self._source_widths else {})
            await connection.send(json.dumps(protocol.make_config(**source_config)))
            await self._send_demand(src, force=True)
        except websockets.exceptions.ConnectionClosed:
            self._drop_if_current(source_name, connection)
            return

        status_task = asyncio.create_task(self._status_loop(src))
        try:
            async for message in connection:
                if isinstance(message, (bytes, bytearray)):
                    self._handle_frame(src, bytes(message))
                else:
                    self._handle_text(src, message)
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
            self._plane_cache.pop(source_name, None)

    def _status_message(self, src: _Source) -> dict:
        snap = src.stats.snapshot()
        corners_seen, robots_seen = self._marker_status(src)
        # A field_boundary source calibrates from the floor boundary (D-484), not four
        # corner markers: report its calibration state so the phone stops asking for markers.
        field = src.field
        field_state = (field[0].get("state") if field is not None
                       and time.monotonic() - field[1] <= MARKER_REPORT_TTL_S else None)
        return {
            "type": "status",
            "corners_seen": corners_seen,
            "corners_needed": 0 if field_state is not None else 4,
            "robots_seen": robots_seen,
            "rx_fps": snap["rx_fps"],
            "dropped": snap["dropped_bad_header"] + snap["oversize"],
            "field_state": field_state,
        }

    async def _status_loop(self, src: _Source) -> None:
        while True:
            await asyncio.sleep(STATUS_INTERVAL_S)
            status = self._status_message(src)
            try:
                await src.connection.send(json.dumps(status))
                await self._send_demand(src)
            except websockets.exceptions.ConnectionClosed:
                return

    def _note_stream_request(self, source: str) -> None:
        """An authorized preview read asks ``source`` to send (D-691)."""
        if not self._demand.note(source):
            return
        src = self._sources.get(source)
        if getattr(src, "connection", None) is None:
            return
        task = asyncio.create_task(self._send_demand(src))
        self._demand_tasks.add(task)
        task.add_done_callback(self._demand_tasks.discard)

    async def _send_demand(self, src: _Source, *, force: bool = False) -> None:
        wanted = src.name in self._measurement_sources or self._demand.wanted(src.name)
        if not force and src.demand_sent is wanted:
            return
        try:
            await src.connection.send(json.dumps(protocol.make_demand(wanted)))
        except websockets.exceptions.ConnectionClosed:
            return
        src.demand_sent = wanted

    async def stop_measurements(self) -> None:
        """D-774 installed owner shutdown; ordinary preview demand keeps its own hold."""
        sources, self._measurement_sources = self._measurement_sources, frozenset()
        for source in sources:
            src = self._sources.get(source)
            if src is not None:
                try:
                    await asyncio.wait_for(self._send_demand(src), timeout=1.)
                except TimeoutError:
                    pass  # The owning server closes the connection next.

    def _handle_text(self, src: _Source, message: str) -> None:
        """D-589: keep a valid ``camera_state``; any other or malformed text is ignored."""
        if src.credential_digest is not None and self._paired_verdict(src) != "ok":
            return
        if len(message) > protocol.MAX_TEXT_CHARS:
            return
        try:
            state = protocol.parse_camera_state(json.loads(message))
        except (ValueError, protocol.CameraMessageError) as exc:
            logger.debug("source %s text message ignored reason=%s", src.name,
                         getattr(exc, "reason", "json"))
            return
        previous = src.camera_state
        if previous is None or (previous.applied, previous.mode) != (state.applied, state.mode):
            logger.info("source %s camera applied %s mode=%s seq=%d thermal=%d", src.name,
                        state.applied.fingerprint(), state.mode, state.seq, state.thermal)
        src.camera_state = state

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
