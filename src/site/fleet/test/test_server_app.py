"""관제 HTTP 표면 — 경로, 상태 코드, 토큰 가드, 자산 allowlist."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import RobotApiError

GRID = {"map_id": "occupancy:abc", "width": 1, "height": 1, "resolution": 0.05,
        "origin": {"x": 0.0, "y": 0.0, "yaw": 0.0}, "data": [0]}


def _client(*robots: FakeRobot, token=None, web_common=None) -> TestClient:
    endpoints = [RobotEndpoint(robot_id=r.robot_id, base_url=f"http://127.0.0.1:808{i}",
                               token="t") for i, r in enumerate(robots)]
    console = FleetConsole(endpoints, list(robots))
    return TestClient(create_app(console, console_token=token, web_common=web_common))


def test_do_translates_a_goal_and_rejects_a_ros_word():
    robot = FakeRobot("rosy_01", state={"robot_id": "rosy_01", "mode": "IDLE"})
    client = _client(robot)
    sent = client.post("/api/fleet/do", json={
        "do": "navigate", "robot": "rosy_01", "x": 1.0, "y": 2.0, "yaw": 0.0,
    })
    assert sent.status_code == 200, sent.text
    assert sent.json()["steps"][0]["path"] == "/api/v1/navigation/goal"
    refused = client.post("/api/fleet/do", json={"do": "navigate", "x": 0, "y": 0, "twist": {}})
    assert refused.status_code == 400
    assert refused.json()["detail"]["code"] == "FORBIDDEN"


def test_state_lists_the_roster():
    client = _client(FakeRobot("rosy_01", state={"robot_id": "rosy_01", "mode": "IDLE"}),
                     FakeRobot("rosy_02", state={"robot_id": "rosy_02", "mode": "NAVIGATION"}))
    body = client.get("/api/fleet/state").json()
    assert body["fleet"]["total"] == 2
    assert [r["robot_id"] for r in body["robots"]] == ["rosy_01", "rosy_02"]


def test_map_is_404_when_no_robot_serves_one():
    blind = FakeRobot("rosy_01")
    blind.map_error = ConnectionError("down")
    assert _client(blind).get("/api/fleet/map").status_code == 404


def test_map_is_served_when_a_robot_has_one():
    assert _client(FakeRobot("rosy_01", map=GRID)).get("/api/fleet/map").json()["map_id"] \
        == "occupancy:abc"


def test_goal_to_an_unknown_robot_is_404_not_502():
    """오타는 사이트 쪽 잘못이다. 502 로 내면 로봇이 거절한 것처럼 읽힌다."""
    resp = _client(FakeRobot("rosy_01")).post("/api/fleet/robots/rosy_99/goal",
                                              json={"x": 0.0, "y": 0.0})
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "UNKNOWN_ROBOT"


def test_a_goal_the_robot_refuses_comes_back_as_502_with_the_robot_code():
    robot = FakeRobot("rosy_01")

    async def refuse(x, y, yaw):
        raise RobotApiError("rosy_01", 409, "MODE_CONFLICT", "not in NAVIGATION")

    robot.navigation_goal = refuse
    resp = _client(robot).post("/api/fleet/robots/rosy_01/goal", json={"x": 1.0, "y": 0.0})
    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "MODE_CONFLICT"
    assert resp.json()["detail"]["robot_id"] == "rosy_01"


def test_estop_is_200_even_when_one_robot_refuses():
    """부분 실패를 5xx 로 접으면 어느 대가 섰는지 화면이 알 수 없다."""
    good = FakeRobot("rosy_01")
    bad = FakeRobot("rosy_02")

    async def blow_up():
        raise ConnectionError("gone")

    bad.estop = blow_up
    resp = _client(good, bad).post("/api/fleet/estop")
    assert resp.status_code == 200
    assert resp.json()["stopped"] == 1


@pytest.mark.parametrize("path", ["/api/fleet/state", "/api/fleet/estop"])
def test_console_token_guards_the_site_api(path):
    """이 포트는 현장의 모든 로봇을 움직인다 — 토큰을 켜면 전부 막힌다."""
    client = _client(FakeRobot("rosy_01"), token="secret")
    method = client.get if path.endswith("state") else client.post
    assert method(path).status_code == 401
    assert method(path, headers={"Authorization": "Bearer secret"}).status_code == 200


def test_console_page_and_its_assets_are_served():
    client = _client(FakeRobot("rosy_01"))
    page = client.get("/console")
    assert page.status_code == 200 and "ROSY FLEET" in page.text
    assert client.get("/console/assets/console.js").status_code == 200
    assert client.get("/console/assets/styles.css").status_code == 200
    assert 'href="/common/tokens.css"' in page.text


def test_the_tokens_copy_is_gone_from_the_allowlist():
    """D-129 — 사본이 없으니 allowlist 도 이름을 잃는다. 부활은 위반이다."""
    client = _client(FakeRobot("rosy_01"))
    assert client.get("/console/assets/tokens.css").status_code == 404


def test_common_assets_are_404_until_configured():
    client = _client(FakeRobot("rosy_01"))
    assert client.get("/common/tokens.css").status_code == 404
    assert client.get("/common/core_ui_logic.js").status_code == 404


def test_common_assets_serve_only_the_configured_allowlist(tmp_path):
    tokens = tmp_path / "tokens.css"
    tokens.write_text(":root { --probe: #000000; }", encoding="utf-8")
    logic = tmp_path / "core_ui_logic.js"
    logic.write_text("export class HeadlessState {}", encoding="utf-8")
    client = _client(FakeRobot("rosy_01"), web_common=tmp_path)
    resp = client.get("/common/tokens.css")
    assert resp.status_code == 200
    assert resp.text == ":root { --probe: #000000; }"
    assert client.get("/common/core_ui_logic.js").status_code == 200
    assert client.get("/common/secret.txt").status_code == 404
    assert client.get("/ui/tokens.css").text == resp.text


def test_asset_allowlist_refuses_anything_it_does_not_name():
    """allowlist 가 경로 순회를 막는 유일한 방어다 — 디렉터리 스캔으로 바꾸지 않는다."""
    client = _client(FakeRobot("rosy_01"))
    assert client.get("/console/assets/../console.py").status_code == 404
    assert client.get("/console/assets/secrets.env").status_code == 404
