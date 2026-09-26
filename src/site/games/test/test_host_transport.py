"""HttpPlayerClient talks to CORE with mode, teleop, and stop only."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from games.host.robots import RobotEndpoint
from games.host.transport import HttpPlayerClient, PlayerClient

EP = RobotEndpoint(
    id="rosy_01",
    url="http://robot:8080",
    token="op-token",
    aruco_id=1,
    attacks="positive_x",
)
HOST = Path(__file__).resolve().parents[1] / "games" / "host"


def _client(handler) -> HttpPlayerClient:
    http = httpx.Client(transport=httpx.MockTransport(handler), base_url=EP.url)
    return HttpPlayerClient(EP, http=http)


def test_http_player_client_exposes_player_client_surface():
    client = _client(lambda _request: httpx.Response(200, json={}))
    assert client.robot_id == "rosy_01"
    assert callable(client.set_manual)
    assert callable(client.teleop)
    assert callable(client.estop)
    assert callable(client.set_limits)
    assert PlayerClient is not None


def test_set_manual_posts_mode_manual_with_bearer():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"mode": "MANUAL"})

    _client(handler).set_manual()
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/v1/mode"
    assert seen["body"] == {"mode": "MANUAL"}
    assert seen["auth"] == "Bearer op-token"


def test_teleop_posts_linear_and_angular():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"accepted": True})

    _client(handler).teleop(0.08, -0.2)
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/v1/teleop"
    assert seen["body"] == {"linear": 0.08, "angular": -0.2}


def test_set_limits_puts_manual_linear_and_angular():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    _client(handler).set_limits(0.08, 0.40)
    assert seen["method"] == "PUT"
    assert seen["path"] == "/api/v1/safety/limits"
    assert seen["body"] == {"manual_linear": 0.08, "manual_angular": 0.40}


def test_estop_posts_safety_stop():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"estop": True})

    _client(handler).estop()
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/v1/safety/stop"
    assert seen["auth"] == "Bearer op-token"


def test_empty_token_omits_authorization():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"accepted": True})

    empty = RobotEndpoint(id="rosy_01", url="http://robot:8080", token="", aruco_id=1, attacks="positive_x")
    http = httpx.Client(transport=httpx.MockTransport(handler), base_url=empty.url)
    HttpPlayerClient(empty, http=http).teleop(0.0, 0.0)
    assert seen["auth"] is None


@pytest.mark.parametrize("status", [409, 500])
def test_http_error_raises_so_the_loop_can_estop_both(status):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"code": "HTTP"}})

    with pytest.raises(Exception):
        _client(handler).teleop(0.1, 0.0)


def test_transport_source_has_only_mode_teleop_stop_and_limits():
    src = (HOST / "transport.py").read_text(encoding="utf-8").lower()
    for banned in ("follow", "navigation", "swarm"):
        assert banned not in src
    assert "/api/v1/mode" in src
    assert "/api/v1/teleop" in src
    assert "/api/v1/safety/stop" in src
    assert "/api/v1/safety/limits" in src
