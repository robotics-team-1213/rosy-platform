"""SWM-001~007 follow 상태머신.

시계를 주입해 테스트가 실제로 기다리지 않게 한다 — 2 Hz 상한과 스트림 단절
판정이 둘 다 시간에 걸려 있어서, sleep 으로 확인하면 느리고 잘 흔들린다.
"""

from __future__ import annotations

import math

import pytest
from core_common.capability import Capability
from core_features.navigation.manager import NavGoalSpec, NavigationError, NavigationManager
from core_features.swarm import (
    MAX_GOAL_RATE_HZ,
    ReferencePose,
    SwarmError,
    SwarmManager,
    follow_goal,
)
from core_common.protocol.schemas import (
    NavigationState,
    SwarmFollowParams,
    SwarmReferenceSource,
    SwarmRole,
    SwarmStatus,
)
from core_features.safety.manager import SafetyManager, SpeedLimits, BatteryPolicy
from core_features.state.manager import StateManager


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeEvents:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict]] = []

    def publish(self, type_, severity="info", source="", data=None):
        self.published.append((type_, data or {}))

    def types(self) -> list[str]:
        return [type_ for type_, _ in self.published]


class FakeNav:
    """SwarmManager 가 실제로 쓰는 것만. 세션 토큰 규약도 그대로 지킨다 —
    지키지 않는 double 은 취소 뒤 목표 누수를 잡아낼 수 없다."""

    def __init__(self) -> None:
        self.goals: list[NavGoalSpec] = []
        self.cancels: list[str] = []
        self.closed: list[bool] = []
        self._session = None
        self._counter = 0
        # NavigationManager 가 선언하는 것과 같은 이름. double 이
        # 계약의 일부만 들고 있으면 그 부분은 더 이상 테스트되지 않는다.
        self.mapping_active = False

    def open_moving_session(self) -> int:
        self._counter += 1
        self._session = self._counter
        return self._session

    def moving_goal(self, spec, source="swarm", session=None):
        if session is not None and session != self._session:
            return False
        self.goals.append(spec)
        return True

    def cancel(self, source="api", close_session=True, session=None):
        if session is not None and session != self._session:
            return
        self.cancels.append(source)
        self.closed.append(close_session)
        if close_session:
            self._session = None


class FakeExecutor:
    def __init__(self) -> None:
        self.sent: list[NavGoalSpec] = []
        self.cancelled = 0

    def send_goal(self, spec):
        self.sent.append(spec)

    def cancel_goal(self):
        self.cancelled += 1

    def send_initial_pose(self, x, y, yaw):
        pass

    def save_map(self, name):
        return "map"


CAPABLE = Capability({"swarm": {"follow": True, "lead": True}})
INCAPABLE = Capability({"swarm": {"follow": False, "lead": False}})


def build(capability=CAPABLE):
    clock = FakeClock()
    events = FakeEvents()
    state = StateManager(robot_id="rosy_01")
    nav = FakeNav()
    safety = SafetyManager(SpeedLimits(), BatteryPolicy(), events)
    manager = SwarmManager(events, state, nav, safety, capability, clock=clock,
                           map_id_provider=lambda: state.map_id)
    return manager, clock, events, state, nav, safety


def params(**overrides) -> SwarmFollowParams:
    body = {"target_robot_id": "rosy_02", "distance": 0.5, "lateral": 0.0}
    body.update(overrides)
    return SwarmFollowParams(**body)


# --- 대형 기하 -----------------------------------------------------------------


def test_the_goal_sits_behind_the_leader_in_the_leader_frame():
    """리더가 +y 를 보고 있으면 0.5 m 뒤는 -y 쪽이다. 맵 축이 아니라 heading 기준."""
    goal = follow_goal(ReferencePose("rosy_02", 0.0, 0.0, math.pi / 2), 0.5, 0.0)

    assert goal.x == pytest.approx(0.0, abs=1e-9)
    assert goal.y == pytest.approx(-0.5)
    assert goal.yaw == pytest.approx(math.pi / 2)


def test_a_positive_lateral_offset_puts_the_follower_on_the_leader_left():
    goal = follow_goal(ReferencePose("rosy_02", 0.0, 0.0, math.pi / 2), 0.0, 0.3)

    assert goal.x == pytest.approx(-0.3)
    assert goal.y == pytest.approx(0.0, abs=1e-9)


def test_the_formation_holds_when_the_leader_turns():
    """같은 대형이면 리더 기준 상대 위치는 회전과 무관하게 같아야 한다."""
    for yaw in (0.0, 0.7, math.pi, -2.1):
        goal = follow_goal(ReferencePose("rosy_02", 3.0, -1.0, yaw), 0.5, 0.25)
        dx, dy = goal.x - 3.0, goal.y + 1.0
        forward = dx * math.cos(yaw) + dy * math.sin(yaw)
        left = -dx * math.sin(yaw) + dy * math.cos(yaw)
        assert forward == pytest.approx(-0.5)
        assert left == pytest.approx(0.25)


# --- follow 게이트 --------------------------------------------------------------


def test_a_robot_without_the_capability_refuses_to_follow():
    manager, *_ = build(INCAPABLE)

    with pytest.raises(SwarmError) as raised:
        manager.follow(params())

    assert raised.value.code == "CAPABILITY_NOT_SUPPORTED"
    assert manager.active is False


def test_follow_refuses_while_the_estop_is_engaged():
    manager, _clock, _events, _state, _nav, safety = build()
    safety.trigger_estop("test")

    with pytest.raises(SwarmError) as raised:
        manager.follow(params())

    assert raised.value.code == "EMERGENCY_ACTIVE"


def test_follow_refuses_a_max_speed_above_the_profile_ceiling():
    """SAF-004 상한은 군집 파라미터로 넘길 수 없다."""
    manager, _clock, _events, _state, _nav, safety = build()
    ceiling = safety.limits.max_linear

    with pytest.raises(SwarmError) as raised:
        manager.follow(params(max_speed=ceiling + 0.01))
    assert raised.value.code == "VALIDATION_ERROR"

    assert manager.follow(params(max_speed=ceiling)).active is True


@pytest.mark.parametrize("bad", [
    {"distance": 0.0}, {"distance": -1.0}, {"distance": float("inf")},
    {"lateral": float("nan")}, {"stream_timeout_ms": 0}, {"max_speed": 0.0},
])
def test_follow_refuses_parameters_that_cannot_describe_a_formation(bad):
    manager, *_ = build()

    with pytest.raises(SwarmError) as raised:
        manager.follow(params(**bad))
    assert raised.value.code == "VALIDATION_ERROR"


def test_the_reserved_peer_source_is_refused_rather_than_pretended():
    """SWM-007 의 peer 는 계약에만 있고 릴레이가 없다. 200 을 돌려주면 거짓말이다."""
    manager, *_ = build()

    with pytest.raises(SwarmError) as raised:
        manager.follow(params(source=SwarmReferenceSource.PEER))
    assert raised.value.code == "CAPABILITY_NOT_SUPPORTED"


def test_follow_announces_the_role_and_shows_it_in_the_snapshot():
    manager, _clock, events, state, _nav, _safety = build()

    status = manager.follow(params())

    assert status.role is SwarmRole.FOLLOWER and status.active is True
    assert state.snapshot().swarm.role is SwarmRole.FOLLOWER
    assert "swarm.role_assigned" in events.types()


def test_cancel_stops_the_goal_clears_the_role_and_announces_it():
    manager, _clock, events, state, nav, _safety = build()
    manager.follow(params())

    manager.cancel()

    assert manager.active is False
    assert nav.cancels == ["swarm"]
    assert state.snapshot().swarm == SwarmStatus()
    assert "swarm.aborted" in events.types()


def test_cancel_without_an_active_follow_is_silent():
    manager, _clock, events, _state, nav, _safety = build()

    manager.cancel()

    assert nav.cancels == []
    assert "swarm.aborted" not in events.types()


# --- 참조 스트림 ---------------------------------------------------------------


def test_a_pose_from_another_robot_is_ignored():
    manager, _clock, _events, _state, nav, _safety = build()
    manager.follow(params(target_robot_id="rosy_02"))

    assert manager.on_reference_pose(ReferencePose("rosy_09", 1.0, 1.0, 0.0)) is False
    assert nav.goals == []


def test_a_pose_arriving_before_a_follow_command_is_ignored():
    manager, _clock, _events, _state, nav, _safety = build()

    assert manager.on_reference_pose(ReferencePose("rosy_02", 1.0, 1.0, 0.0)) is False
    assert nav.goals == []


def test_goal_updates_are_capped_at_two_hertz():
    """SWM-002: 10 Hz 스트림을 그대로 흘리면 Nav2 플래너가 계속 재시작한다."""
    manager, clock, _events, _state, nav, _safety = build()
    manager.follow(params())

    assert manager.on_reference_pose(ReferencePose("rosy_02", 1.0, 0.0, 0.0)) is True
    clock.advance(0.1)
    assert manager.on_reference_pose(ReferencePose("rosy_02", 1.1, 0.0, 0.0)) is False

    assert len(nav.goals) == 1
    assert 1.0 / MAX_GOAL_RATE_HZ == pytest.approx(0.5)


def test_a_sample_held_back_by_the_rate_cap_is_issued_by_the_next_tick():
    """버리면 리더의 최신 위치를 잃는다. 들고 있다가 창이 열리면 낸다."""
    manager, clock, _events, _state, nav, _safety = build()
    manager.follow(params())
    manager.on_reference_pose(ReferencePose("rosy_02", 1.0, 0.0, 0.0))
    clock.advance(0.1)
    manager.on_reference_pose(ReferencePose("rosy_02", 2.0, 0.0, 0.0))

    clock.advance(0.45)
    manager.tick()

    assert len(nav.goals) == 2
    assert nav.goals[-1].x == pytest.approx(1.5)  # 2.0 - distance 0.5


# --- SWM-004 단절 정책 ----------------------------------------------------------


def test_losing_the_stream_holds_position_without_ending_the_follow():
    manager, clock, events, state, nav, _safety = build()
    manager.follow(params(stream_timeout_ms=1000))
    manager.on_reference_pose(ReferencePose("rosy_02", 1.0, 0.0, 0.0))

    clock.advance(1.0)
    manager.tick()

    assert nav.cancels == ["swarm"], "the goal is withdrawn"
    assert manager.active is True, "the follow assignment survives"
    assert manager.holding is True
    assert "swarm.hold" in events.types()
    assert state.snapshot().swarm.active is True


def test_the_hold_is_announced_once_not_on_every_tick():
    manager, clock, events, _state, nav, _safety = build()
    manager.follow(params(stream_timeout_ms=1000))
    manager.on_reference_pose(ReferencePose("rosy_02", 1.0, 0.0, 0.0))

    clock.advance(1.0)
    manager.tick()
    clock.advance(1.0)
    manager.tick()

    assert events.types().count("swarm.hold") == 1
    assert nav.cancels == ["swarm"]


def test_a_returning_stream_resumes_following_without_a_new_follow_command():
    manager, clock, _events, _state, nav, _safety = build()
    manager.follow(params(stream_timeout_ms=1000))
    manager.on_reference_pose(ReferencePose("rosy_02", 1.0, 0.0, 0.0))
    clock.advance(1.0)
    manager.tick()
    assert manager.holding is True

    clock.advance(0.1)
    assert manager.on_reference_pose(ReferencePose("rosy_02", 3.0, 0.0, 0.0)) is True

    assert manager.holding is False
    assert nav.goals[-1].x == pytest.approx(2.5)


def test_tick_before_the_first_sample_does_not_hold():
    """follow 직후에는 아직 받은 표본이 없다. 그것을 단절로 읽으면 안 된다."""
    manager, clock, events, _state, nav, _safety = build()
    manager.follow(params(stream_timeout_ms=1000))

    clock.advance(60.0)
    manager.tick()

    assert manager.holding is False
    assert nav.cancels == []
    assert "swarm.hold" not in events.types()


def test_tick_without_a_follow_does_nothing():
    manager, _clock, events, _state, nav, _safety = build()

    manager.tick()

    assert nav.cancels == [] and nav.goals == [] and events.types() == []


def test_state_payload_reports_the_target_and_the_stream_age():
    manager, clock, _events, _state, _nav, _safety = build()
    manager.follow(params(target_robot_id="rosy_07"))
    manager.on_reference_pose(ReferencePose("rosy_07", 1.0, 0.0, 0.0))
    clock.advance(0.25)

    body = manager.state_payload()

    assert body["target_robot_id"] == "rosy_07"
    assert body["role"] == "follower" and body["active"] is True
    assert body["source"] == "fleet"
    assert body["stream_age_s"] == pytest.approx(0.25)


def test_the_follow_path_does_not_know_where_the_stream_comes_from():
    """SWM-007: 소스 교체가 추종 로직에 영향을 주면 안 된다.

    주석이 아니라 import 그래프를 본다. 이 모듈이 전송 계층을 하나라도
    import 하는 순간 "소스를 묻지 않는다"는 성질은 말뿐이 된다.
    """
    import ast
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "core_features" / "core_features"
              / "swarm" / "manager.py").read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    transports = ("fastapi", "starlette", "websockets", "httpx", "socket",
                  "core.fleet_agent", "core.api")
    assert not [name for name in imported
                if any(name == t or name.startswith(t + ".") for t in transports)]
    assert not [name for name in imported if name.startswith("rclpy")]


# --- NavigationManager.moving_goal ---------------------------------------------


def nav_manager(events):
    class Waypoints:
        def get(self, name):
            raise KeyError(name)

    safety = SafetyManager(SpeedLimits(), BatteryPolicy(), events)
    manager = NavigationManager(events, StateManager(robot_id="rosy_01"),
                                Waypoints(), safety)
    manager.executor = FakeExecutor()
    return manager, safety


def test_moving_goal_replaces_a_goal_while_navigating():
    """goal() 은 NAVIGATION_ACTIVE 로 막는다. 추종은 그것이 정상 동작이다."""
    events = FakeEvents()
    manager, _safety = nav_manager(events)
    manager.goal(NavGoalSpec(1.0, 0.0, 0.0))
    manager.on_goal_accepted()
    assert manager.nav_state is NavigationState.NAVIGATING

    with pytest.raises(NavigationError) as raised:
        manager.goal(NavGoalSpec(2.0, 0.0, 0.0))
    assert raised.value.code == "NAVIGATION_ACTIVE"

    manager.moving_goal(NavGoalSpec(2.0, 0.0, 0.0))

    assert manager.executor.sent[-1].x == pytest.approx(2.0)
    assert manager.nav_state is NavigationState.NAVIGATING


def test_moving_goal_does_not_cancel_before_sending():
    """취소를 먼저 보내면 그 사이에 로봇이 멈춰 선다. Nav2 는 선점을 지원한다."""
    events = FakeEvents()
    manager, _safety = nav_manager(events)
    manager.goal(NavGoalSpec(1.0, 0.0, 0.0))
    manager.on_goal_accepted()

    manager.moving_goal(NavGoalSpec(2.0, 0.0, 0.0))

    assert manager.executor.cancelled == 0


def test_moving_goal_announces_the_start_only_when_it_starts():
    events = FakeEvents()
    manager, _safety = nav_manager(events)

    manager.moving_goal(NavGoalSpec(1.0, 0.0, 0.0))
    manager.on_goal_accepted()
    manager.moving_goal(NavGoalSpec(2.0, 0.0, 0.0))

    assert events.types().count("nav.started") == 1


def test_moving_goal_still_refuses_on_estop_and_while_mapping():
    events = FakeEvents()
    manager, safety = nav_manager(events)
    safety.trigger_estop("test")

    with pytest.raises(NavigationError) as raised:
        manager.moving_goal(NavGoalSpec(1.0, 0.0, 0.0))
    assert raised.value.code == "EMERGENCY_ACTIVE"

    safety.release("test")
    manager.mapping_active = True
    with pytest.raises(NavigationError) as raised:
        manager.moving_goal(NavGoalSpec(1.0, 0.0, 0.0))
    assert raised.value.code == "MAPPING_ACTIVE"
