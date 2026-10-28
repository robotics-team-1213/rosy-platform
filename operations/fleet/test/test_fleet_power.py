"""Fleet sleep / wake per robot (D-440 6).

Fleet only forwards to CORE's own power API: STANDBY via /api/v1/power/mode and
wake via /api/v1/power/wake. CORE keeps the interlock (a robot that is not IDLE
stays ACTIVE), so Fleet adds no rule of its own.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fakes import FakeRobot
from fleet.server.console_routes import install_console_routes
from fleet.swarm.transport import HttpRobotClient

ROSTER = Path(__file__).resolve().parents[3] / "applications/fleet/web" / "shared" / "power-action.js"


class Console:
    def __init__(self, robot):
        self._clients = {robot.robot_id: robot}
        self._clock = time.monotonic

    def clients(self):
        return dict(self._clients)


def _client(robot) -> TestClient:
    app = FastAPI()
    nobody = lambda: None
    install_console_routes(app, console=Console(robot), sightings=None, require_viewer=nobody,
                           read_guard=[], operator_guard=[], require_operator=nobody,
                           require_named_operator=nobody)
    return TestClient(app)


def test_sleep_and_wake_are_forwarded_to_core_power_api():
    robot = FakeRobot("rosy_01")
    client = _client(robot)

    slept = client.post("/api/fleet/robots/rosy_01/power", json={"action": "sleep"})
    woke = client.post("/api/fleet/robots/rosy_01/power", json={"action": "wake"})

    assert slept.status_code == 200 and woke.status_code == 200
    assert [call for call in robot.calls if call[0] == "power"] == [("power", "sleep"), ("power", "wake")]
    assert slept.json()["result"]["mode"] == "STANDBY" and woke.json()["result"]["mode"] == "ACTIVE"


def test_unknown_action_and_robot_are_refused_without_a_call():
    robot = FakeRobot("rosy_01")
    client = _client(robot)

    assert client.post("/api/fleet/robots/rosy_01/power", json={"action": "off"}).status_code == 422
    assert client.post("/api/fleet/robots/rosy_01/power", json={"mode": "STANDBY"}).status_code == 422
    assert client.post("/api/fleet/robots/rosy_01/power",
                       json={"action": "wake", "mode": "ACTIVE"}).status_code == 422
    assert client.post("/api/fleet/robots/nobody/power", json={"action": "wake"}).status_code == 404
    assert not [call for call in robot.calls if call[0] == "power"]


def test_power_route_needs_a_named_operator():
    from fastapi import HTTPException

    def refuse():
        raise HTTPException(status_code=403, detail={"code": "NAMED_OPERATOR_REQUIRED"})

    robot = FakeRobot("rosy_01")
    app = FastAPI()
    nobody = lambda: None
    install_console_routes(app, console=Console(robot), sightings=None, require_viewer=nobody,
                           read_guard=[], operator_guard=[], require_operator=nobody,
                           require_named_operator=refuse)
    assert TestClient(app).post("/api/fleet/robots/rosy_01/power", json={"action": "sleep"}).status_code == 403
    assert not [call for call in robot.calls if call[0] == "power"]


def test_http_client_asks_core_only_for_standby_or_wake():
    posts = []

    async def post(path, body=None):
        posts.append((path, body))
        return {}

    client = HttpRobotClient.__new__(HttpRobotClient)
    client._post = post
    asyncio.run(client.power("sleep"))
    asyncio.run(client.power("wake"))
    assert posts == [("/api/v1/power/mode", {"mode": "STANDBY"}), ("/api/v1/power/wake", None)]
    with pytest.raises(KeyError):
        asyncio.run(client.power("ACTIVE"))
    assert len(posts) == 2


def test_roster_offers_sleep_or_wake_without_inline_handlers():
    source = ROSTER.read_text(encoding="utf-8")
    assert "/power`" in source and "action: power.dataset.powerAction" in source
    assert "일하는 로봇은 절전할 수 없습니다" in source
    assert "onclick" not in source.lower()          # CSP: no inline handlers
