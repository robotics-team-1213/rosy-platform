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
import hmac
import itertools
import json
import logging
import re
import ssl
import time
from concurrent.futures import Executor
from typing import Mapping

import websockets

try:
    from websockets.asyncio.server import Server, ServerConnection, serve
except ImportError as exc:  # apt python3-websockets on Ubuntu 24.04 is 10.x
    raise ImportError(
        f"overhead needs websockets>=14 (found {websockets.__version__}); "
        "install it with pip in the site-PC venv"
    ) from exc

from core_common.protocol.vision_preview import VisionLeaseSigner
from rosy_vision import ingest_helpers, ingest_proposals, map_worker, protocol
from rosy_vision.ingest_helpers import (  # noqa: F401
    FIELD_REPORT_TTL_S,
    LatestFrame,
    SourceStats,
    _FIELD_PROPOSAL_INTERVAL_S,
    _FRAME_INTERVAL_S,
    _PAIRING_RETRY_AFTER_S,
    _STATS_WINDOW_S,
    _Source,
    _bearer_digest,
    _lens_header,
    _lens_text,
    _plane_unavailable,
)
from rosy_vision.ingest_proposals import _FieldRun, _MapRun, _http_response  # noqa: F401 (moved; tests and measured_preview import them here)
from rosy_vision.ingest_status import MARKER_REPORT_TTL_S, marker_status, status_message  # noqa: F401
from rosy_vision.loops import LoopWatch
from rosy_vision.map_register import MapPaint
from rosy_vision.pairing_sync import PairedCredentials
from rosy_vision.stream_demand import StreamDemand

logger = logging.getLogger(__name__)
# websockets logs every handshake header at DEBUG, the phone's Authorization included.
# The server gets its own logger pinned at INFO so no log level ever records a bearer.
_WS_LOGGER = logging.getLogger(__name__ + ".websocket")
_WS_LOGGER.setLevel(logging.INFO)

STATUS_INTERVAL_S = 1.0
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
# D-560: a calibration revision travels in X-Frame-Calibration; anything else is no record.
_REVISION = re.compile(r"[A-Za-z0-9._:-]{1,96}")


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
        self.loop_watch = LoopWatch()  # death-watch: /readyz 503 on a dead loop, /healthz untouched
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
        from rosy_vision.measured_preview import MeasuredPreview
        self.measured = MeasuredPreview()
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

    def report_measured_config(self, source, config, map_id):
        self.measured.update(source, config, map_id)

    def measured_status(self, source):
        from rosy_vision.measured_preview import current_status
        return current_status(self, source)

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

    # -- handshake & preview handlers (bound from ingest_helpers / ingest_proposals) --
    _field_corners = ingest_helpers._field_corners
    _process_request = ingest_helpers._process_request
    _preview_response = ingest_helpers._preview_response
    _map_plane_response = ingest_helpers._map_plane_response
    _rate_limited = ingest_helpers._rate_limited
    _field_proposal_response = ingest_proposals._field_proposal_response
    _map_proposal_response = ingest_proposals._map_proposal_response  # tests drive this handler directly

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

        status_task = self.loop_watch.supervised(f"status:{source_name}", self._status_loop(src))
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

    def _marker_status(self, src: _Source) -> tuple[list[int], list[str]]:
        return marker_status(src, time.monotonic())

    def _status_message(self, src: _Source) -> dict:
        return status_message(src.stats.snapshot(), *self._marker_status(src), src.field, time.monotonic(),
                              MARKER_REPORT_TTL_S)

    async def _status_loop(self, src: _Source) -> None:
        while True:
            await asyncio.sleep(STATUS_INTERVAL_S)
            status = self._status_message(src)
            try:
                await src.connection.send(json.dumps(status))
                await self._send_demand(src)
            except websockets.exceptions.ConnectionClosed:
                return

    def hold_stream(self, source: str) -> None:
        """An authorized preview read (D-691) or Fleet's locate session (D-989) asks ``source`` to send."""
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
        self.measured.observe(src.name, self.measured.session_id(src.link, src.name), {
            'image_size': [header.width, header.height], 'rotation_deg': header.rotation_deg, 'lens': src.lens})
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
