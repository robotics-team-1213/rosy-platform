"""교통 정리 — 경로 충돌 판정(순수)과 미션 대기열(콘솔)."""

from __future__ import annotations

import pytest

from fakes import FakeRobot, run
from fleet.server import traffic
from fleet.server.console import FleetConsole
from fleet.swarm.robots import RobotEndpoint


def _line(x0, y0, x1, y1, n=40):
    return [(x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n) for i in range(n + 1)]


# --- 순수 기하 -------------------------------------------------------------------


def test_coincident_poses_are_closer_than_a_footprint():
    """D-116: 0.05 m 는 겹친 보고이지, 0.6 m spawn 간격이 아니다."""
    assert traffic.coincident((0.0, 0.0), (0.0, 0.0))
    assert traffic.coincident((0.0, 0.0), (0.04, 0.0))
    assert not traffic.coincident((0.0, 0.0), (0.6, 0.0))
    assert not traffic.coincident((-0.2, 1.05), (0.4, 1.05))


def test_head_on_routes_in_the_same_corridor_conflict():
    """폭 1.4 m 통로를 마주 보고 지나는 두 경로. 실제로 두 대가 0.10 m 간격으로 갇혔던 장면이다."""
    assert traffic.routes_conflict(_line(-2.2, 0, 2.2, 0), _line(2.2, 0.1, -2.2, 0.1))


def test_routes_in_different_corridors_do_not_conflict():
    """옆 통로를 나란히 가는 경로까지 막으면 현장이 한 대씩만 움직이는 곳이 된다."""
    assert not traffic.routes_conflict(_line(-2.2, 0, 2.2, 0), _line(-2.2, 1.5, 2.2, 1.5))


def test_an_unknown_route_never_blocks():
    """계획을 아직 못 읽었다는 이유로 미션을 막으면, 로봇 하나가 늦다고 현장이 선다."""
    assert not traffic.routes_conflict([], _line(0, 0, 1, 0))
    assert traffic.closest_approach([], _line(0, 0, 1, 0)) is None


def test_thin_keeps_both_ends():
    """끝점을 버리면 경로의 목표 근처가 판정에서 사라진다."""
    points = _line(0, 0, 1, 0, n=100)
    kept = traffic.thin(points, step=0.2)
    assert kept[0] == points[0] and kept[-1] == points[-1]
    assert len(kept) < len(points)


def test_the_blocker_is_chosen_in_a_fixed_order():
    """두 대가 서로 양보하면 둘 다 선다. 같은 상황에서는 늘 같은 대가 막는 쪽이어야 한다."""
    route = _line(0, 0, 2, 0)
    claims = {"rosy_03": _line(0, 0.1, 2, 0.1), "rosy_02": _line(0, -0.1, 2, -0.1)}
    assert traffic.blocking_robot(route, claims) == "rosy_02"
    assert traffic.blocking_robot(route, claims, skip=("rosy_02",)) == "rosy_03"


def test_a_robot_does_not_block_itself():
    route = _line(0, 0, 2, 0)
    assert traffic.blocking_robot(route, {"rosy_01": route}, skip=("rosy_01",)) is None


# --- 콘솔 대기열 -----------------------------------------------------------------


def _console(*robots: FakeRobot) -> FleetConsole:
    endpoints = [RobotEndpoint(robot_id=r.robot_id, base_url=f"http://127.0.0.1:808{i}",
                               token="t") for i, r in enumerate(robots)]
    return FleetConsole(endpoints, list(robots))


def _navigating(robot_id):
    return {"robot_id": robot_id, "navigation": "NAVIGATING"}


def _arrived(robot_id):
    return {"robot_id": robot_id, "navigation": "ARRIVED"}


def test_a_conflicting_mission_is_cancelled_and_queued():
    """내려간 뒤 경로를 보고 판단한다 — 경로는 목표를 받아야 생긴다. 되돌리는 값은 취소 한 번이다."""
    first = FakeRobot("rosy_01", state=_navigating("rosy_01"))
    first._path = _line(-2.0, 0, 2.0, 0)
    second = FakeRobot("rosy_02", state=_navigating("rosy_02"))
    second._path = _line(2.0, 0.1, -2.0, 0.1)
    console = _console(first, second)

    run(console.goal("rosy_01", 2.0, 0.0))
    result = run(console.goal("rosy_02", -2.0, 0.1))

    assert result["queued"] is True and result["blocked_by"] == "rosy_01"
    assert ("navigation_cancel",) in second.calls
    row = [r for r in run(console.snapshot())["robots"] if r["robot_id"] == "rosy_02"][0]
    assert row["queued"]["blocked_by"] == "rosy_01"
    assert row["goal"] is None          # 아직 가지 않는 곳을 목표로 그리지 않는다


def test_task_traffic_queue_preserves_task_attempt_and_waits_for_scheduler_release():
    first = FakeRobot("rosy_01", state=_navigating("rosy_01"))
    first._path = _line(-2.0, 0, 2.0, 0)
    second = FakeRobot("rosy_02", state=_navigating("rosy_02"))
    second._path = _line(2.0, 0.1, -2.0, 0.1)
    console = _console(first, second)
    released = []
    console.set_task_queue_release_callback(lambda mission: _record_release(released, mission))
    run(console.goal("rosy_01", 2.0, 0.0))

    result = run(console.goal(
        "rosy_02", -2.0, 0.1, task_id="task-42", attempt_id="attempt-1", attempt_seq=1,
    ))

    assert result["accepted"] is False
    assert result["queued"] is True
    assert result["cancel_confirmed"] is True
    assert console._queued["rosy_02"]["task_id"] == "task-42"
    assert console._queued["rosy_02"]["attempt_id"] == "attempt-1"
    assert sum(1 for call in second.calls if call[0] == "navigation_goal") == 1

    first._state = _arrived("rosy_01")
    run(console.snapshot())

    assert len(released) == 1
    assert released[0]["task_id"] == "task-42"
    assert sum(1 for call in second.calls if call[0] == "navigation_goal") == 1


async def _record_release(rows, mission):
    rows.append(dict(mission))


def test_task_traffic_queue_requires_confirmed_cancel_before_waiting():
    first = FakeRobot("rosy_01", state=_navigating("rosy_01"))
    first._path = _line(-2.0, 0, 2.0, 0)
    second = FakeRobot("rosy_02", state=_navigating("rosy_02"))
    second._path = _line(2.0, 0.1, -2.0, 0.1)

    async def ambiguous_cancel():
        second._record("navigation_cancel")
        return {"navigation": "IDLE"}

    second.navigation_cancel = ambiguous_cancel
    console = _console(first, second)
    run(console.goal("rosy_01", 2.0, 0.0))

    try:
        run(console.goal("rosy_02", -2.0, 0.1, task_id="task-ambiguous"))
    except RuntimeError as exc:
        assert "cancellation" in str(exc)
    else:
        raise AssertionError("traffic wait requires a positive cancellation receipt")

    assert "rosy_02" not in console._queued
    assert console._goals["rosy_02"] == {"x": -2.0, "y": 0.1, "yaw": 0.0}


def test_the_queued_mission_goes_out_once_the_blocker_stops_navigating():
    first = FakeRobot("rosy_01", state=_navigating("rosy_01"))
    first._path = _line(-2.0, 0, 2.0, 0)
    second = FakeRobot("rosy_02", state=_navigating("rosy_02"))
    second._path = _line(2.0, 0.1, -2.0, 0.1)
    console = _console(first, second)
    run(console.goal("rosy_01", 2.0, 0.0))
    run(console.goal("rosy_02", -2.0, 0.1))

    first._state = _arrived("rosy_01")
    second._path = _line(2.0, 0.1, -2.0, 0.1)
    snapshot = run(console.snapshot())

    row = [r for r in snapshot["robots"] if r["robot_id"] == "rosy_02"][0]
    assert row["queued"] is None
    assert row["goal"] == {"x": -2.0, "y": 0.1, "yaw": 0.0}
    assert sum(1 for c in second.calls if c[0] == "navigation_goal") == 2


def test_a_non_conflicting_mission_goes_straight_out():
    first = FakeRobot("rosy_01", state=_navigating("rosy_01"))
    first._path = _line(-2.0, 0, 2.0, 0)
    second = FakeRobot("rosy_02", state=_navigating("rosy_02"))
    second._path = _line(-2.0, 1.5, 2.0, 1.5)
    console = _console(first, second)

    run(console.goal("rosy_01", 2.0, 0.0))
    result = run(console.goal("rosy_02", 2.0, 1.5))

    assert "queued" not in result
    assert ("navigation_cancel",) not in second.calls


def test_a_robot_that_cannot_report_its_path_is_still_dispatched():
    """경로를 못 읽는다고 막으면, 계획을 늦게 내는 로봇 한 대가 현장을 세운다."""
    first = FakeRobot("rosy_01", state=_navigating("rosy_01"))
    first._path = _line(-2.0, 0, 2.0, 0)
    second = FakeRobot("rosy_02", state=_navigating("rosy_02"))
    second.path_error = ConnectionError("no path yet")
    console = _console(first, second)

    run(console.goal("rosy_01", 2.0, 0.0))
    result = run(console.goal("rosy_02", -2.0, 0.0))

    assert "queued" not in result


def test_cancelling_a_mission_frees_the_corridor_for_the_queued_one():
    first = FakeRobot("rosy_01", state=_navigating("rosy_01"))
    first._path = _line(-2.0, 0, 2.0, 0)
    second = FakeRobot("rosy_02", state=_navigating("rosy_02"))
    second._path = _line(2.0, 0.1, -2.0, 0.1)
    console = _console(first, second)
    run(console.goal("rosy_01", 2.0, 0.0))
    run(console.goal("rosy_02", -2.0, 0.1))

    run(console.cancel("rosy_01"))
    run(console.snapshot())

    assert sum(1 for c in second.calls if c[0] == "navigation_goal") == 2


def test_an_estop_drops_the_queue_instead_of_releasing_it_later():
    """전체 정지 뒤에 대기 미션이 저절로 나가면, 운영자가 세운 현장이 스스로 다시 움직인다."""
    first = FakeRobot("rosy_01", state=_navigating("rosy_01"))
    first._path = _line(-2.0, 0, 2.0, 0)
    second = FakeRobot("rosy_02", state=_navigating("rosy_02"))
    second._path = _line(2.0, 0.1, -2.0, 0.1)
    console = _console(first, second)
    run(console.goal("rosy_01", 2.0, 0.0))
    run(console.goal("rosy_02", -2.0, 0.1))

    run(console.estop_all())
    first._state = _arrived("rosy_01")
    run(console.snapshot())

    assert sum(1 for c in second.calls if c[0] == "navigation_goal") == 1


@pytest.mark.parametrize("clearance,expected", [(0.05, False), (0.7, True)])
def test_clearance_is_configurable(clearance, expected):
    a, b = _line(-1, 0, 1, 0), _line(-1, 0.1, 1, 0.1)
    assert traffic.routes_conflict(a, b, clearance) is expected
