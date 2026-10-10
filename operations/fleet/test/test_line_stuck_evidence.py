"""D-577 8: a stuck's evidence picture — one front-camera frame per open stuck, held in Fleet memory only."""

from __future__ import annotations

import base64
import asyncio
import httpx
import pytest
from hashlib import sha256

from fastapi.testclient import TestClient

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
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

    async def front_frame(self, *, overlay=True):
        self._record("front_frame")
        if self.frame_error is not None:
            raise self.frame_error
        return JPEG, {"sequence": 812, "age_ms": 400, "source": "front"}


def test_live_reads_new_raw_frames_without_replacing_incident_snapshot(tmp_path):
    robot = FramedRobot("rosy_01", state=_state())
    client = _client(robot, tmp_path)
    _gather(client)
    historical = _preview(client).json()
    for _ in range(2):
        result = _preview(client, "stuck-abc&live=true")
        assert result.status_code == 200, result.text
        assert result.json()["live"] is True
        assert 0.4 <= result.json()["age_s"] <= 3
    assert robot.calls.count(("front_frame",)) == 3
    assert _preview(client).json()["jpeg_base64"] == historical["jpeg_base64"]


@pytest.mark.parametrize("age", [None, -1, 3001, float("nan")])
def test_live_does_not_show_unknown_or_stale_image_age(tmp_path, age):
    robot = FramedRobot("rosy_01", state=_state())

    async def front_frame(*, overlay):
        assert overlay is False
        return JPEG, {"sequence": 813, "age_ms": age, "source": "front"}

    robot.front_frame = front_frame
    client = _client(robot, tmp_path)
    _gather(client)
    assert _preview(client, "stuck-abc&live=true").status_code == 404


def test_live_drops_frame_if_stuck_closed_while_fetching(tmp_path):
    robot = FramedRobot("rosy_01", state=_state())
    client = _client(robot, tmp_path)
    _gather(client)

    async def front_frame(*, overlay):
        client.app.state.line_stuck.observe([{"robot_id": "rosy_01", "online": True, "state": _state(None)}])
        return JPEG, {"sequence": 813, "age_ms": 100, "source": "front"}

    robot.front_frame = front_frame
    assert _preview(client, "stuck-abc&live=true").json()["detail"]["code"] == "STUCK_NOT_OPEN"


def _state(stuck=STUCK) -> dict:
    return {"robot_id": "rosy_01", "mode": "NAVIGATION", "safety": {"estop": False},
            "line_follow": {"mode": "CAMERA_LINE", "state": "HOLD", "stuck": stuck}}


def _client(robot, tmp_path):
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "rest-token")], [robot])
    store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    app = create_app(console, task_service=FleetTaskService(store, robot_ids={"rosy_01"}),
                     start_task_dispatcher=False, site_users={
                         sha256(VIEWER.encode()).hexdigest(): {"principal_id": "watcher", "role": "viewer"}})
    client = TestClient(app)
    client.app.state.fleet_gather.max_age_s = 0.0
    return client


def _gather(client):
    assert client.get("/api/fleet/state", headers={"Authorization": f"Bearer {VIEWER}"}).status_code == 200


def _preview(client, stuck_id="stuck-abc"):
    return client.get(f"/api/fleet/robots/rosy_01/line-stuck/evidence?stuck_id={stuck_id}",
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
    on_disk = [p for p in tmp_path.rglob("*") if p.is_file() and b"fake-jpeg" in p.read_bytes()]
    assert on_disk == []                                     # D-577 8: memory only, never disk


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
    assert client.get("/api/fleet/robots/rosy_01/line-stuck/evidence?stuck_id=stuck-abc").status_code == 401


@pytest.mark.parametrize("overlay", [True, False])
def test_the_robot_client_reads_status_then_the_frame_of_that_sequence(overlay):
    import asyncio

    import httpx

    from fleet.swarm.transport import HttpRobotClient

    seen = []

    def handler(request):
        seen.append((request.url.path, dict(request.url.params), request.headers.get("authorization")))
        if request.url.path == "/api/v1/vision/front/status":
            return httpx.Response(200, json={"available": True, "sequence": 812, "age_ms": 400, "source": "front",
                                            "raw_available": True, "raw_sequence": 811})
        return httpx.Response(200, content=JPEG, headers={"Content-Type": "image/jpeg"})

    endpoint = RobotEndpoint("rosy_01", "http://robot:8080", "op-token")
    client = HttpRobotClient(endpoint, http=httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                                             base_url=endpoint.base_url))
    data, status = asyncio.run(client.front_frame(overlay=overlay))

    assert data == JPEG and status["sequence"] == (812 if overlay else 811)
    params = {"sequence": "812"} if overlay else {"sequence": "811", "overlay": "false"}
    assert seen == [("/api/v1/vision/front/status", {}, "Bearer op-token"),
                    ("/api/v1/vision/front/frame", params, "Bearer op-token")]

    stale = HttpRobotClient(endpoint, http=httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"available": False, "sequence": 0})),
        base_url=endpoint.base_url))
    try:
        asyncio.run(stale.front_frame())
    except RobotApiError as exc:
        assert exc.code == "CAMERA_FRAME_UNAVAILABLE"
    else:
        raise AssertionError("a stale camera must not yield a frame")


def test_raw_frame_request_does_not_substitute_an_annotated_image():
    from fleet.swarm.transport import HttpRobotClient
    endpoint = RobotEndpoint("rosy_01", "http://robot:8080", "op-token")
    client = HttpRobotClient(endpoint, http=httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"available": True, "sequence": 1, "raw_available": False})),
        base_url=endpoint.base_url))
    with pytest.raises(RobotApiError, match="raw front frame unavailable"):
        asyncio.run(client.front_frame(overlay=False))
