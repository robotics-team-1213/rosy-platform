"""Real localhost phone WebSocket -> vision worker -> Fleet HTTP contract."""

from __future__ import annotations

import asyncio
import json
import socket

import cv2
import httpx
import numpy as np
import uvicorn
import websockets
import yaml

from overhead import protocol
from overhead.ingest import IngestServer
from overhead.publish import SightingPublisher
from overhead.vision_config import load_vision_sources
from overhead.worker import VisionWorker
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.sightings import SightingService
from fleet.server.sightings_config import load_sighting_sources
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import HttpRobotClient

PHONE_TOKEN = "phone-ingress-secret"
VISION_TOKEN = "vision-fleet-secret"
OPERATOR_TOKEN = "operator-console-secret"
SOURCE_ID = "ceiling_north"


def _jpeg(*, missing_corner=None):
    canvas = np.full((400, 600), 255, dtype=np.uint8)
    positions = {30: (100, 100), 31: (500, 100), 32: (500, 300),
                 33: (100, 300), 7: (300, 200)}
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    for marker_id, (cx, cy) in positions.items():
        if marker_id == missing_corner:
            continue
        marker = cv2.aruco.generateImageMarker(dictionary, marker_id, 72)
        canvas[cy - 36:cy + 36, cx - 36:cx + 36] = marker
    ok, encoded = cv2.imencode(".jpg", canvas, [cv2.IMWRITE_JPEG_QUALITY, 100])
    assert ok
    return encoded.tobytes()


def _frame(seq, age_ms, jpeg):
    header = protocol.FrameHeader(seq, age_ms, 600, 400, 0)
    return protocol.pack_header(header) + jpeg


async def _wait_for(predicate, timeout_s=2.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        value = predicate()
        if value:
            return value
        await asyncio.sleep(0.01)
    raise AssertionError("localhost integration condition was not reached")


async def _run_pipeline(config_path):
    endpoint = RobotEndpoint("rosy_01", "http://127.0.0.1:9", "robot-rest")
    console = FleetConsole([endpoint], [HttpRobotClient(endpoint)])
    http_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    http_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    http_socket.bind(("127.0.0.1", 0))
    http_socket.listen(128)
    http_socket.setblocking(False)
    http_port = http_socket.getsockname()[1]
    config_path.write_text(yaml.safe_dump({"sources": [{
        "source_id": SOURCE_ID,
        "phone_token_env": "ROSY_TEST_PHONE_TOKEN",
        "token_env": "ROSY_TEST_FLEET_SIGHTING_TOKEN",
        "fleet_base_url": f"http://127.0.0.1:{http_port}",
        "robot_ids": ["rosy_01"],
        "map_id": "site-v1",
        "calibration_revision": "cal-v3",
        "processor_revision": "aruco-v1",
        "corner_marker_ids": [30, 31, 32, 33],
        "corner_world_m": [[0, 0], [4, 0], [4, 2], [0, 2]],
        "robot_markers": {"rosy_01": 7},
        "heading_edge": [1, 2],
    }]}), encoding="utf-8")
    fleet_sources = load_sighting_sources(config_path)
    vision_config = load_vision_sources(config_path)[0]
    sightings = SightingService(fleet_sources, known_robot_ids=console.robot_ids)
    app = create_app(console, console_token=OPERATOR_TOKEN, sightings=sightings)
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", lifespan="off"))
    http_task = asyncio.create_task(server.serve(sockets=[http_socket]))

    ingest = IngestServer({SOURCE_ID: vision_config.phone_token})
    ws_server = await ingest.start("127.0.0.1", 0)
    ws_port = ws_server.sockets[0].getsockname()[1]
    ws_url = f"ws://127.0.0.1:{ws_port}{protocol.WS_PATH}"

    try:
        await _wait_for(lambda: server.started)
        async with websockets.connect(
            ws_url, additional_headers={"Authorization": f"Bearer {vision_config.phone_token}"}
        ) as phone, SightingPublisher(
            vision_config.fleet_base_url, vision_config.sighting_token
        ) as publisher:
            await phone.send(json.dumps({
                "type": "hello", "proto": protocol.PROTO, "source": SOURCE_ID,
                "app_version": "test", "device": "synthetic-camera",
                "sensor": {"width": 600, "height": 400, "rotation_deg": 0},
            }))
            assert json.loads(await phone.recv()) == protocol.make_config()
            worker = VisionWorker(source_id=SOURCE_ID, ingest=ingest,
                                  camera=vision_config.camera,
                                  publisher=publisher)

            await phone.send(_frame(1, 0, _jpeg(missing_corner=32)))
            await _wait_for(lambda: ingest.latest_frame(SOURCE_ID)
                            and ingest.latest_frame(SOURCE_ID).header.seq == 1)
            assert await worker.process_latest() == ()

            await phone.send(_frame(2, 0, _jpeg()))
            await _wait_for(lambda: ingest.latest_frame(SOURCE_ID)
                            and ingest.latest_frame(SOURCE_ID).header.seq == 2)
            projected = await worker.process_latest()
            assert len(projected) == 1
            assert projected[0].seq == 2

            await phone.send(_frame(3, 1600, _jpeg()))
            await _wait_for(lambda: ingest.latest_frame(SOURCE_ID)
                            and ingest.latest_frame(SOURCE_ID).header.seq == 3)
            assert await worker.process_latest() == ()

            async with httpx.AsyncClient() as operator:
                response = await operator.get(
                    f"http://127.0.0.1:{http_port}/api/fleet/sightings",
                    headers={"Authorization": f"Bearer {OPERATOR_TOKEN}"},
                )
            assert response.status_code == 200, response.text
            rows = response.json()["sightings"]
            assert len(rows) == 1
            row = rows[0]
            assert (row["source_id"], row["robot_id"], row["seq"]) == (
                SOURCE_ID, "rosy_01", 2)
            assert (row["map_id"], row["calibration_revision"], row["processor_revision"]) == (
                "site-v1", "cal-v3", "aruco-v1")
            assert abs(row["x"] - 2.0) < 0.03
            assert abs(row["y"] - 1.0) < 0.03
            assert row["quality"] is None
            assert "jpeg" not in row and "image_url" not in row
    finally:
        ws_server.close()
        await ws_server.wait_closed()
        server.should_exit = True
        await asyncio.wait_for(http_task, timeout=3.0)


def test_real_localhost_phone_to_fleet_sighting_path(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSY_TEST_PHONE_TOKEN", PHONE_TOKEN)
    monkeypatch.setenv("ROSY_TEST_FLEET_SIGHTING_TOKEN", VISION_TOKEN)
    asyncio.run(_run_pipeline(tmp_path / "site-cameras.yaml"))
