"""선착 우선권 — 대기자들이 한꺼번에 풀릴 때 누가 먼저 나가나.

`test_server_traffic` 은 순서를 "늦게 온 미션이 기다린다"로 만들고, `test_server_yield`
은 서 있는 로봇을 치운다. 여기는 그 다음이다 — 로터리의 선착 우권. 블로커가 사라져
여러 대기 미션이 같은 순간에 풀릴 때, 공유 충돌 지점에 먼저 도달하는 미션이 먼저
나가야 한다. robot_id 순서는 타이브레이크일 뿐이다.

상한선은 그대로다 — 점유 클레임(달리는 로봇)은 절대 여기서 밀려나지 않는다. 선착이
고르는 것은 대기자들 사이의 순서다.
"""

from __future__ import annotations

import math

from fakes import FakeRobot, run
from test_server_bays import HALL, payload
from test_server_yield import SimRobot, _console, _goals, _row
from fleet.server import traffic


# --- 순수 기하 --------------------------------------------------------------------


def _line(x0, y0, x1, y1, n=20):
    return [(x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n) for i in range(n + 1)]


def test_closest_points_finds_the_sharing_zone():
    a = _line(0.0, 0.0, 2.0, 0.0)
    b = _line(1.5, 1.0, 1.5, 0.2, 8)
    pair = traffic.closest_points(a, b)
    assert pair is not None
    (pa, pb) = pair
    # thin() 이 0.2 m 간격 꼭짓점만 남기므로 꼭짓점 수준의 최근접이다. 실제 플래너
    # 경로는 5 cm 밀도라 실전 오차는 이보다 작다.
    assert math.dist(pa, pb) <= 0.25
    assert abs(pb[1] - 0.2) < 1e-6


def test_closest_points_with_an_empty_route_is_none():
    assert traffic.closest_points([], [(0.0, 0.0)]) is None
    assert traffic.closest_points([(0.0, 0.0)], []) is None


def test_remaining_distance_measures_along_the_route():
    route = _line(0.0, 0.0, 2.0, 0.0)
    d = traffic.remaining_distance(route, (0.2, 0.0), (1.5, 0.0))
    assert d is not None and abs(d - 1.3) < 0.11


def test_remaining_distance_behind_the_start_is_none():
    """목표가 이미 지나친 뒤면 도달하지 못한다 — 선착에서 무한대로 밀린다."""
    route = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]
    d = traffic.remaining_distance(route, (1.8, 0.0), (0.5, 0.0))
    assert d is None


def test_remaining_distance_with_unknowns_is_none():
    route = [(0.0, 0.0), (1.0, 0.0)]
    assert traffic.remaining_distance([], (0.0, 0.0), (1.0, 0.0)) is None
    assert traffic.remaining_distance(route, None, (1.0, 0.0)) is None
    assert traffic.remaining_distance(route, (0.0, 0.0), None) is None


# --- 콘솔: 대기 풀기 순서 ----------------------------------------------------------


def _queued_console():
    """블로커(rosy_03) 뒤에 두 대가 대기 중인 콘솔. rosy_01 은 멀리, rosy_02 는
    공유 충돌 지점(1.5, 1.05) 바로 앞에 선다."""
    grid = payload(HALL)
    far = SimRobot("rosy_01", (0.2, 1.05), grid)
    near = SimRobot("rosy_02", (1.3, 1.05), grid)
    blocker = FakeRobot("rosy_03", map=grid,
                        state={"robot_id": "rosy_03", "navigation": "IDLE",
                               "map_id": "m1", "pose": {"x": 2.2, "y": 3.0, "yaw": 0.0}})
    console = _console(far, near, blocker)
    console._queued["rosy_01"] = {
        "x": 2.2, "y": 1.05, "yaw": 0.0, "blocked_by": "rosy_03",
        "waiting_on": ["rosy_03"], "reason": "ROUTE_CONFLICT",
        "route": [(0.2 + 0.2 * i, 1.05) for i in range(11)]}
    console._queued["rosy_02"] = {
        "x": 2.2, "y": 1.05, "yaw": 0.0, "blocked_by": "rosy_03",
        "waiting_on": ["rosy_03"], "reason": "ROUTE_CONFLICT",
        "route": [(1.3 + 0.2 * i, 1.05) for i in range(5)]}
    return far, near, blocker, console


def test_the_nearer_mission_is_released_first_when_the_blocker_clears():
    """선착. 둘 다 풀리는 순간, 공유 충돌 지점에 가까운 rosy_02 가 먼저 나간다.

    robot_id 순이었다면 rosy_01 이 먼저 나가 rosy_02 를 다시 세웠을 것이다 — 도로의
    교차로에서 먼저 온 차가 나중에 온 차를 막아 세우는 것과 같은 역전이다.
    """
    far, near, blocker, console = _queued_console()

    run(console.snapshot())

    assert _goals(near) == [(2.2, 1.05)]          # 가까운 쪽이 먼저 나갔다
    assert near._state["navigation"] == "NAVIGATING"
    row = _row(run(console.snapshot()), "rosy_01")
    assert row["queued"] is not None              # 먼 쪽은 다시 대기
    assert row["queued"]["blocked_by"] == "rosy_02"


def test_ties_fall_back_to_robot_id_order():
    """같은 거리(경로 모름)면 결정적으로 robot_id 순이다. 같은 상황에서 매번 같은 대가
    먼저 나가야 운영자가 화면을 읽을 수 있다. 단 서 있는 로봇이 상대 경로 위에 있으면
    양보 판정이 먼저 개입하므로, 여기서는 길 밖에 세운다."""
    grid = payload(HALL)
    first = SimRobot("rosy_01", (1.0, 1.05), grid)
    second = SimRobot("rosy_02", (1.0, 2.8), grid)
    console = _console(first, second)
    for rid in ("rosy_01", "rosy_02"):
        console._queued[rid] = {
            "x": 2.2, "y": 1.05, "yaw": 0.0, "blocked_by": "rosy_03",
            "waiting_on": ["rosy_03"], "reason": "ROUTE_CONFLICT",
            "route": []}

    run(console.snapshot())

    assert _goals(first) == [(2.2, 1.05)]
    assert first._state["navigation"] == "NAVIGATING"
    # second 도 재하달을 시도하지만, first 의 새 클레임에 막혀 취소되고 뒤로 선다.
    assert ("navigation_cancel",) in second.calls
    assert console._queued.get("rosy_02", {}).get("blocked_by") == "rosy_01"


def test_a_mission_without_a_route_still_releases_last_not_never():
    """경로를 모르는 대기자는 선착에서 밀릴 뿐, 영영 못 나가는 것이 아니다."""
    grid = payload(HALL)
    far = SimRobot("rosy_01", (0.2, 1.05), grid)
    near = SimRobot("rosy_02", (2.0, 2.8), grid)
    console = _console(far, near)
    console._queued["rosy_01"] = {
        "x": 2.2, "y": 1.05, "yaw": 0.0, "blocked_by": "rosy_03",
        "waiting_on": ["rosy_03"], "reason": "ROUTE_CONFLICT",
        "route": _line(0.2, 1.05, 2.2, 1.05)}
    console._queued["rosy_02"] = {
        "x": 2.2, "y": 1.05, "yaw": 0.0, "blocked_by": "rosy_03",
        "waiting_on": ["rosy_03"], "reason": "ROUTE_CONFLICT"}

    run(console.snapshot())

    assert _goals(far) == [(2.2, 1.05)]            # 경로 아는 쪽이 먼저 나간다
    assert far._state["navigation"] == "NAVIGATING"
    # 경로 모르는 쪽은 선착에서 밀려 뒤에 섰다가, 재하달 시도 후 다시 대기로 돌아간다
    # — 영영 못 나가는 것이 아니라 순서가 늦은 것뿐이다.
    assert console._queued.get("rosy_02", {}).get("blocked_by") == "rosy_01"
