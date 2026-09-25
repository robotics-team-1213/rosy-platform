"""CORE FleetAgent connects to the same ASGI app that serves Fleet console."""

from __future__ import annotations

import asyncio
import socket
import time

import httpx
import uvicorn
from argparse import Namespace
from fastapi.testclient import TestClient

from core_common.protocol.schemas import EventMessage, StateSnapshot
from core_features.fleet_agent.agent import FleetAgent
from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.swarm.robots import RobotEndpoint, write_robots
import fleet.cli as cli


class _Identity:
    robot_id = "rosy_01"
    device_uid = "uid-01"
    device_name = "pinky-01"
    model = "pinky_pro"
    hardware_serial = "serial-01"


class _State:
    def snapshot(self):
        return StateSnapshot(robot_id="rosy_01", seq=4).model_dump(mode="json")


class _EventBus:
    def __init__(self):
        self.subscribers = set()

    def subscribe(self, callback):
        self.subscribers.add(callback)

    def unsubscribe(self, callback):
        self.subscribers.discard(callback)

    def publish(self, event):
        for callback in tuple(self.subscribers):
            callback(event)


async def _until(predicate, *, timeout_s=4.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition did not become true before timeout")


def test_core_agent_hello_heartbeat_and_event_reach_console_app():
    async def scenario():
        endpoint = RobotEndpoint(
            "rosy_01", "https://robot.local", "rest-operator",
            fleet_pairing_token="agent-pairing",
        )
        console = FleetConsole([endpoint], [FakeRobot("rosy_01")])
        app = create_app(console, console_token="console-token", hub=console.hub)

        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.setblocking(False)
        port = listener.getsockname()[1]

        server = uvicorn.Server(uvicorn.Config(
            app, log_level="critical", access_log=False, lifespan="off"))
        server_task = asyncio.create_task(server.serve(sockets=[listener]))
        events = _EventBus()
        agent = FleetAgent(
            _State(), events,
            {"fleet": {"hub_url": f"http://127.0.0.1:{port}",
                       "pairing_token": "agent-pairing"}},
            _Identity(),
        )
        try:
            await _until(lambda: server.started)
            agent.start()
            await _until(lambda: (
                agent.connected
                and console.hub.registry.record("rosy_01").snapshot is not None
            ))
            events.publish(EventMessage(
                seq=1, robot_id="rosy_01", type="nav.completed", source="navigation"))
            await _until(lambda: len(console.hub.registry.record("rosy_01").events) == 1)

            old_socket = agent._ws
            await old_socket.close()
            await _until(lambda: not console.hub.registry.record("rosy_01").online)
            await _until(lambda: (
                agent.connected and console.hub.registry.record("rosy_01").online
            ), timeout_s=6.0)

            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
                unauthorized = await client.get("/registry")
                registry = await client.get(
                    "/registry", headers={"Authorization": "Bearer console-token"})

            assert unauthorized.status_code == 401
            assert registry.status_code == 200
            row = registry.json()["rosy_01"]
            assert row["online"] is True
            assert row["snapshot"]["seq"] == 4
            assert row["events"][0]["type"] == "nav.completed"
        finally:
            agent.stop()
            if agent._task is not None:
                await asyncio.wait_for(agent._task, timeout=2.0)
            server.should_exit = True
            await asyncio.wait_for(server_task, timeout=3.0)

    asyncio.run(scenario())


def test_console_cli_mounts_agent_routes_only_when_pairing_is_configured(tmp_path, monkeypatch):
    captured = {}

    def run_app(app, **kwargs):
        captured["app"] = app

    monkeypatch.setattr(uvicorn, "run", run_app)
    robots_path = tmp_path / "robots.yaml"
    write_robots(robots_path, [RobotEndpoint(
        "rosy_01", "https://robot.local", "rest-operator",
        fleet_pairing_token="agent-pairing",
    )])

    cli.run_console(Namespace(
        host="127.0.0.1", port=8090, robots=robots_path,
        signals=None, token="console-token", web_common=None,
    ))

    assert TestClient(captured["app"]).get("/registry").status_code == 401


def test_console_cli_keeps_agent_routes_disabled_without_pairing_config(tmp_path, monkeypatch):
    captured = {}

    def run_app(app, **kwargs):
        captured["app"] = app

    monkeypatch.setattr(uvicorn, "run", run_app)
    robots_path = tmp_path / "robots.yaml"
    write_robots(robots_path, [RobotEndpoint(
        "rosy_01", "https://robot.local", "rest-operator",
    )])

    cli.run_console(Namespace(
        host="127.0.0.1", port=8090, robots=robots_path,
        signals=None, token=None, web_common=None,
    ))

    assert TestClient(captured["app"]).get("/registry").status_code == 404
