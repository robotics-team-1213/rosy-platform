"""양보 — 관제가 서 있는 로봇을 치워 실제로 공간을 만드는지.

`test_server_traffic` 은 **순서**를 시험한다(늦게 온 미션이 기다리는가). 여기는 순서로
풀리지 않는 장면이다 — 서 있는 로봇이 상대의 목표 자리를 깔고 앉았을 때. 대기열만으로는
A 가 B 를 기다리고 B 가 A 를 기다리며 둘 다 영원히 선다.

맵은 기하 시험(`test_server_bays`)과 같은 그림을 쓴다. 두 벌이면 한쪽만 통과하는 일이
생기고, 그것은 알아채기 어렵다.
"""

from __future__ import annotations

import math

from fakes import FakeRobot, run
from test_server_bays import ALCOVE, CORRIDOR, HALL, payload
from fleet.server.console import FleetConsole
from fleet.swarm.robots import RobotEndpoint


def _line(x0, y0, x1, y1, n=30):
    return [(x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n) for i in range(n + 1)]


class SimRobot(FakeRobot):
    """목표를 받으면 제 자리에서 목표까지 직선 경로를 내고 NAVIGATING 이 된다.

    `arrive()` 로 도착시킨다. 진짜 주행은 아니지만 관제가 보는 것 — 경로, 주행 상태,
    pose — 은 전부 실제와 같은 자리에서 온다. 여기 쓰는 맵의 통로는 직선이라 직선 경로가
    계획기가 낼 경로와 크게 다르지 않다.
    """

    def __init__(self, robot_id: str, xy, grid) -> None:
        super().__init__(robot_id, map=grid,
                         state={"robot_id": robot_id, "navigation": "IDLE", "map_id": "m1",
                                "localization": {"state": "LOCALIZED", "pose_frame": "map"},
                                "pose": {"x": xy[0], "y": xy[1], "yaw": 0.0}})
        self._target = None
        #: 거짓이면 목표를 받아도 경로를 내지 않는다 — 계획기가 아직 늦은 상태.
        self.plans = True
        #: 계획 경로가 목표보다 이만큼 앞에서 끝난다. 상대가 선 자리는 치명 비용이라
        #: 플래너가 거기까지 가지 못한다 — 실측으로 0.13 m 짧았다.
        self.plan_short_by = 0.0

    @property
    def xy(self):
        pose = self._state["pose"]
        return pose["x"], pose["y"]

    async def navigation_goal(self, x: float, y: float, yaw: float, *,
                              correlation_id: str | None = None) -> dict:
        result = await super().navigation_goal(x, y, yaw, correlation_id=correlation_id)
        path = _line(self.xy[0], self.xy[1], x, y) if self.plans else []
        if path and self.plan_short_by:
            path = [p for p in path
                    if math.dist(p, (x, y)) >= self.plan_short_by] or path[:1]
        self._path = path
        self._state = {**self._state, "navigation": "NAVIGATING"}
        self._target = (x, y)
        return result

    async def navigation_cancel(self) -> dict:
        result = await super().navigation_cancel()
        self._path = []
        self._state = {**self._state, "navigation": "IDLE"}
        self._target = None
        return result

    def arrive(self) -> None:
        assert self._target is not None, f"{self.robot_id} 는 아무 데도 가고 있지 않다"
        x, y = self._target
        self._state = {"robot_id": self.robot_id, "navigation": "ARRIVED", "map_id": "m1",
                       "localization": {"state": "LOCALIZED", "pose_frame": "map"},
                       "pose": {"x": x, "y": y, "yaw": 0.0}}
        self._path = []
        self._target = None


def _console(*robots):
    endpoints = [RobotEndpoint(robot_id=r.robot_id, base_url=f"http://127.0.0.1:808{i}",
                               token="t") for i, r in enumerate(robots)]
    return FleetConsole(endpoints, list(robots))


def _corridor(art=ALCOVE):
    """통로 양 끝에 한 대씩. 맵은 폭 1.0 m 라 서로를 지나갈 수 없다."""
    grid = payload(art)
    left = SimRobot("rosy_01", (0.4, 0.6), grid)
    right = SimRobot("rosy_02", (2.2, 0.6), grid)
    return left, right, _console(left, right)


def _goals(robot):
    return [(c[1], c[2]) for c in robot.calls if c[0] == "navigation_goal"]


# --- 공간 만들기 -----------------------------------------------------------------


def test_coincident_origin_reports_do_not_look_like_a_blocked_corridor():
    """D-116: 둘 다 odom (0,0) 이면 양보 미션을 만들지 않는다."""
    grid = payload(ALCOVE)
    left = SimRobot("rosy_01", (0.0, 0.0), grid)
    right = SimRobot("rosy_02", (0.0, 0.0), grid)
    console = _console(left, right)

    result = run(console.goal("rosy_01", 0.3, 1.05))

    assert result.get("reason") != "YIELDING"
    assert result.get("queued") is not True
    assert _goals(right) == []
    assert _goals(left) == [(0.3, 1.05)]


def test_the_robot_in_the_way_is_sent_to_a_bay_and_the_mission_waits():
    left, right, console = _corridor()

    result = run(console.goal("rosy_01", 2.2, 0.6))

    assert result["queued"] is True and result["reason"] == "YIELDING"
    assert result["yielding"] == ["rosy_02"]
    bay = _goals(right)[-1]
    assert bay != (2.2, 0.6)                         # 제자리에 있지 않다
    assert bay[1] > 1.0                              # 벽감 쪽으로 물러났다
    # 미션을 낸 쪽은 취소되고 대기열에 있다 — 통로가 빌 때까지 들어가지 않는다.
    assert ("navigation_cancel",) in left.calls


def test_the_mission_goes_out_once_the_other_robot_has_reached_its_bay():
    left, right, console = _corridor()
    run(console.goal("rosy_01", 2.2, 0.6))

    run(console.snapshot())                           # 아직 비켜서는 중
    assert _goals(left) == [(2.2, 0.6)]               # 아직 다시 나가지 않았다

    right.arrive()
    row = _row(run(console.snapshot()), "rosy_01")

    assert row["queued"] is None
    assert row["goal"] == {"x": 2.2, "y": 0.6, "yaw": 0.0}
    assert _goals(left) == [(2.2, 0.6), (2.2, 0.6)]   # 같은 목표로 다시 나갔다


def test_two_robots_swap_ends_of_a_single_lane_corridor():
    """이 파일의 이유. 대기열만으로는 절대 끝나지 않는 미션 쌍이다."""
    left, right, console = _corridor()

    run(console.goal("rosy_01", 2.2, 0.6))            # rosy_02 가 벽감으로 비켜선다
    run(console.goal("rosy_02", 0.4, 0.6))            # 비켜서는 중이라 대기열로
    right.arrive()                                     # 벽감 도착
    run(console.snapshot())                            # rosy_01 출발
    left.arrive()                                      # 반대편 끝 도착
    run(console.snapshot())                            # rosy_02 출발
    right.arrive()

    assert left.xy == (2.2, 0.6)
    assert right.xy == (0.4, 0.6)
    snapshot = run(console.snapshot())
    assert all(r["queued"] is None for r in snapshot["robots"])
    assert all(r["yielding"] is None for r in snapshot["robots"])


def test_the_swap_works_in_either_order():
    """운영자가 어느 쪽 미션을 먼저 내리든 같아야 한다."""
    left, right, console = _corridor()

    run(console.goal("rosy_02", 0.4, 0.6))
    run(console.goal("rosy_01", 2.2, 0.6))
    left.arrive()
    run(console.snapshot())
    right.arrive()
    run(console.snapshot())
    left.arrive()

    assert left.xy == (2.2, 0.6)
    assert right.xy == (0.4, 0.6)


def test_the_yielder_goes_back_to_its_own_goal_afterwards():
    """비켜서는 것은 잠깐 물러나는 것이지 미션 취소가 아니다."""
    left, right, console = _corridor()
    run(console.goal("rosy_02", 2.2, 0.6))            # 제자리 근처가 목표
    right.arrive()
    run(console.snapshot())

    run(console.goal("rosy_01", 2.2, 0.6))            # rosy_02 가 비켜선다
    right.arrive()
    run(console.snapshot())
    left.arrive()
    run(console.snapshot())

    # 지나간 뒤 제 목표로 돌아간다 — 운영자가 보낸 곳에서 로봇이 사라지지 않는다.
    assert _goals(right)[-1] == (2.2, 0.6)


# --- 자리가 없을 때 --------------------------------------------------------------


def test_a_corridor_without_a_bay_says_so_instead_of_pretending():
    """폭 1 m 방의 정직한 답이다. 실측에서 두 대가 자리를 맞바꾸지 못한 그 맵이다."""
    left, right, console = _corridor(CORRIDOR)

    result = run(console.goal("rosy_01", 2.2, 0.6))

    assert result["queued"] is True
    assert result["reason"] == "NO_YIELD_SPACE"
    assert result["no_space"] == ["rosy_02"]
    assert _goals(right) == []                        # 아무 데로도 보내지 않았다


def test_neither_half_of_an_impossible_swap_drives_into_the_other_robot():
    """실측 — 폭 1 m 방에서 둘째 미션이 나가 상대 0.19 m 앞까지 밀고 들어갔다.

    자리가 없다고 첫 미션을 세워 놓고 둘째는 내보내면, 관제가 막았다고 말한 그 통로로
    로봇이 들어간다. 사람이 보기에는 관제가 거짓말을 한 것이다.
    """
    left, right, console = _corridor(CORRIDOR)

    run(console.goal("rosy_01", 2.2, 0.6))            # rosy_02 가 막았다 — 자리 없음
    second = run(console.goal("rosy_02", 0.4, 0.6))   # 이제 rosy_01 이 막는다

    assert second["queued"] is True
    assert second["reason"] == "NO_YIELD_SPACE"
    assert ("navigation_cancel",) in right.calls
    assert all(r["queued"] is not None for r in run(console.snapshot())["robots"])


def test_a_robot_with_no_plan_yet_is_still_checked_against_who_is_standing_there():
    """실측에서 이 틈으로 로봇이 들어갔다 — 계획 경로는 목표를 받은 뒤에야 생긴다.

    빈 경로를 "아무도 안 막는다"로 읽으면, 계획기가 몇백 ms 늦은 것만으로 관제의 판단이
    통째로 건너뛰어진다. 어디로 갈지는 몰라도 어디서 어디로 가는지는 안다.
    """
    left, right, console = _corridor(CORRIDOR)
    left.plans = False                                 # 계획기가 아직 경로를 못 냈다

    result = run(console.goal("rosy_01", 2.2, 0.6))

    assert result["queued"] is True and result["reason"] == "NO_YIELD_SPACE"
    assert ("navigation_cancel",) in left.calls


def test_a_robot_with_no_plan_yet_still_yields_when_there_is_a_bay():
    left, right, console = _corridor()
    left.plans = False

    result = run(console.goal("rosy_01", 2.2, 0.6))

    assert result["reason"] == "YIELDING" and result["yielding"] == ["rosy_02"]


def test_a_mission_blocked_with_no_space_is_released_when_the_way_clears():
    """사람이 손을 대 로봇을 치우면 미션은 저절로 나가야 한다 — 다시 내리게 하면 안 된다."""
    left, right, console = _corridor(CORRIDOR)
    run(console.goal("rosy_01", 2.2, 0.6))

    # 운영자가 rosy_02 를 통로 밖으로 뺐다고 하자 (여기서는 좌표만 옮긴다).
    right._state = {"robot_id": "rosy_02", "navigation": "ARRIVED", "map_id": "m1",
                    "localization": {"state": "LOCALIZED", "pose_frame": "map"},
                    "pose": {"x": 2.2, "y": 3.0, "yaw": 0.0}}
    row = _row(run(console.snapshot()), "rosy_01")

    assert row["queued"] is None
    assert _goals(left) == [(2.2, 0.6), (2.2, 0.6)]


def test_a_yield_that_did_not_open_the_way_stops_promising_it_will():
    """실측에서 온 시험 — 2x1 m 방의 두 대가 "물러나면 자동 출발합니다" 아래서 한없이 섰다.

    기다리는 것 자체는 맞다(물리가 그렇다). 거짓말은 곧 풀린다고 말한 쪽이다. 비켜선
    로봇이 멈췄는데도 길이 안 열렸으면 화면은 사람을 불러야 한다.
    """
    left, right, console = _corridor()
    run(console.goal("rosy_01", 2.2, 0.6))
    assert _row(run(console.snapshot()), "rosy_01")["queued"]["reason"] == "YIELDING"

    # 비켜서긴 했는데 충분히 못 갔다 — 목표에 못 미쳐 서는 실제 장면이다.
    right._state = {"robot_id": "rosy_02", "navigation": "ARRIVED", "map_id": "m1",
                    "pose": {"x": 1.25, "y": 0.9, "yaw": 0.0}}
    right._target = None
    for _ in range(4):
        run(console.snapshot())

    row = _row(run(console.snapshot()), "rosy_01")
    assert row["queued"]["reason"] == "NO_YIELD_SPACE"
    assert _goals(left) == [(2.2, 0.6)]        # 여전히 안 보낸다 — 길이 실제로 막혔다


def test_a_yield_still_in_progress_is_not_called_a_failure():
    """움직이는 중인 로봇을 실패로 읽으면, 잘 되던 양보가 매번 경고로 끝난다."""
    left, right, console = _corridor()
    run(console.goal("rosy_01", 2.2, 0.6))

    for _ in range(6):
        run(console.snapshot())               # rosy_02 는 계속 NAVIGATING

    assert _row(run(console.snapshot()), "rosy_01")["queued"]["reason"] == "YIELDING"


# --- 끼어들지 않아야 할 때 --------------------------------------------------------


def test_a_robot_clear_of_the_path_is_not_moved():
    """폭이 아니라 경로 거리로 뺀다 (D-93). keep-out 밖이면 구석으로 안 보낸다."""
    grid = payload(HALL)
    left = SimRobot("rosy_01", (0.4, 1.05), grid)
    beside = SimRobot("rosy_02", (1.3, 1.7), grid)
    console = _console(left, beside)

    result = run(console.goal("rosy_01", 2.2, 1.05))

    assert "queued" not in result
    assert _goals(beside) == []


def test_a_robot_parked_on_the_goal_is_moved_even_in_a_wide_hall():
    """폭과 무관하다 — 목표 자리를 깔고 앉은 로봇이 있으면 그 자리에는 아무도 못 선다."""
    grid = payload(HALL)
    left = SimRobot("rosy_01", (0.4, 1.05), grid)
    on_goal = SimRobot("rosy_02", (2.2, 1.05), grid)
    console = _console(left, on_goal)

    result = run(console.goal("rosy_01", 2.2, 1.05))

    assert result["reason"] == "YIELDING"
    assert _goals(on_goal), "넓은 방에는 비켜설 자리가 얼마든지 있다"


def test_without_a_map_nobody_is_moved_aside_merely_for_being_near_the_route():
    """맵을 못 읽었다는 이유로 로봇을 옮기면, 그 좌표에 무엇이 있는지 아무도 모른다."""
    left = SimRobot("rosy_01", (0.4, 0.6), None)
    beside = SimRobot("rosy_02", (1.3, 0.75), None)
    console = _console(left, beside)

    result = run(console.goal("rosy_01", 2.2, 0.6))

    assert "queued" not in result
    assert _goals(beside) == []


def test_a_truncated_plan_does_not_hide_the_robot_sitting_on_the_goal():
    """실측 — 장애물 레이어가 살아난 뒤 계획 경로는 목표에 0.13 m 못 미쳐 끝난다.

    상대가 선 자리가 치명 비용이라 플래너가 거기까지 가지 못한다. 잘린 끝을 목표로 알면
    "목표를 깔고 앉았다"는 판정이 그만큼 물러난 자리에서 이뤄진다. 지시한 목표로 봐야 한다.
    """
    grid = payload(HALL)
    left = SimRobot("rosy_01", (0.4, 1.05), grid)
    on_goal = SimRobot("rosy_02", (2.2, 1.05), grid)
    # 계획 경로가 목표 0.3 m 앞에서 끊긴 상태를 흉내낸다.
    left.plan_short_by = 0.3
    console = _console(left, on_goal)

    result = run(console.goal("rosy_01", 2.2, 1.05))

    assert result["reason"] == "YIELDING"
    assert _goals(on_goal), "목표를 깔고 앉은 로봇은 비켜서야 한다"


def test_a_robot_sitting_on_the_goal_blocks_it_even_with_no_map_at_all():
    """실측에서 온 규칙 — 갓 시작한 콘솔이 맵을 못 받자 미션이 상대 좌표로 그냥 나갔다.

    "지나갈 수 있는가"는 지나가려는 경우의 물음이다. 목표 자리를 깔고 앉은 로봇에게는
    폭도 맵도 상관없다 - 거기에는 두 대가 설 수 없다.
    """
    left = SimRobot("rosy_01", (0.4, 0.6), None)
    on_goal = SimRobot("rosy_02", (2.2, 0.6), None)
    console = _console(left, on_goal)

    result = run(console.goal("rosy_01", 2.2, 0.6))

    assert result["queued"] is True
    # 맵이 없으면 비켜설 자리도 고를 수 없다 — 그래서 사람을 부른다.
    assert result["reason"] == "NO_YIELD_SPACE"
    assert _goals(on_goal) == []


def test_a_robot_without_a_pose_is_never_ordered_to_yield():
    """좌표를 모르는 로봇은 길을 막았다고도 비켰다고도 말할 수 없다."""
    grid = payload(ALCOVE)
    left = SimRobot("rosy_01", (0.4, 0.6), grid)
    right = SimRobot("rosy_02", (2.2, 0.6), grid)
    right._state = {"robot_id": "rosy_02", "navigation": "IDLE", "map_id": "m1"}
    console = _console(left, right)

    result = run(console.goal("rosy_01", 2.2, 0.6))

    assert result["reason"] == "LOCALIZATION_UNTRUSTED"
    assert result["blocked_by"] == "rosy_02"
    assert _goals(right) == []


def test_a_robot_that_is_already_driving_is_not_told_to_yield():
    """곧 지나갈 로봇을 붙잡아 비켜세우면 통로에 멈춘 장애물이 하나 더 생긴다."""
    left, right, console = _corridor()
    run(console.goal("rosy_02", 0.4, 0.6))            # rosy_02 가 달리며 통로를 점유
    right._state = {**right._state, "pose": {"x": 1.5, "y": 0.6, "yaw": 0.0}}

    result = run(console.goal("rosy_01", 2.2, 0.6))

    assert result["queued"] is True
    assert result.get("reason") != "YIELDING"          # 경로 충돌로 기다리는 것이다
    assert _goals(right) == [(0.4, 0.6)]               # 벽감으로 보내지 않았다


# --- 운영자가 끼어들 때 ----------------------------------------------------------


def test_an_estop_forgets_the_yields():
    """전체 정지 뒤 비켜서기가 남아 있으면, 다음 미션이 이유 없이 대기열로 간다."""
    left, right, console = _corridor()
    run(console.goal("rosy_01", 2.2, 0.6))

    run(console.estop_all())

    assert _row(run(console.snapshot()), "rosy_02")["yielding"] is None


def test_cancelling_the_yielder_clears_its_yield():
    left, right, console = _corridor()
    run(console.goal("rosy_01", 2.2, 0.6))

    run(console.cancel("rosy_02"))

    assert _row(run(console.snapshot()), "rosy_02")["yielding"] is None


def test_the_snapshot_says_who_is_yielding_and_for_whom():
    """화면이 말하지 못하면 운영자는 로봇이 왜 엉뚱한 데로 갔는지 알 수 없다."""
    left, right, console = _corridor()
    run(console.goal("rosy_01", 2.2, 0.6))

    row = _row(run(console.snapshot()), "rosy_02")

    assert row["yielding"]["for"] == "rosy_01"
    assert row["yielding"]["bay"]["y"] > 1.0
    waiting = _row(run(console.snapshot()), "rosy_01")
    assert waiting["queued"]["reason"] == "YIELDING"


def test_the_snapshot_does_not_carry_the_stored_route_to_the_browser():
    """경로 폴리라인을 매 폴링마다 실어 보내면 스냅샷이 통째로 불어난다."""
    left, right, console = _corridor()
    run(console.goal("rosy_01", 2.2, 0.6))

    queued = _row(run(console.snapshot()), "rosy_01")["queued"]

    assert "route" not in queued and "settled_ticks" not in queued
    assert queued["reason"] == "YIELDING"         # 운영자가 볼 것은 남아 있다


def _row(snapshot, robot_id):
    return [r for r in snapshot["robots"] if r["robot_id"] == robot_id][0]
