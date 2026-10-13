"""D-691: a Rosy preview read wakes the phone, then the hold lets it sleep."""

from __future__ import annotations

import asyncio
import json

import pytest
import websockets

from core_common.protocol.vision_preview import VisionLeaseSigner
from rosy_vision import protocol
from rosy_vision.ingest import IngestServer
from rosy_vision.stream_demand import STREAM_HOLD_S, StreamDemand

SOURCE = "ceiling-north"
TOKEN = "phone-token"
HELLO = {
    "type": "hello", "proto": protocol.PROTO, "source": SOURCE,
    "app_version": "test", "device": "synthetic",
    "sensor": {"width": 1280, "height": 720, "rotation_deg": 0},
}


def test_hold_matches_the_shared_vector_and_ends_on_time():
    from pathlib import Path
    vectors = json.loads((Path(__file__).resolve().parents[3] / "test" / "fixtures"
                          / "protocol" / "overhead-ingest.v1.json").read_text(encoding="utf-8"))
    assert vectors["stream_hold_s"] == STREAM_HOLD_S
    clock = [0.0]
    demand = StreamDemand(clock=lambda: clock[0])
    assert demand.wanted(SOURCE) is False
    assert demand.note(SOURCE) is True
    assert demand.note(SOURCE) is False
    clock[0] = STREAM_HOLD_S - 0.001
    assert demand.wanted(SOURCE) is True
    clock[0] = STREAM_HOLD_S
    assert demand.wanted(SOURCE) is False


def test_a_later_read_restarts_the_hold_from_that_moment():
    clock = [0.0]
    demand = StreamDemand(clock=lambda: clock[0])
    demand.note("cam")
    clock[0] = 20.0
    assert demand.note("cam") is False
    clock[0] = 49.9
    assert demand.wanted("cam") is True
    clock[0] = 50.0
    assert demand.wanted("cam") is False


def test_sources_do_not_share_a_hold():
    demand = StreamDemand(clock=lambda: 0.0)
    demand.note("a", now=0.0)
    assert demand.wanted("b", now=0.0) is False
    demand.drop("a")
    assert demand.wanted("a", now=0.0) is False


def test_hold_must_be_positive():
    with pytest.raises(ValueError):
        StreamDemand(hold_s=0)


def test_an_authorized_read_wakes_the_phone_and_the_hold_lets_it_sleep():
    asyncio.run(_wake())


async def _next(phone, kind: str) -> dict:
    while True:
        message = json.loads(await asyncio.wait_for(phone.recv(), 2))
        if message["type"] == kind:
            return message


async def _wake():
    clock = [0.0]
    signer = VisionLeaseSigner("p" * 32)
    server = IngestServer({SOURCE: TOKEN}, preview_signer=signer)
    server._demand = StreamDemand(clock=lambda: clock[0])
    ws = await server.start("127.0.0.1", 0)
    port = ws.sockets[0].getsockname()[1]
    try:
        async with websockets.connect(
            f"ws://127.0.0.1:{port}{protocol.WS_PATH}",
            additional_headers={"Authorization": f"Bearer {TOKEN}"},
        ) as phone:
            await phone.send(json.dumps(HELLO))
            assert json.loads(await phone.recv()) == protocol.make_config()
            assert json.loads(await phone.recv()) == protocol.make_demand(False)
            lease = signer.issue(principal_id="rosy-fleet", source_id=SOURCE)
            missing = await server._preview_response(
                f"/api/vision/sources/{SOURCE}/frame", f"Bearer {lease}")
            assert missing.status_code == 404
            assert await _next(phone, "demand") == protocol.make_demand(True)
            clock[0] = 10.0
            denied = await server._preview_response(
                f"/api/vision/sources/{SOURCE}/frame", None)
            assert denied.status_code == 401
            clock[0] = STREAM_HOLD_S
            assert await _next(phone, "demand") == protocol.make_demand(False)
    finally:
        ws.close()
        await ws.wait_closed()
