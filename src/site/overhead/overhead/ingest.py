"""Receive-only WebSocket ingest server for ``rosy-overhead/1`` (D-261 A2).

Accepts one connection per ``source`` at :data:`overhead.protocol.WS_PATH`,
keeps only the latest JPEG frame per source (never queues), and reports
per-source stats. No marker detection, no Fleet sightings — that is D-257
scope, not this ADR's.

Clock: ``captured_at`` is computed from this process's own wall clock
(``time.time()``) minus the frame's ``age_ms``, per design §3 — the phone's
clock is never trusted, only its reported elapsed time.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import ssl
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Mapping

import websockets

try:
    from websockets.asyncio.server import Server, ServerConnection, serve
except ImportError as exc:  # apt python3-websockets on Ubuntu 24.04 is 10.x
    raise ImportError(
        f"overhead needs websockets>=14 (found {websockets.__version__}); "
        "install it with pip in the site-PC venv"
    ) from exc

from overhead import protocol

STATUS_INTERVAL_S = 1.0
# A peer that upgrades but never sends hello is closed after this long.
HELLO_TIMEOUT_S = 5.0
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


class IngestServer:
    """One ``rosy-overhead/1`` receive-only endpoint. Latest-frame-per-source only."""

    def __init__(self, source_tokens: Mapping[str, str], config: dict | None = None) -> None:
        if not source_tokens:
            raise ValueError("at least one source token is required")
        tokens = dict(source_tokens)
        for source, token in tokens.items():
            if not isinstance(source, str) or not protocol.SOURCE_PATTERN.fullmatch(source):
                raise ValueError(f"invalid source name {source!r}")
            if not isinstance(token, str) or not token:
                raise ValueError(f"source {source!r} needs a non-empty token")
        if len(set(tokens.values())) != len(tokens):
            raise ValueError("each source must have a unique token")
        self.source_tokens = tokens
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
        )

    def source_names(self) -> list[str]:
        return list(self._sources)

    def stats(self, source: str) -> dict | None:
        src = self._sources.get(source)
        return src.stats.snapshot() if src is not None else None

    def latest_frame(self, source: str) -> LatestFrame | None:
        src = self._sources.get(source)
        return src.latest if src is not None else None

    # -- handshake --------------------------------------------------------

    def _process_request(self, connection: ServerConnection, request):
        if request.path == "/healthz" and request.method == "GET":
            return connection.respond(200, '{"status":"ok"}\n')
        if request.path != protocol.WS_PATH:
            return connection.respond(404, "not found\n")
        auth = request.headers.get("Authorization")
        authorized = False
        for token in self.source_tokens.values():
            authorized |= hmac.compare_digest(auth or "", f"Bearer {token}")
        if not authorized:
            return connection.respond(401, "unauthorized\n")
        return None

    # -- per-connection lifecycle ------------------------------------------

    async def _handler(self, connection: ServerConnection) -> None:
        source_name: str | None = None
        try:
            raw = await asyncio.wait_for(connection.recv(), HELLO_TIMEOUT_S)
        except asyncio.TimeoutError:
            await connection.close(protocol.CLOSE_BAD_PROTO, "no hello")
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
        expected = self.source_tokens.get(source_name)
        auth = connection.request.headers.get("Authorization")
        if expected is None or not hmac.compare_digest(auth or "", f"Bearer {expected}"):
            await connection.close(protocol.CLOSE_UNAUTHORIZED, "token is not authorized for source")
            return
        replaced = self._sources.get(source_name)
        src = _Source(name=source_name, connection=connection)
        self._sources[source_name] = src
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
    async def _close_replaced(connection: ServerConnection) -> None:
        try:
            await asyncio.wait_for(
                connection.close(protocol.CLOSE_REPLACED, "replaced by new connection"),
                _REPLACED_CLOSE_TIMEOUT_S,
            )
        except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
            connection.transport.abort()

    def _drop_if_current(self, source_name: str, connection: ServerConnection) -> None:
        current = self._sources.get(source_name)
        if current is not None and current.connection is connection:
            del self._sources[source_name]

    async def _status_loop(self, src: _Source) -> None:
        while True:
            await asyncio.sleep(STATUS_INTERVAL_S)
            snap = src.stats.snapshot()
            status = {
                "type": "status",
                "corners_seen": [],
                "corners_needed": 4,
                "robots_seen": [],
                "rx_fps": snap["rx_fps"],
                "dropped": snap["dropped_bad_header"] + snap["oversize"],
            }
            try:
                await src.connection.send(json.dumps(status))
            except websockets.exceptions.ConnectionClosed:
                return

    def _handle_frame(self, src: _Source, message: bytes) -> None:
        now = time.time()
        try:
            header = protocol.parse_header(message)
        except protocol.HeaderError:
            src.stats.dropped_bad_header += 1
            return
        jpeg = message[protocol.HEADER_SIZE :]
        if len(jpeg) > self.config["max_bytes"]:
            src.stats.oversize += 1
            return
        captured_at = now - header.age_ms / 1000.0
        src.latest = LatestFrame(header=header, jpeg=jpeg, captured_at=captured_at, received_at=now)
        src.stats.record_frame(now, len(jpeg), header.age_ms, header.seq)
