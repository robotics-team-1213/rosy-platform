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

    def __init__(self, config: dict | None = None):
        self.server = IngestServer(TOKEN, config=config)
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
