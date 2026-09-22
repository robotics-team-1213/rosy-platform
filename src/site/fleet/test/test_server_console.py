"""FleetConsole — 모음과 흩뿌림의 규칙. 네트워크 없이 가짜 로봇으로 돈다."""

from __future__ import annotations

import pytest

from fakes import FakeClock, FakeRobot, run
from fleet.hub.hub import HubError
from fleet.server.console import FleetConsole
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import RobotApiError

GRID = {"map_id": "occupancy:abc", "width": 2, "height": 2, "resolution": 0.05,
        "origin": {"x": -0.05, "y": -0.05, "yaw": 0.0}, "data": [-1, 0, 0, 100]}


def _console(*robots: FakeRobot, clock=None) -> FleetConsole:
    endpoints = [RobotEndpoint(robot_id=r.robot_id, base_url=f"http://127.0.0.1:808{i}",
                               token="t") for i, r in enumerate(robots)]
    return FleetConsole(endpoints, list(robots), clock=clock or FakeClock())


def test_snapshot_reports_every_robot_even_when_one_is_unreachable():
    """한 대가 죽었다고 나머지가 화면에서 사라지면 관제로 못 쓴다."""
    up = FakeRobot("rosy_01", state={"robot_id": "rosy_01", "mode": "IDLE"})
    down = FakeRobot("rosy_02")
    down.state_error = ConnectionError("no route to host")
    snapshot = run(_console(up, down).snapshot())

    assert [r["robot_id"] for r in snapshot["robots"]] == ["rosy_01", "rosy_02"]
    assert snapshot["fleet"]["online"] == 1 and snapshot["fleet"]["total"] == 2
    assert snapshot["robots"][0]["state"]["mode"] == "IDLE"
    assert snapshot["robots"][1]["state"] is None


def test_snapshot_separates_a_robot_that_refused_from_one_we_never_reached():
    """401 은 '거기 있고 거절했다'이고 ConnectionError 는 '닿지 못했다'다.
    운영자가 토큰을 고칠지 전원을 볼지는 이 구분에서 갈린다."""
    refused = FakeRobot("rosy_01")
    refused.state_error = RobotApiError("rosy_01", 401, "UNAUTHORIZED", "bad token")
    absent = FakeRobot("rosy_02")
    absent.state_error = OSError("connect failed")
    rows = run(_console(refused, absent).snapshot())["robots"]

    assert rows[0]["error"]["reachable"] is True
    assert rows[0]["error"]["code"] == "UNAUTHORIZED"
    assert rows[1]["error"]["reachable"] is False


def test_map_falls_through_to_the_next_robot_and_is_then_cached():
    """맵은 사이트에 하나다. 한 대가 못 줘도 다음 대에서 받고, 받은 뒤엔 N배로 다시 묻지 않는다."""
    first = FakeRobot("rosy_01")
    first.map_error = ConnectionError("down")
    second = FakeRobot("rosy_02", map=GRID)
    clock = FakeClock()
    console = _console(first, second, clock=clock)

    assert run(console.map())["map_id"] == "occupancy:abc"
    assert run(console.map())["map_id"] == "occupancy:abc"
    assert sum(1 for c in second.calls if c[0] == "map") == 1

    clock.advance(11.0)
    run(console.map())
    assert sum(1 for c in second.calls if c[0] == "map") == 2


def test_map_is_none_when_nobody_serves_one():
    """맵이 없어도 관제는 떠야 한다 — 목록만으로도 상태는 보인다."""
    blind = FakeRobot("rosy_01")
    blind.map_error = ConnectionError("down")
    assert run(_console(blind).map()) is None


def test_the_fleet_remembers_the_goal_it_dispatched():
    """미션은 Fleet 개념이다(D-12). 로봇 상태 스냅샷에는 목표가 없다."""
    robot = FakeRobot("rosy_01")
    console = _console(robot)

    run(console.goal("rosy_01", 1.5, -0.5, 0.0))
    assert run(console.snapshot())["robots"][0]["goal"] == {"x": 1.5, "y": -0.5, "yaw": 0.0}
    assert ("navigation_goal", 1.5, -0.5, 0.0) in robot.calls

    run(console.cancel("rosy_01"))
    assert run(console.snapshot())["robots"][0]["goal"] is None


def test_a_rejected_goal_is_not_remembered():
    """거절된 목표가 지도에 남으면 운영자는 가지도 않을 곳으로 간다고 읽는다."""
    robot = FakeRobot("rosy_01")

    async def refuse(x, y, yaw):
        raise RobotApiError("rosy_01", 409, "MODE_CONFLICT", "not in NAVIGATION")

    robot.navigation_goal = refuse
    console = _console(robot)

    with pytest.raises(RobotApiError):
        run(console.goal("rosy_01", 1.0, 1.0))
    assert run(console.snapshot())["robots"][0]["goal"] is None


def test_estop_reaches_every_robot_even_when_one_refuses():
    """닿지 않는 한 대 때문에 멈출 수 있었던 나머지가 계속 움직이는 것이 최악이다."""
    good = FakeRobot("rosy_01")
    bad = FakeRobot("rosy_02")

    async def blow_up():
        raise ConnectionError("gone")

    bad.estop = blow_up
    result = run(_console(good, bad).estop_all())

    assert result["stopped"] == 1 and result["total"] == 2
    assert ("estop",) in good.calls
    assert result["robots"][1]["error"]["reachable"] is False


def test_estop_keeps_the_goal_of_a_robot_that_did_not_stop():
    """선 로봇의 목표만 지운다. 못 선 대의 목표를 지우면 화면은 '아무 데도 안 간다'가
    되지만 실제로는 아직 가고 있다."""
    good = FakeRobot("rosy_01")
    bad = FakeRobot("rosy_02")

    async def blow_up():
        raise ConnectionError("gone")

    bad.estop = blow_up
    console = _console(good, bad)
    run(console.goal("rosy_01", 1.0, 0.0))
    run(console.goal("rosy_02", 2.0, 0.0))

    run(console.estop_all())
    rows = run(console.snapshot())["robots"]
    assert rows[0]["goal"] is None
    assert rows[1]["goal"] == {"x": 2.0, "y": 0.0, "yaw": 0.0}


def test_unknown_robot_is_refused_before_any_transport():
    console = _console(FakeRobot("rosy_01"))
    with pytest.raises(HubError):
        run(console.goal("rosy_99", 0.0, 0.0))


class _DegradedSpec:
    formation = "COLUMN"
    max_speed = 0.4


class _DegradedSession:
    state = "RUNNING"
    spec = _DegradedSpec()
    assignment = ["rosy_02"]


def test_degraded_member_actually_triggers_auto_speed_reform():
    """ADR-1000: 저하 멤버 감지 시 자동 감속 reform 이 실제로 나가야 한다.
    spec.name 오타(AttributeError)가 except 로 삼켜져 한 번도 살지 못했다."""
    console = _console(FakeRobot("rosy_01", state={"robot_id": "rosy_01"}),
                       FakeRobot("rosy_02", state={"robot_id": "rosy_02"}))
    console._formation = _DegradedSession()
    calls: list = []

    async def _reform(formation, spacing=None, max_speed=None):
        calls.append((formation, max_speed))

    console.formation_reform = _reform
    rows = [{"robot_id": "rosy_02",
             "state": {"capabilities_degraded": ["vision"]}}]
    run(console._manage_swarm_speed(rows))
    assert calls == [("COLUMN", 0.2)]


def test_healthy_swarm_does_not_auto_reform():
    console = _console(FakeRobot("rosy_01", state={"robot_id": "rosy_01"}),
                       FakeRobot("rosy_02", state={"robot_id": "rosy_02"}))
    console._formation = _DegradedSession()
    calls: list = []

    async def _reform(formation, spacing=None, max_speed=None):
        calls.append((formation, max_speed))

    console.formation_reform = _reform
    run(console._manage_swarm_speed(
        [{"robot_id": "rosy_02", "state": {"capabilities_degraded": []}}]))
    assert calls == []


def test_failing_auto_reform_is_logged_and_survives():
    """reform 이 실패해도 관제 루프는 산다 — 다만 이제 보이게 실패한다."""
    import logging

    console = _console(FakeRobot("rosy_01", state={"robot_id": "rosy_01"}))
    console._formation = _DegradedSession()

    async def _boom(formation, spacing=None, max_speed=None):
        raise OSError("hub down")

    console.formation_reform = _boom
    records: list = []

    class _Handler(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _Handler()
    logger = logging.getLogger("fleet.console")
    logger.addHandler(handler)
    try:
        run(console._manage_swarm_speed(
            [{"robot_id": "rosy_02",
              "state": {"capabilities_degraded": ["vision"]}}]))
    finally:
        logger.removeHandler(handler)
    assert any("auto speed reform failed" in r.getMessage() for r in records)
