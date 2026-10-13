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
    return {"robot_id": robot_id, "navigation": "NAVIGATING",
            "localization": {"state": "LOCALIZED", "pose_frame": "map"}}


def _arrived(robot_id):
    return {"robot_id": robot_id, "navigation": "ARRIVED",
            "localization": {"state": "LOCALIZED", "pose_frame": "map"}}


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


# --- D-395 P2-2: untrusted poses ---------------------------------------------------------


def _loc(state="LOCALIZED", frame="map"):
    return {"state": state, "pose_frame": frame}


def _standing(robot_id, xy, localization=...):
    state = {"robot_id": robot_id, "navigation": "IDLE",
             "pose": {"x": xy[0], "y": xy[1], "yaw": 0.0}}
    if localization is not ...:
        state["localization"] = localization
    return state


def _mover():
    mover = FakeRobot("rosy_01", state=_standing("rosy_01", (-2.0, 0.0), _loc()))
    mover._path = _line(-2.0, 0, 2.0, 0)
    return mover


def _goal_calls(robot):
    return sum(1 for c in robot.calls if c[0] == "navigation_goal")


def test_an_untrusted_robot_is_a_wide_obstacle_at_its_last_trusted_pose():
    """D-395 §10: a robot that lost LOCALIZED keeps 0.45 m clear around where it was last trusted.
    Its current odom pose (far away here) is not used."""
    mover = _mover()
    other = FakeRobot("rosy_02", state=_standing("rosy_02", (0.0, 0.3), _loc()))
    console = _console(mover, other)
    run(console.snapshot())                                       # last trusted pose (0, 0.3)
    other._state = _standing("rosy_02", (5.0, 5.0), _loc("CANDIDATES", "odom"))

    result = run(console.goal("rosy_01", 2.0, 0.0))

    assert result["queued"] is True
    assert result["reason"] == "LOCALIZATION_UNTRUSTED" and result["blocked_by"] == "rosy_02"
    assert ("navigation_cancel",) in mover.calls
    assert _goal_calls(other) == 0                                # never sent anywhere


def test_the_mission_goes_out_once_the_robot_is_localized_off_the_route():
    mover = _mover()
    other = FakeRobot("rosy_02", state=_standing("rosy_02", (0.0, 0.3), _loc()))
    console = _console(mover, other)
    run(console.snapshot())
    other._state = _standing("rosy_02", (0.0, 0.3), _loc("SUSPECT", "map"))
    run(console.goal("rosy_01", 2.0, 0.0))
    run(console.snapshot())
    assert _goal_calls(mover) == 1                                # still waiting

    other._state = _standing("rosy_02", (1.0, 1.5), _loc())
    run(console.snapshot())

    assert _goal_calls(mover) == 2
    assert "rosy_01" not in console._queued


def test_an_untrusted_robot_far_from_the_route_does_not_block():
    mover = _mover()
    other = FakeRobot("rosy_02", state=_standing("rosy_02", (0.0, 0.6), _loc()))
    console = _console(mover, other)
    run(console.snapshot())
    other._state = _standing("rosy_02", (0.0, 0.0), _loc("CANDIDATES", "odom"))   # odom says on-route

    result = run(console.goal("rosy_01", 2.0, 0.0))

    assert "queued" not in result


def test_an_untrusted_robot_never_trusted_blocks_the_whole_track():
    mover = _mover()
    other = FakeRobot("rosy_02", state=_standing("rosy_02", (9.0, 9.0), _loc("UNKNOWN", "odom")))
    console = _console(mover, other)
    run(console.snapshot())

    result = run(console.goal("rosy_01", 2.0, 0.0))

    assert result["reason"] == "LOCALIZATION_UNTRUSTED" and result["blocked_by"] == "rosy_02"


def test_a_robot_without_localization_blocks_without_inventing_a_map_pose():
    """Missing localization cannot establish a map pose."""
    mover = _mover()
    other = FakeRobot("rosy_02", state=_standing("rosy_02", (0.0, 0.3)))
    console = _console(mover, other)
    snapshot = run(console.snapshot())

    result = run(console.goal("rosy_01", 2.0, 0.0))

    assert result["reason"] == "LOCALIZATION_UNTRUSTED" and result["blocked_by"] == "rosy_02"
    row = [r for r in snapshot["robots"] if r["robot_id"] == "rosy_02"][0]
    assert row["localization"]["legacy"] is False and row["localization"]["trusted"] is False
    assert row["localization"]["label"] == "위치 모름"


def test_a_mission_held_behind_an_untrusted_robot_drops_its_claim():
    """Review fix: like ROUTE_CONFLICT, a cancelled mission must not keep claiming the corridor."""
    mover = _mover()
    other = FakeRobot("rosy_02", state=_standing("rosy_02", (0.0, 0.3), _loc()))
    console = _console(mover, other)
    run(console.snapshot())
    console._claims["rosy_01"] = _line(-2.0, 0, 2.0, 0)        # an earlier mission's claim
    other._state = _standing("rosy_02", (0.0, 0.3), _loc("SUSPECT", "map"))

    result = run(console.goal("rosy_01", 2.0, 0.0))

    assert result["reason"] == "LOCALIZATION_UNTRUSTED"
    assert "rosy_01" not in console._claims


def test_an_untrusted_mover_is_queued_without_sending_the_goal():
    """Decision (review of lane C): CORE would refuse a goal from an unlocalized robot anyway."""
    mover = _mover()
    mover._state = _standing("rosy_01", (-2.0, 0.0), _loc("CANDIDATES", "odom"))
    console = _console(mover)
    run(console.snapshot())

    result = run(console.goal("rosy_01", 2.0, 0.0))

    assert result["queued"] is True and result["dispatch_attempted"] is False
    assert result["reason"] == "LOCALIZATION_UNTRUSTED" and result["blocked_by"] == "rosy_01"
    assert _goal_calls(mover) == 0
    run(console.snapshot())
    assert _goal_calls(mover) == 0                                 # still unlocalized: waits

    mover._state = _standing("rosy_01", (-2.0, 0.0), _loc())
    run(console.snapshot())
    assert _goal_calls(mover) == 1 and "rosy_01" not in console._queued


def test_a_mover_without_localization_is_queued_without_dispatch():
    mover = _mover()
    mover._state = _standing("rosy_01", (-2.0, 0.0))
    console = _console(mover)
    run(console.snapshot())
    result = run(console.goal("rosy_01", 2.0, 0.0))
    assert result["reason"] == "LOCALIZATION_UNTRUSTED" and result["dispatch_attempted"] is False
    assert _goal_calls(mover) == 0


def test_a_goal_reads_localization_before_dispatch_even_without_a_snapshot():
    mover = _mover()
    console = _console(mover)
    assert "queued" not in run(console.goal("rosy_01", 2.0, 0.0))
    mover._state["localization"] = None
    result = run(console.goal("rosy_01", 3.0, 0.0))
    assert result["reason"] == "LOCALIZATION_UNTRUSTED"
    assert result["dispatch_attempted"] is False
    assert _goal_calls(mover) == 1


# --- D-395 S2 Finding 1: a legacy-null pose is never a trusted pose ------------------------


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _clocked(*robots: FakeRobot):
    clock = _Clock()
    endpoints = [RobotEndpoint(robot_id=r.robot_id, base_url=f"http://127.0.0.1:808{i}",
                               token="t") for i, r in enumerate(robots)]
    return FleetConsole(endpoints, list(robots), clock=clock), clock


def test_s2_null_at_power_on_then_candidates_blocks_the_whole_track():
    """S2 q0: Fleet read r4 before loc_assist was up (`localization: null`, power-on odom pose far
    off the route), then r4 reported CANDIDATES. It was never LOCALIZED, so it has no trusted
    pose and must block the whole track; the other robot's goal stays queued."""
    mover = _mover()
    other = FakeRobot("rosy_02", state=_standing("rosy_02", (9.0, 9.0), None))
    console = _console(mover, other)
    run(console.snapshot())                                       # missing localization: pose never trusted
    other._state = _standing("rosy_02", (9.0, 9.0), _loc("CANDIDATES", "odom"))
    run(console.snapshot())

    result = run(console.goal("rosy_01", 2.0, 0.0))

    assert result["reason"] == "LOCALIZATION_UNTRUSTED" and result["blocked_by"] == "rosy_02"
    assert "rosy_02" not in console._trusted
    sent = _goal_calls(mover)
    run(console.snapshot())
    run(console.snapshot())
    assert _goal_calls(mover) == sent and "rosy_01" in console._queued


def test_null_then_localized_map_gives_the_localized_pose_as_trusted():
    mover = _mover()
    other = FakeRobot("rosy_02", state=_standing("rosy_02", (9.0, 9.0), None))
    console = _console(mover, other)
    run(console.snapshot())
    other._state = _standing("rosy_02", (1.0, 1.5), _loc())
    run(console.snapshot())

    assert console._trusted["rosy_02"] == (1.0, 1.5)
    assert "queued" not in run(console.goal("rosy_01", 2.0, 0.0))


def test_null_localized_then_candidates_keeps_out_around_the_localized_pose():
    mover = _mover()
    other = FakeRobot("rosy_02", state=_standing("rosy_02", (0.0, 1.5), None))   # odom: off-route
    console = _console(mover, other)
    run(console.snapshot())
    other._state = _standing("rosy_02", (0.0, 0.3), _loc())                       # on the route
    run(console.snapshot())
    other._state = _standing("rosy_02", (0.0, 1.5), _loc("CANDIDATES", "odom"))
    run(console.snapshot())

    result = run(console.goal("rosy_01", 2.0, 0.0))

    assert result["reason"] == "LOCALIZATION_UNTRUSTED" and result["blocked_by"] == "rosy_02"
    assert console._trusted["rosy_02"] == (0.0, 0.3)


def test_null_localization_stays_untrusted_after_cached_position_expires():
    """A CORE restart never restores trust by timeout; the old position expires after 30 s."""
    mover = _mover()
    other = FakeRobot("rosy_02", state=_standing("rosy_02", (0.0, 0.3), _loc()))
    console, clock = _clocked(mover, other)
    run(console.snapshot())
    other._state = _standing("rosy_02", (5.0, 5.0), None)                      # CORE restarted
    snapshot = run(console.snapshot())
    row = [r for r in snapshot["robots"] if r["robot_id"] == "rosy_02"][0]
    assert row["localization"]["legacy"] is False and row["localization"]["trusted"] is False

    clock.now = 29.0
    result = run(console.goal("rosy_01", 2.0, 0.0))
    assert result["reason"] == "LOCALIZATION_UNTRUSTED" and result["blocked_by"] == "rosy_02"

    clock.now = 30.0
    snapshot = run(console.snapshot())                       # null for 30 s: cached position expires
    row = [r for r in snapshot["robots"] if r["robot_id"] == "rosy_02"][0]
    assert row["localization"]["legacy"] is False and row["localization"]["trusted"] is False
    assert "rosy_01" in console._queued
    assert "rosy_02" not in console._trusted                 # the stale trusted pose is dropped


def test_a_d395_robot_back_from_null_reporting_resets_the_grace():
    mover = _mover()
    other = FakeRobot("rosy_02", state=_standing("rosy_02", (0.0, 0.3), _loc()))
    console, clock = _clocked(mover, other)
    run(console.snapshot())
    other._state = _standing("rosy_02", (0.0, 0.3), None)
    run(console.snapshot())                                   # null since t=0
    clock.now = 20.0
    other._state = _standing("rosy_02", (0.0, 0.3), _loc("UNKNOWN", "odom"))
    run(console.snapshot())
    other._state = _standing("rosy_02", (0.0, 0.3), None)
    clock.now = 25.0
    run(console.snapshot())                                   # null again since t=25
    clock.now = 40.0

    result = run(console.goal("rosy_01", 2.0, 0.0))

    assert result["reason"] == "LOCALIZATION_UNTRUSTED"


def test_missing_localization_never_becomes_trusted_by_timeout():
    mover = _mover()
    other = FakeRobot("rosy_02", state=_standing("rosy_02", (0.0, 0.3), None))
    console, clock = _clocked(mover, other)
    for t in (0.0, 10.0, 40.0):
        clock.now = t
        snapshot = run(console.snapshot())
        row = [r for r in snapshot["robots"] if r["robot_id"] == "rosy_02"][0]
        assert row["localization"]["legacy"] is False and row["localization"]["trusted"] is False

    assert run(console.goal("rosy_01", 2.0, 0.0))["reason"] == "LOCALIZATION_UNTRUSTED"
    assert "rosy_02" not in console._trusted


# --- D-395 P2-7: traffic holds before a localization mission -------------------------------


def _driving(console, robot):
    """A Fleet goal under way along y = 0 (set directly: dispatch rules are tested above)."""
    console._goals[robot.robot_id] = {"x": 2.0, "y": 0.0, "yaw": 0.0}
    console._claims[robot.robot_id] = _line(-2.0, 0, 2.0, 0)
    robot._state = {**robot._state, "navigation": "NAVIGATING"}


def test_a_driving_robot_near_the_mover_is_held_until_the_mover_is_localized():
    mover = FakeRobot("rosy_02", state=_standing("rosy_02", (0.0, 0.3), _loc()))
    driver = _mover()                                               # rosy_01 on y = 0
    console = _console(driver, mover)
    run(console.snapshot())                                         # mover last trusted at (0, 0.3)
    _driving(console, driver)
    mover._state = _standing("rosy_02", (0.0, 0.3), _loc("CANDIDATES", "odom"))
    run(console.snapshot())

    held = run(console.hold_for_localization("rosy_02"))

    assert held == ["rosy_01"]
    assert ("navigation_cancel",) in driver.calls
    assert console._queued["rosy_01"]["reason"] == "LOCALIZATION_UNTRUSTED"
    assert console._queued["rosy_01"]["blocked_by"] == "rosy_02"
    run(console.snapshot())
    assert _goal_calls(driver) == 0                                 # still held

    mover._state = _standing("rosy_02", (0.0, 1.5), _loc())        # localized, off the route
    run(console.snapshot())
    assert _goal_calls(driver) == 1 and "rosy_01" not in console._queued


def test_a_driving_robot_far_from_the_mover_keeps_going():
    mover = FakeRobot("rosy_02", state=_standing("rosy_02", (0.0, 1.5), _loc()))
    driver = _mover()
    console = _console(driver, mover)
    run(console.snapshot())
    _driving(console, driver)
    mover._state = _standing("rosy_02", (0.0, 1.5), _loc("CANDIDATES", "odom"))
    run(console.snapshot())

    assert run(console.hold_for_localization("rosy_02")) == []
    assert ("navigation_cancel",) not in driver.calls


def test_a_mover_never_trusted_holds_every_driving_robot():
    mover = FakeRobot("rosy_02", state=_standing("rosy_02", (9.0, 9.0), _loc("UNKNOWN", "odom")))
    driver = FakeRobot("rosy_01", state=_standing("rosy_01", (-2.0, 0.0)))   # legacy driver
    driver._path = _line(-2.0, 0, 2.0, 0)
    console = _console(driver, mover)
    run(console.snapshot())
    console._goals["rosy_01"] = {"x": 2.0, "y": 0.0, "yaw": 0.0}
    console._claims["rosy_01"] = _line(-2.0, 0, 2.0, 0)

    assert run(console.hold_for_localization("rosy_02")) == ["rosy_01"]


def test_an_unconfirmed_cancel_fails_the_hold():
    mover = FakeRobot("rosy_02", state=_standing("rosy_02", (0.0, 0.3), _loc("UNKNOWN", "odom")))
    driver = _mover()
    console = _console(driver, mover)
    run(console.snapshot())
    console._goals["rosy_01"] = {"x": 2.0, "y": 0.0, "yaw": 0.0}

    async def ambiguous_cancel():
        return {"navigation": "IDLE"}

    driver.navigation_cancel = ambiguous_cancel
    with pytest.raises(RuntimeError, match="cancellation"):
        run(console.hold_for_localization("rosy_02"))


def test_a_formation_near_the_mover_is_stopped():
    from types import SimpleNamespace
    mover = FakeRobot("rosy_02", state=_standing("rosy_02", (0.0, 0.3), _loc("UNKNOWN", "odom")))
    leader = _mover()
    console = _console(leader, mover)
    run(console.snapshot())
    console._formation = SimpleNamespace(state="RUNNING", assignment={"rosy_03": "slot"},
                                         follower_ids=frozenset({"rosy_03"}))
    console._formation_leader = "rosy_01"
    stopped = []

    async def formation_stop():
        stopped.append(True)
        return {"active": False}

    console.formation_stop = formation_stop
    assert run(console.hold_for_localization("rosy_02")) == ["formation"]
    assert stopped == [True]


def test_a_yield_whose_way_to_its_bay_crosses_the_mover_is_cancelled():
    mover = FakeRobot("rosy_02", state=_standing("rosy_02", (0.0, 0.3), _loc()))
    yielder = FakeRobot("rosy_03", state=_standing("rosy_03", (-1.0, 0.3), _loc()))
    far = FakeRobot("rosy_04", state=_standing("rosy_04", (3.0, 3.0), _loc()))
    console = _console(mover, yielder, far)
    run(console.snapshot())                                       # mover last trusted (0, 0.3)
    mover._state = _standing("rosy_02", (0.0, 0.3), _loc("CANDIDATES", "odom"))
    run(console.snapshot())
    console._yielding["rosy_03"] = {"bay": {"x": 1.0, "y": 0.3}, "for": "rosy_01"}
    console._yielding["rosy_04"] = {"bay": {"x": 3.0, "y": 4.0}, "for": "rosy_01"}

    assert run(console.hold_for_localization("rosy_02")) == ["rosy_03"]
    assert ("navigation_cancel",) in yielder.calls and "rosy_03" not in console._yielding
    assert ("navigation_cancel",) not in far.calls and "rosy_04" in console._yielding
