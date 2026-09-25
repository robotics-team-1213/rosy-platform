"""Ingest server tests over a real localhost WebSocket on an ephemeral port.

Uses the ``websockets`` client (same library the server uses) rather than
mocks, per design §3: 401 without token, 404 wrong path, 4400 bad proto,
config sent after hello, 4409 on same-source replacement, latest-only
overwrite, oversize drop counted, bad header counted without disconnect,
captured_at derived from age_ms.

Synchronous tests + ``asyncio.run()`` — no pytest-asyncio in this repo (see
src/site/fleet/test/test_server_signals.py).
"""

from __future__ import annotations

import asyncio
import functools
import json
import time

import pytest
import websockets
from websockets.exceptions import ConnectionClosed, InvalidStatus

from overhead import protocol
from overhead.ingest import IngestServer

TOKEN = "test-token"
HELLO = {
    "type": "hello",
    "proto": protocol.PROTO,
    "source": "overhead-1",
    "app_version": "0.1.0",
    "device": "test-device",
    "sensor": {"width": 1280, "height": 720, "rotation_deg": 90},
}


def run_async(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        asyncio.run(fn(*args, **kwargs))

    return wrapper


class _Harness:
    """Owns one IngestServer + the ws_server socket for one test."""

    def __init__(self, config: dict | None = None, tokens: dict[str, str] | None = None):
        self.tokens = tokens or {"overhead-1": TOKEN}
        self.server = IngestServer(self.tokens, config=config)
        self.ws_server = None
        self.url = None

    async def __aenter__(self) -> "_Harness":
        self.ws_server = await self.server.start("127.0.0.1", 0)
        port = self.ws_server.sockets[0].getsockname()[1]
        self.url = f"ws://127.0.0.1:{port}{protocol.WS_PATH}"
        return self

    async def __aexit__(self, *exc):
        self.ws_server.close()
        await self.ws_server.wait_closed()

    async def connect(self, token: str = TOKEN):
        return await websockets.connect(self.url, additional_headers={"Authorization": f"Bearer {token}"})


def _hello(source: str = "overhead-1") -> dict:
    return {**HELLO, "source": source}


def _frame(seq: int, age_ms: int, jpeg: bytes = b"\xff\xd8\xff\xd9") -> bytes:
    header = protocol.FrameHeader(seq=seq, age_ms=age_ms, width=1280, height=720, rotation_deg=90)
    return protocol.pack_header(header) + jpeg


async def _wait_for(predicate, timeout: float = 2.0, interval: float = 0.02):
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        result = predicate()
        if result:
            return result
        await asyncio.sleep(interval)
    raise AssertionError("condition not met before timeout")


@run_async
async def test_missing_token_is_rejected_with_401():
    async with _Harness() as h:
        with pytest.raises(InvalidStatus) as excinfo:
            await websockets.connect(h.url)
        assert excinfo.value.response.status_code == 401


@run_async
async def test_source_token_cannot_authenticate_another_source():
    async with _Harness(tokens={"overhead-1": "camera-one", "overhead-2": "camera-two"}) as h:
        conn = await h.connect("camera-two")
        await conn.send(json.dumps(_hello("overhead-1")))
        with pytest.raises(ConnectionClosed):
            await conn.recv()
        assert conn.close_code == protocol.CLOSE_UNAUTHORIZED
        assert h.server.source_names() == []


@run_async
async def test_unknown_source_is_rejected_even_with_a_valid_source_token():
    async with _Harness(tokens={"overhead-1": "camera-one"}) as h:
        conn = await h.connect("camera-one")
        await conn.send(json.dumps(_hello("overhead-unknown")))
        with pytest.raises(ConnectionClosed):
            await conn.recv()
        assert conn.close_code == protocol.CLOSE_UNAUTHORIZED
        assert h.server.source_names() == []


@run_async
async def test_source_token_authenticates_its_configured_source():
    async with _Harness(tokens={"overhead-1": "camera-one", "overhead-2": "camera-two"}) as h:
        conn = await h.connect("camera-two")
        await conn.send(json.dumps(_hello("overhead-2")))
        assert json.loads(await conn.recv()) == protocol.make_config()
        assert h.server.source_names() == ["overhead-2"]


def test_source_tokens_must_be_valid_and_unique():
    with pytest.raises(ValueError, match="at least one source"):
        IngestServer({})
    with pytest.raises(ValueError, match="unique token"):
        IngestServer({"overhead-1": "shared", "overhead-2": "shared"})


@run_async
async def test_wrong_path_is_rejected_with_404():
    async with _Harness() as h:
        wrong = h.url.rsplit("/", 1)[0] + "/not-the-frames-path"
        with pytest.raises(InvalidStatus) as excinfo:
            await websockets.connect(wrong, additional_headers={"Authorization": f"Bearer {TOKEN}"})
        assert excinfo.value.response.status_code == 404


@run_async
async def test_bad_proto_hello_closes_4400():
    async with _Harness() as h:
        conn = await h.connect()
        await conn.send(json.dumps({**_hello(), "proto": "rosy-overhead/2"}))
        with pytest.raises(ConnectionClosed):
            await conn.recv()
        assert conn.close_code == protocol.CLOSE_BAD_PROTO


@run_async
async def test_config_is_sent_right_after_a_valid_hello():
    async with _Harness() as h:
        conn = await h.connect()
        await conn.send(json.dumps(_hello()))
        reply = json.loads(await conn.recv())
        assert reply == protocol.make_config()


@run_async
async def test_same_source_reconnect_replaces_and_closes_the_old_one_4409():
    async with _Harness() as h:
        old = await h.connect()
        await old.send(json.dumps(_hello()))
        await old.recv()  # config

        new = await h.connect()
        await new.send(json.dumps(_hello()))
        await new.recv()  # config

        with pytest.raises(ConnectionClosed):
            await old.recv()
        assert old.close_code == protocol.CLOSE_REPLACED
        assert h.server.source_names() == ["overhead-1"]


@run_async
async def test_latest_frame_overwrites_never_queues():
    async with _Harness() as h:
        conn = await h.connect()
        await conn.send(json.dumps(_hello()))
        await conn.recv()  # config

        await conn.send(_frame(seq=1, age_ms=10, jpeg=b"frame-one"))
        await conn.send(_frame(seq=2, age_ms=10, jpeg=b"frame-two"))

        await _wait_for(lambda: h.server.stats("overhead-1")["frames"] == 2)
        latest = h.server.latest_frame("overhead-1")
        assert latest.jpeg == b"frame-two"
        assert latest.header.seq == 2


@run_async
async def test_oversize_frame_is_dropped_and_counted():
    async with _Harness(config={**protocol.DEFAULT_CONFIG, "max_bytes": 8}) as h:
        conn = await h.connect()
        await conn.send(json.dumps(_hello()))
        await conn.recv()  # config

        await conn.send(_frame(seq=1, age_ms=5, jpeg=b"way-too-big-for-the-limit"))
        await _wait_for(lambda: h.server.stats("overhead-1")["oversize"] == 1)

        assert h.server.stats("overhead-1")["frames"] == 0
        assert h.server.latest_frame("overhead-1") is None


@run_async
async def test_bad_header_is_dropped_and_counted_without_disconnecting():
    async with _Harness() as h:
        conn = await h.connect()
        await conn.send(json.dumps(_hello()))
        await conn.recv()  # config

        await conn.send(b"not a valid header at all")
        await _wait_for(lambda: h.server.stats("overhead-1")["dropped_bad_header"] == 1)

        # connection must still be open and able to carry a good frame
        await conn.send(_frame(seq=1, age_ms=5, jpeg=b"ok"))
        await _wait_for(lambda: h.server.stats("overhead-1")["frames"] == 1)
        assert h.server.latest_frame("overhead-1").jpeg == b"ok"


@run_async
async def test_captured_at_is_receive_time_minus_age_ms():
    async with _Harness() as h:
        conn = await h.connect()
        await conn.send(json.dumps(_hello()))
        await conn.recv()  # config

        wall_before = time.time()
        await conn.send(_frame(seq=1, age_ms=250, jpeg=b"ok"))
        await _wait_for(lambda: h.server.stats("overhead-1")["frames"] == 1)
        wall_after = time.time()

        latest = h.server.latest_frame("overhead-1")
        assert wall_before - 0.250 - 0.5 <= latest.captured_at <= wall_after - 0.250 + 0.5


async def _half_open_peer(url: str, hello: dict):
    """A raw-socket client that completes the upgrade, sends hello, then goes
    silent without ever answering a close frame — a phone that lost Wi-Fi."""
    import base64
    import os
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    reader, writer = await asyncio.open_connection(parts.hostname, parts.port)
    key = base64.b64encode(os.urandom(16)).decode()
    writer.write(
        (
            f"GET {parts.path} HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\nAuthorization: Bearer {TOKEN}\r\n\r\n"
        ).encode()
    )
    await writer.drain()
    await reader.readuntil(b"\r\n\r\n")
    payload = json.dumps(hello).encode()
    mask = os.urandom(4)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    assert len(payload) < 65536
    length = bytes([0x80 | len(payload)]) if len(payload) < 126 else bytes([0x80 | 126]) + len(payload).to_bytes(2, "big")
    writer.write(bytes([0x81]) + length + mask + masked)
    await writer.drain()
    return reader, writer


@run_async
async def test_replacing_a_half_open_old_connection_does_not_stall_the_new_one():
    """Design §3: a phone that reconnects after losing Wi-Fi must win at once.
    The old socket never answers the close handshake; the new connection must
    still get its config promptly, not after websockets' 10 s close timeout."""
    async with _Harness() as h:
        old_reader, old_writer = await _half_open_peer(h.url, _hello())
        await _wait_for(lambda: "overhead-1" in h.server.source_names())
        new = await h.connect()
        started = time.monotonic()
        await new.send(json.dumps(_hello()))
        config = json.loads(await asyncio.wait_for(new.recv(), timeout=5))
        assert config["type"] == "config"
        assert time.monotonic() - started < 1.0
        # The old socket never answers the close frame, so the server must
        # abort it rather than hold it open; the new one keeps the slot.
        while await asyncio.wait_for(old_reader.read(65536), timeout=5):
            pass
        assert h.server.source_names() == ["overhead-1"]
        assert new.state.name == "OPEN"
        await new.close()
        old_writer.close()


@run_async
async def test_a_peer_that_never_sends_hello_is_closed_4400(monkeypatch):
    monkeypatch.setattr("overhead.ingest.HELLO_TIMEOUT_S", 0.2)
    async with _Harness() as h:
        ws = await h.connect()
        with pytest.raises(ConnectionClosed) as exc:
            await asyncio.wait_for(ws.recv(), timeout=2)
        assert exc.value.rcvd.code == protocol.CLOSE_BAD_PROTO


@run_async
async def test_frames_near_max_bytes_are_accepted_not_closed_1009():
    """max_bytes above websockets' default 1 MiB max_size must still drop and
    count oversize frames rather than closing the connection."""
    config = {**protocol.DEFAULT_CONFIG, "max_bytes": 1_200_000}
    async with _Harness(config=config) as h:
        ws = await h.connect()
        await ws.send(json.dumps(_hello()))
        await ws.recv()
        await ws.send(_frame(0, 5, jpeg=b"\xff" * 1_150_000))
        await _wait_for(lambda: (h.server.stats("overhead-1") or {}).get("frames") == 1)
        await ws.send(_frame(1, 5, jpeg=b"\xff" * 1_250_000))
        await _wait_for(lambda: (h.server.stats("overhead-1") or {}).get("oversize") == 1)
        await ws.close()


@run_async
async def test_receive_queue_is_bounded_small(monkeypatch):
    """D-136 6항: the receiver must not buffer a backlog of frames inside
    websockets while a handler is busy — the bound must reach serve()."""
    import overhead.ingest as ingest

    seen = {}
    real_serve = ingest.serve

    async def spy(*args, **kwargs):
        seen.update(kwargs)
        return await real_serve(*args, **kwargs)

    monkeypatch.setattr(ingest, "serve", spy)
    async with _Harness():
        pass
    assert seen["max_queue"] == ingest.RECEIVE_QUEUE_FRAMES
    assert ingest.RECEIVE_QUEUE_FRAMES <= 2
