"""D-341 11-12: the ingest server admits paired phones by synced digest, real localhost WS."""

from __future__ import annotations

import asyncio
import json
import time
from hashlib import sha256

import pytest
import websockets
from rosy_vision import protocol
from rosy_vision.ingest import IngestServer
from rosy_vision.pairing_sync import PairedCredentials, PairingSync
from test_ingest import _frame, _hello, _wait_for, run_async
from websockets.exceptions import ConnectionClosed, InvalidStatus

STATIC_TOKEN = "static-" + "phone-token"
PAIRED_A = "paired-" + "phone-north"
PAIRED_B = "paired-" + "phone-south"


def _row(token: str, source: str, credential_id: str) -> dict:
    return {"credential_id": credential_id, "source_id": source,
            "token_sha256": sha256(token.encode()).hexdigest(), "expires_at": "2099-01-01T00:00:00Z"}


ROWS = [_row(PAIRED_A, "ceiling_north", "cred-a"), _row(PAIRED_B, "ceiling_south", "cred-b")]


class Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


class _Paired:
    def __init__(self, *, clock=None, static=True):
        self.credentials = PairedCredentials(["ceiling_north", "ceiling_south"],
                                             clock=clock or time.monotonic)
        tokens = {"bench_static": STATIC_TOKEN} if static else {}
        self.server = IngestServer(tokens, paired=self.credentials)

    async def __aenter__(self):
        self.ws_server = await self.server.start("127.0.0.1", 0)
        port = self.ws_server.sockets[0].getsockname()[1]
        self.url = f"ws://127.0.0.1:{port}{protocol.WS_PATH}"
        return self

    async def __aexit__(self, *exc):
        self.ws_server.close()
        await self.ws_server.wait_closed()

    async def connect(self, token: str):
        return await websockets.connect(self.url, additional_headers={"Authorization": f"Bearer {token}"})

    async def stream(self, token: str, source: str):
        ws = await self.connect(token)
        await ws.send(json.dumps(_hello(source)))
        assert json.loads(await ws.recv())["type"] == "config"
        return ws


def test_paired_only_receiver_starts_without_static_tokens():
    IngestServer({}, paired=PairedCredentials(["ceiling_north"]))
    with pytest.raises(ValueError):
        IngestServer({})
    with pytest.raises(ValueError, match="both"):
        IngestServer({"ceiling_north": STATIC_TOKEN}, paired=PairedCredentials(["ceiling_north"]))


@run_async
async def test_unknown_state_is_503_retry_after_at_upgrade():
    async with _Paired() as harness:
        with pytest.raises(InvalidStatus) as caught:
            await harness.connect(PAIRED_A)
        assert caught.value.response.status_code == 503
        assert caught.value.response.headers["Retry-After"] == "2"
        # Static sources are not affected by the pairing state.
        ws = await harness.stream(STATIC_TOKEN, "bench_static")
        await ws.close()


@run_async
async def test_synced_digest_streams_and_unknown_bearer_is_401():
    async with _Paired() as harness:
        harness.credentials.replace(ROWS)
        ws = await harness.stream(PAIRED_A, "ceiling_north")
        await ws.send(_frame(1, 0))
        await _wait_for(lambda: harness.server.latest_frame("ceiling_north") is not None)
        await ws.close()
        with pytest.raises(InvalidStatus) as caught:
            await harness.connect("not-" + "issued")
        assert caught.value.response.status_code == 401


@run_async
async def test_a_paired_token_only_opens_its_own_source():
    async with _Paired() as harness:
        harness.credentials.replace(ROWS)
        for token, source in ((PAIRED_A, "ceiling_south"), (PAIRED_A, "bench_static"),
                              (STATIC_TOKEN, "ceiling_north")):
            ws = await harness.connect(token)
            await ws.send(json.dumps(_hello(source)))
            with pytest.raises(ConnectionClosed):
                await ws.recv()
            assert ws.close_code == protocol.CLOSE_UNAUTHORIZED


@run_async
async def test_state_lost_between_upgrade_and_hello_closes_4503():
    clock = Clock()
    async with _Paired(clock=clock) as harness:
        harness.credentials.replace(ROWS)
        ws = await harness.connect(PAIRED_A)
        clock.now += 601
        await ws.send(json.dumps(_hello("ceiling_north")))
        with pytest.raises(ConnectionClosed):
            await ws.recv()
        assert ws.close_code == protocol.CLOSE_CREDENTIAL_UNKNOWN


@run_async
async def test_revoked_credential_closes_4401_and_its_frames_are_dropped():
    async with _Paired() as harness:
        harness.credentials.replace(ROWS)
        north = await harness.stream(PAIRED_A, "ceiling_north")
        south = await harness.stream(PAIRED_B, "ceiling_south")
        harness.credentials.replace(ROWS[1:])  # cred-a revoked at Fleet
        await north.send(_frame(7, 0))
        await asyncio.sleep(0.1)
        assert harness.server.latest_frame("ceiling_north") is None
        harness.server.enforce_paired_credentials()
        with pytest.raises(ConnectionClosed):
            while True:
                await asyncio.wait_for(north.recv(), 2.0)
        assert north.close_code == protocol.CLOSE_UNAUTHORIZED
        await south.send(_frame(1, 0))
        await _wait_for(lambda: harness.server.latest_frame("ceiling_south") is not None)
        await south.close()


@run_async
async def test_stale_list_closes_live_paired_connections_4503():
    clock = Clock()
    async with _Paired(clock=clock) as harness:
        harness.credentials.replace(ROWS)
        north = await harness.stream(PAIRED_A, "ceiling_north")
        static = await harness.stream(STATIC_TOKEN, "bench_static")
        clock.now += 601
        harness.server.enforce_paired_credentials()
        with pytest.raises(ConnectionClosed):
            while True:
                await asyncio.wait_for(north.recv(), 2.0)
        assert north.close_code == protocol.CLOSE_CREDENTIAL_UNKNOWN
        await static.send(_frame(1, 0))
        await _wait_for(lambda: harness.server.latest_frame("bench_static") is not None)
        await static.close()


@run_async
async def test_revocation_reaches_a_live_socket_within_5_s_through_the_sync_thread():
    """Acceptance: revoke at Fleet -> close 4401 in under 5 s with the real 2 s sync thread."""
    listing = {"rows": list(ROWS)}
    async with _Paired() as harness:
        loop = asyncio.get_running_loop()
        sync = PairingSync(
            harness.credentials,
            fetch=lambda: {"role": "overhead-camera", "credentials": list(listing["rows"])},
            on_cycle=lambda: loop.call_soon_threadsafe(harness.server.enforce_paired_credentials))
        sync.start()
        try:
            await _wait_for(harness.credentials.available, timeout=3.0)
            north = await harness.stream(PAIRED_A, "ceiling_north")
            revoked_at = time.monotonic()
            listing["rows"] = ROWS[1:]
            with pytest.raises(ConnectionClosed):
                while True:
                    await asyncio.wait_for(north.recv(), 6.0)
            elapsed = time.monotonic() - revoked_at
        finally:
            sync.stop()
        assert north.close_code == protocol.CLOSE_UNAUTHORIZED
        assert elapsed < 5.0


@run_async
async def test_logs_hold_no_bearer(caplog):
    import logging

    async with _Paired() as harness:
        harness.credentials.replace(ROWS)
        with caplog.at_level(logging.DEBUG):
            ws = await harness.stream(PAIRED_A, "ceiling_north")
            harness.credentials.replace([])
            harness.server.enforce_paired_credentials()
            with pytest.raises(ConnectionClosed):
                while True:
                    await asyncio.wait_for(ws.recv(), 2.0)
    # The test's own websockets client logs its request headers; the receiver must not.
    server_text = " | ".join(record.getMessage() for record in caplog.records
                             if not record.name.startswith("websockets.client"))
    assert PAIRED_A not in server_text
    assert "cred-a" in server_text
