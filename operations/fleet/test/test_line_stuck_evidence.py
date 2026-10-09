"""D-577 8: a stuck's evidence picture — one front-camera frame per open stuck, held in Fleet memory only."""

from __future__ import annotations

import base64
from hashlib import sha256

from fastapi.testclient import TestClient

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import RobotApiError

STUCK = {"stuck_id": "stuck-abc", "cause": "lane_lost", "phase": "WAITING_CONSOLE", "held_s": 3.5,
         "attempts": 2, "max_attempts": 2, "local_enabled": True}
JPEG = b"\xff\xd8fake-jpeg\xff\xd9"
VIEWER = "viewer-token"


class FramedRobot(FakeRobot):
    """A robot whose front camera answers one JPEG (or raises ``frame_error``)."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.frame_error = None

    async def front_frame(self):
        self._record("front_frame")
        if self.frame_error is not None:
            raise self.frame_error
        return JPEG, {"sequence": 812, "age_ms": 400, "source": "front"}


def _state(stuck=STUCK) -> dict:
    return {"robot_id": "rosy_01", "mode": "NAVIGATION", "safety": {"estop": False},
            "line_follow": {"mode": "CAMERA_LINE", "state": "HOLD", "stuck": stuck}}


def _client(robot, tmp_path):
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "rest-token")], [robot])
    app = create_app(console, site_users={
        sha256(VIEWER.encode()).hexdigest(): {"principal_id": "watcher", "role": "viewer"}})
    client = TestClient(app)
    client.app.state.fleet_gather.max_age_s = 0.0
    return client


def _gather(client):
    assert client.get("/api/fleet/state", headers={"Authorization": f"Bearer {VIEWER}"}).status_code == 200


def _preview(client, stuck_id="stuck-abc"):
    return client.get(f"/api/fleet/robots/rosy_01/line-stuck/preview?stuck_id={stuck_id}",
                      headers={"Authorization": f"Bearer {VIEWER}"})


def test_the_open_stuck_gets_one_frame_kept_in_memory_with_its_age(tmp_path):
    robot = FramedRobot("rosy_01", state=_state())
    client = _client(robot, tmp_path)
    _gather(client)

    first = _preview(client)
    second = _preview(client)

    assert first.status_code == 200, first.text
    body = first.json()
    assert base64.b64decode(body["jpeg_base64"]) == JPEG
    assert body["stuck_id"] == "stuck-abc" and body["sequence"] == 812 and body["source"] == "front"
    assert 0.4 <= body["age_s"] < 5.0
    assert second.json()["jpeg_base64"] == body["jpeg_base64"]
    assert robot.calls.count(("front_frame",)) == 1          # one picture per stuck
    assert not any(tmp_path.rglob("*"))                      # D-577 8: nothing on disk


def test_a_closed_stuck_drops_its_picture_and_a_wrong_id_has_none(tmp_path):
    robot = FramedRobot("rosy_01", state=_state())
    client = _client(robot, tmp_path)
    _gather(client)
    assert _preview(client).status_code == 200
    assert _preview(client, "stuck-other").json()["detail"]["code"] == "STUCK_NOT_OPEN"

    robot._state = _state(stuck=None)
    _gather(client)

    assert client.app.state.line_stuck.preview("rosy_01", "stuck-abc") is None
    assert _preview(client).status_code == 404


def test_a_robot_without_a_fresh_frame_answers_unavailable_and_is_asked_again_later(tmp_path):
    robot = FramedRobot("rosy_01", state=_state())
    robot.frame_error = RobotApiError("rosy_01", 404, "CAMERA_FRAME_UNAVAILABLE", "stale")
    client = _client(robot, tmp_path)
    _gather(client)

    missing = _preview(client)
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "STUCK_PREVIEW_UNAVAILABLE"

    robot.frame_error = None
    assert _preview(client).status_code == 200


def test_the_preview_needs_a_site_credential(tmp_path):
    client = _client(FramedRobot("rosy_01", state=_state()), tmp_path)
    assert client.get("/api/fleet/robots/rosy_01/line-stuck/preview?stuck_id=stuck-abc").status_code == 401


def test_the_robot_client_reads_status_then_the_frame_of_that_sequence():
    import asyncio

    import httpx

    from fleet.swarm.transport import HttpRobotClient

    seen = []

    def handler(request):
        seen.append((request.url.path, dict(request.url.params), request.headers.get("authorization")))
        if request.url.path == "/api/v1/vision/front/status":
            return httpx.Response(200, json={"available": True, "sequence": 812, "age_ms": 400, "source": "front"})
        return httpx.Response(200, content=JPEG, headers={"Content-Type": "image/jpeg"})

    endpoint = RobotEndpoint("rosy_01", "http://robot:8080", "op-token")
    client = HttpRobotClient(endpoint, http=httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                                             base_url=endpoint.base_url))
    data, status = asyncio.run(client.front_frame())

    assert data == JPEG and status["sequence"] == 812
    assert seen == [("/api/v1/vision/front/status", {}, "Bearer op-token"),
                    ("/api/v1/vision/front/frame", {"sequence": "812"}, "Bearer op-token")]

    stale = HttpRobotClient(endpoint, http=httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"available": False, "sequence": 0})),
        base_url=endpoint.base_url))
    try:
        asyncio.run(stale.front_frame())
    except RobotApiError as exc:
        assert exc.code == "CAMERA_FRAME_UNAVAILABLE"
    else:
        raise AssertionError("a stale camera must not yield a frame")
