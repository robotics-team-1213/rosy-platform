"""관제 화면의 대형 조작 — 무장·변경·재개·해제, 그리고 대형과 개별 미션의 경계."""

from __future__ import annotations

import pytest

from fakes import FakeRelay, FakeRobot, run
from fleet.hub.hub import HubError
from fleet.server.console import FleetConsole
from fleet.swarm.robots import RobotEndpoint


def _console(*robots: FakeRobot) -> FleetConsole:
    endpoints = [RobotEndpoint(robot_id=r.robot_id, base_url=f"http://127.0.0.1:808{i}",
                               token="t") for i, r in enumerate(robots)]
    return FleetConsole(endpoints, list(robots),
                        relay_factory=lambda leader, followers, **kw: FakeRelay(leader, followers))


def _fleet(n: int = 2):
    robots = []
    for i in range(1, n + 1):
        robot = FakeRobot(f"rosy_{i:02d}",
                          state={"robot_id": f"rosy_{i:02d}", "navigation": "IDLE",
                                 "map_id": "m1", "pose": {"x": float(i), "y": 0.0, "yaw": 0.0}})
        robots.append(robot)
    return robots


def test_arming_reports_the_slots_each_follower_was_given():
    """어느 로봇이 어느 자리인지 화면이 말하지 못하면 운영자는 대형이 섰는지 알 수 없다."""
    robots = _fleet(2)
    console = _console(*robots)

    status = run(console.formation_start("rosy_01", "COLUMN", 0.6))

    assert status["active"] and status["state"] == "RUNNING"
    assert status["leader"] == "rosy_01"
    assert "rosy_02" in status["assignment"]
    assert status["relay"]["paused"] is False


def test_a_dead_leader_is_replaced_by_the_next_living_robot():
    """관제가 명단 순서의 다음 생존자로 대형을 다시 연다. 팔로워는 다른 리더를 안 뽑는다."""
    robots = _fleet(3)
    console = _console(*robots)
    run(console.formation_start("rosy_01", "COLUMN", 0.6))
    robots[0].state_error = ConnectionError("leader down")

    run(console.snapshot())

    status = console.formation_status()
    assert status["active"] is True
    assert status["leader"] == "rosy_02"
    assert set(status["assignment"]) == {"rosy_03"}
    assert any(call[0] == "swarm_cancel" for call in robots[1].calls)
    assert any(call[0] == "follow" for call in robots[2].calls)
    assert not any(call[0] == "follow" for call in robots[0].calls)


def test_a_dead_leader_with_one_survivor_ends_the_formation():
    robots = _fleet(2)
    console = _console(*robots)
    run(console.formation_start("rosy_01"))
    robots[0].state_error = ConnectionError("leader down")

    run(console.snapshot())

    assert console.formation_status()["active"] is False
    assert any(call[0] == "swarm_cancel" for call in robots[1].calls)


def test_a_second_formation_is_refused_instead_of_replacing_the_first():
    """조용히 갈아치우면 앞 세션의 팔로워가 무장된 채 남아, 아무도 안 보내는 참조를 기다린다."""
    console = _console(*_fleet(2))
    run(console.formation_start("rosy_01"))

    with pytest.raises(HubError) as raised:
        run(console.formation_start("rosy_02"))
    assert raised.value.code == "FORMATION_ACTIVE"


def test_a_formation_needs_a_follower():
    console = _console(*_fleet(1))
    with pytest.raises(HubError) as raised:
        run(console.formation_start("rosy_01"))
    assert raised.value.code == "NO_FOLLOWERS"


def test_an_unknown_formation_name_is_refused_before_any_robot_is_touched():
    robots = _fleet(2)
    console = _console(*robots)
    with pytest.raises(HubError) as raised:
        run(console.formation_start("rosy_01", "ZIGZAG"))
    assert raised.value.code == "UNKNOWN_FORMATION"
    assert not [c for c in robots[1].calls if c[0] == "follow"]


def test_a_follower_in_a_formation_refuses_a_separate_goal():
    """팔로워는 리더 pose 를 따라간다. 목표를 따로 내리면 로봇 안에서 두 임자가 다툰다."""
    robots = _fleet(2)
    console = _console(*robots)
    run(console.formation_start("rosy_01"))

    with pytest.raises(HubError) as raised:
        run(console.goal("rosy_02", 1.0, 1.0))
    assert raised.value.code == "FORMATION_ACTIVE"
    assert not [c for c in robots[1].calls if c[0] == "navigation_goal"]


def test_stopping_the_formation_gives_the_robots_back():
    robots = _fleet(2)
    console = _console(*robots)
    run(console.formation_start("rosy_01"))

    status = run(console.formation_stop())

    assert status["active"] is False and status["state"] == "STOPPED"
    assert ("swarm_cancel",) in robots[1].calls
    run(console.goal("rosy_02", 1.0, 1.0))      # 이제 개별 미션이 나간다
    assert [c for c in robots[1].calls if c[0] == "navigation_goal"]


def test_stopping_when_nothing_is_running_is_not_an_error():
    """대형을 못 푸는 화면은 대형을 여는 화면보다 나쁘다."""
    console = _console(*_fleet(2))
    assert run(console.formation_stop())["active"] is False


def test_resume_is_refused_while_the_session_is_not_holding():
    console = _console(*_fleet(2))
    run(console.formation_start("rosy_01"))
    # RUNNING 에서의 재개는 세션이 조용히 무시한다 — 화면이 그것을 성공으로 읽으면 안 된다.
    assert run(console.formation_resume())["state"] == "RUNNING"


def test_reform_without_a_session_is_refused():
    console = _console(*_fleet(2))
    with pytest.raises(HubError) as raised:
        run(console.formation_reform("LINE"))
    assert raised.value.code == "NO_FORMATION"


def test_reform_changes_the_shape_that_the_status_reports():
    console = _console(*_fleet(3))
    run(console.formation_start("rosy_01", "COLUMN", 0.6))

    status = run(console.formation_reform("LINE", 0.8))

    assert status["formation"] == "LINE" and status["spacing"] == pytest.approx(0.8)


def test_an_estop_releases_the_formation_before_stopping_the_robots():
    """릴레이가 참조를 계속 밀어 넣는 채로 로봇만 세우면, e-stop 을 푸는 순간 달려나간다."""
    robots = _fleet(2)
    console = _console(*robots)
    run(console.formation_start("rosy_01"))

    run(console.estop_all())

    assert console.formation_status()["active"] is False
    assert ("swarm_cancel",) in robots[1].calls
    assert ("estop",) in robots[1].calls


def test_the_leader_still_takes_goals_while_the_formation_runs():
    """대형은 리더를 몰아서 움직인다. 리더가 목표를 못 받으면 무장만 된 채 아무 데도 못 간다."""
    robots = _fleet(2)
    console = _console(*robots)
    run(console.formation_start("rosy_01"))

    run(console.goal("rosy_01", 2.0, 0.0))

    assert [c for c in robots[0].calls if c[0] == "navigation_goal"]


def test_robot_selection_picks_who_joins_the_formation():
    """FOR-001 Robot Selection — N대 중 일부로 대형을 열 수 있다."""
    robots = _fleet(3)
    console = _console(*robots)
    run(console.formation_start("rosy_01", "COLUMN", 0.6, members=["rosy_01", "rosy_02"]))

    status = console.formation_status()
    assert set(status["assignment"]) == {"rosy_02"}
    # 미선택 로봇은 개별 미션을 계속 받는다 — 대형에 안 들었다고 막히면 안 된다.
    run(console.goal("rosy_03", 2.0, 2.0))
    assert [c for c in robots[2].calls if c[0] == "navigation_goal"]
    # 선택된 팔로워는 여전히 거절한다.
    with pytest.raises(HubError) as raised:
        run(console.goal("rosy_02", 1.0, 1.0))
    assert raised.value.code == "FORMATION_ACTIVE"


def test_the_leader_must_be_among_the_selected_members():
    console = _console(*_fleet(3))
    with pytest.raises(HubError) as raised:
        run(console.formation_start("rosy_01", members=["rosy_02", "rosy_03"]))
    assert raised.value.code == "LEADER_NOT_IN_MEMBERS"


def test_an_unknown_member_is_refused():
    console = _console(*_fleet(2))
    with pytest.raises(HubError) as raised:
        run(console.formation_start("rosy_01", members=["rosy_01", "rosy_99"]))
    assert raised.value.code == "UNKNOWN_ROBOT"


def test_duplicated_members_are_refused():
    console = _console(*_fleet(3))
    with pytest.raises(HubError) as raised:
        run(console.formation_start("rosy_01", members=["rosy_01", "rosy_02", "rosy_02"]))
    assert raised.value.code == "MEMBER_DUPLICATED"


def test_members_without_a_follower_is_refused():
    console = _console(*_fleet(2))
    with pytest.raises(HubError) as raised:
        run(console.formation_start("rosy_01", members=["rosy_01"]))
    assert raised.value.code == "NO_FOLLOWERS"


def test_omitting_members_keeps_the_all_robots_behaviour():
    """members 를 보내지 않으면 기존 동작(나머지 전원)이다 — 호환은 계약이다."""
    robots = _fleet(3)
    console = _console(*robots)
    run(console.formation_start("rosy_01", "COLUMN", 0.6))
    assert set(console.formation_status()["assignment"]) == {"rosy_02", "rosy_03"}


class _StreamsNeverReadyRelay(FakeRelay):
    def streams_ready(self) -> bool:
        return False


def test_start_does_not_touch_robots_until_the_streams_are_open():
    """D-132 — 스트림이 안 열리면 무장하지 않는다. 로봇 무접촉 거절이다."""
    robots = _fleet(2)
    console = _console(*robots)
    console._relay_factory = lambda leader, followers, **kw: _StreamsNeverReadyRelay(leader, followers)

    with pytest.raises(HubError) as raised:
        run(console.formation_start("rosy_01"))

    assert raised.value.code == "ARMING_FAILED"
    for robot in robots:
        assert not [c for c in robot.calls if c[0] == "follow"]
