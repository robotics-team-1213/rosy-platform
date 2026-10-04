"""추종이 실제 NavigationManager·목표 세대 관리와 만나는 지점.

기존 swarm 테스트는 전부 `FakeNav` 를 끼워 SwarmManager 만 본다. 리뷰가 잡아낸
결함 두 개(HOLD 취소가 Nav2 에 닿지 않음, NAV-006 무력화)는 정확히 그 사이 —
SwarmManager → NavigationManager → NavExecutor, 그리고 브리지가 되돌려주는
콜백 순서 — 에 살아 있었다. 여기서는 진짜 매니저를 쓰고 브리지 콜백을 재생한다.
"""

from __future__ import annotations

import math

import pytest
from core.bridge.goal_tracker import GoalTracker
from core_common.capability import Capability
from core_features.navigation.manager import NavGoalSpec, NavigationError, NavigationManager
from core_features.swarm import ReferencePose, SwarmError, SwarmManager
from core_common.protocol.schemas import NavigationState, SwarmFollowParams
from core_features.safety.manager import BatteryPolicy, SafetyManager, SpeedLimits
from core_features.state.manager import StateManager


class FakeClock:
    def __init__(self) -> None:
        self.now = 500.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeEvents:
    def __init__(self) -> None:
        self.published = []

    def publish(self, type_, severity="info", source="", data=None):
        self.published.append((type_, data or {}))

    def types(self):
        return [t for t, _ in self.published]


class FakeHandle:
    def __init__(self, accepted: bool = True) -> None:
        self.accepted = accepted
        self.cancelled = False

    def cancel_goal_async(self):
        self.cancelled = True


class BridgeExecutor:
    """브리지가 하는 일을 rclpy 없이 재생한다.

    핵심은 Nav2 의 선점 의미다: 새 목표를 받으면 이전 목표는 **abort 로**
    끝나고, 그 결과 콜백이 뒤늦게 도착한다.
    """

    def __init__(self, nav: NavigationManager) -> None:
        self._nav = nav
        self.goals: list[NavGoalSpec] = []
        self.handles: list[FakeHandle] = []
        self.tracker = GoalTracker()
        self._pending: list[tuple[int, FakeHandle]] = []

    # --- NavExecutor -----------------------------------------------------------

    def send_goal(self, spec: NavGoalSpec) -> None:
        self.goals.append(spec)
        generation = self.tracker.opening()
        self._pending.append((generation, FakeHandle()))

    def cancel_goal(self) -> None:
        for handle in self.tracker.cancel_all():
            handle.cancel_goal_async()

    def send_initial_pose(self, x, y, yaw):
        pass

    def save_map(self, name):
        return "map"

    # --- 브리지 콜백 재생 --------------------------------------------------------

    def settle(self) -> None:
        """서버가 목표를 받아들이고, 선점된 이전 목표를 abort 로 끝낸다."""
        superseded = [item for item in self._pending[:-1]]
        newest = self._pending[-1:]
        self._pending = []
        for generation, handle in superseded + newest:
            self.handles.append(handle)
            if self.tracker.accepted(generation, handle):
                self._nav.on_goal_accepted()
            else:
                handle.cancel_goal_async()
        # Nav2 는 선점된 목표를 abort 로 종료한다. 결과는 뒤늦게 도착한다.
        for generation, _handle in superseded:
            if self.tracker.finished(generation):
                self._nav.on_result(False, "PREEMPTED")

    @property
    def cancelled_handles(self) -> int:
        return sum(1 for handle in self.handles if handle.cancelled)


def build():
    clock = FakeClock()
    events = FakeEvents()
    state = StateManager(robot_id="rosy_01")
    safety = SafetyManager(SpeedLimits(), BatteryPolicy(), events)

    class Waypoints:
        def get(self, name):
            raise KeyError(name)

    nav = NavigationManager(events, state, Waypoints(), safety, stuck_timeout_s=30.0)
    executor = BridgeExecutor(nav)
    nav.executor = executor
    docking = {"active": False}
    swarm = SwarmManager(events, state, nav, safety,
                         Capability({"swarm": {"follow": True, "lead": True}}),
                         clock=clock,
                         docking_active_provider=lambda: docking["active"],
                         map_id_provider=lambda: state.map_id)
    # services.py 와 같은 배선. 세션을 닫는 모든 길이 추종자에게 닿는다.
    nav.session_closed_listener = swarm.on_navigation_session_closed
    safety.estop_listeners.append(swarm.on_estop)
    return swarm, nav, executor, clock, events, safety, docking


def params(**overrides):
    body = {"target_robot_id": "rosy_02", "distance": 0.5, "lateral": 0.0}
    body.update(overrides)
    return SwarmFollowParams(**body)


def stream(swarm, executor, clock, x, *, settle=True):
    swarm.on_reference_pose(ReferencePose("rosy_02", x, 0.0, 0.0))
    if settle:
        executor.settle()
    clock.advance(0.5)


# --- HOLD 는 실제로 Nav2 목표를 거둬야 한다 -------------------------------------


def test_a_preempted_goal_result_does_not_move_the_navigation_state():
    """선점 abort 를 현재 목표의 실패로 읽으면 상태가 FAILED 로 떨어진다."""
    swarm, nav, executor, clock, _events, _safety, _docking = build()
    swarm.follow(params())

    stream(swarm, executor, clock, 1.0)
    stream(swarm, executor, clock, 2.0)

    assert len(executor.goals) == 2
    assert nav.nav_state is NavigationState.NAVIGATING


def test_hold_cancels_the_live_nav2_goal_even_after_a_preemption():
    """리뷰가 재현한 경로: 선점 결과가 FAILED 를 만들면 cancel 이 통째로 무시됐다."""
    swarm, nav, executor, clock, events, _safety, _docking = build()
    swarm.follow(params(stream_timeout_ms=1000))

    stream(swarm, executor, clock, 1.0)
    stream(swarm, executor, clock, 2.0)

    clock.advance(1.0)
    swarm.tick()

    assert "swarm.hold" in events.types()
    assert executor.cancelled_handles >= 1, "the goal must actually be withdrawn"
    assert swarm.active is True and swarm.holding is True


def test_cancel_reaches_nav2_from_any_navigation_state():
    swarm, nav, executor, clock, _events, _safety, _docking = build()
    swarm.follow(params())
    stream(swarm, executor, clock, 1.0)
    nav.on_result(False, "ABORTED")
    assert nav.nav_state is NavigationState.FAILED

    swarm.cancel()

    assert executor.cancelled_handles >= 1


def test_a_goal_cancelled_before_acceptance_is_still_cancelled():
    """send 와 accept 사이에 취소가 오면 핸들이 아직 없다. 놓치면 안 된다."""
    swarm, nav, executor, clock, _events, _safety, _docking = build()
    swarm.follow(params())
    swarm.on_reference_pose(ReferencePose("rosy_02", 1.0, 0.0, 0.0))

    swarm.cancel()
    executor.settle()

    assert nav.nav_state is not NavigationState.NAVIGATING
    assert executor.tracker.live_count == 0


# --- NAV-006 는 추종 중에도 살아 있어야 한다 (SWM-002) ---------------------------


def test_goal_replacement_does_not_reset_the_stuck_baseline():
    """0.5 초마다 기준점을 초기화하면 30 초 무진척 조건이 성립할 수 없다.

    예전 테스트는 루프 안에서 기준시각을 직접 조작하고 첫 이벤트에서 멈춰,
    조건이 성립한다는 것만 보이고 그 뒤 무한 반복은 보지 못했다. 여기서는
    기준점 자체가 목표 교체를 견디는지만 본다.
    """
    swarm, nav, executor, clock, _events, _safety, _docking = build()
    swarm.follow(params())
    stream(swarm, executor, clock, 1.0)
    nav.on_pose_progress(0.0, 0.0)
    baseline = nav._last_progress_ts

    for step in range(5):
        swarm.on_reference_pose(ReferencePose("rosy_02", 2.0 + step, 0.0, 0.0))
        executor.settle()
        clock.advance(0.5)

    assert nav._last_progress_ts == baseline
    assert nav._last_progress_pos == (0.0, 0.0)


def test_the_stuck_timeout_is_measured_on_the_injected_clock():
    """브리지가 ROS 시계를 끼우면 `use_sim_time` 시뮬에서도 30 초가 시뮬 30 초다.

    벽시계로 재면 RTF 0.1 인 기계에서 30 초 무진척 조건이 시뮬 3 초 만에 성립해, 제자리
    회전 중인 로봇이 움직여 보기도 전에 잘린다 — 미로 시험에서 실제로 그렇게 끊겼다.
    """
    swarm, nav, executor, clock, events, _safety, _docking = build()
    fake = FakeClock()
    nav.clock = fake
    nav.goal(NavGoalSpec(1.0, 0.0, 0.0))
    executor.settle()
    nav.on_pose_progress(0.0, 0.0)

    fake.advance(29.0)
    nav.on_pose_progress(0.0, 0.0)
    assert "nav.stuck" not in events.types()

    fake.advance(2.0)
    nav.on_pose_progress(0.0, 0.0)
    assert "nav.stuck" in events.types()


def test_opening_a_follow_session_starts_the_no_progress_clock_fresh():
    """서 있던 로봇이 추종을 시작하면 무진척 시계도 그때 시작한다.

    SWM-002 를 지키느라 `on_goal_accepted` 가 추종 중 기준점을 지우지 않는데, 그 규칙이
    세션이 **열리는 순간**까지 걸리면 직전 주행에서 남은 낡은 기준시각이 살아남는다.
    그러면 한참 주차돼 있던 팔로워는 첫 참조 pose 하나에 `nav.stuck` 을 맞고, 대형은
    무장하자마자 HOLDING 으로 떨어진다 — sim bench 에서 무장 63 ms 뒤에 실제로 그랬다.
    """
    swarm, nav, executor, clock, events, _safety, _docking = build()
    nav.goal(NavGoalSpec(1.0, 0.0, 0.0))
    executor.settle()
    nav.on_pose_progress(0.0, 0.0)
    nav.on_result(True)
    import time as _time
    nav._last_progress_ts = _time.monotonic() - 3600.0   # 한 시간 서 있었다

    swarm.follow(params())
    stream(swarm, executor, clock, 1.0)
    nav.on_pose_progress(0.0, 0.0)   # 아직 못 움직였다 — 그래도 갓 시작한 세션이다
    nav.on_pose_progress(0.0, 0.0)

    assert "nav.stuck" not in events.types()
    assert nav.nav_state is NavigationState.NAVIGATING


def test_a_single_goal_still_resets_the_stuck_baseline():
    """추종 세션 밖에서는 기존 동작 그대로여야 한다."""
    swarm, nav, executor, clock, _events, _safety, _docking = build()
    nav.goal(NavGoalSpec(1.0, 0.0, 0.0))
    executor.settle()
    nav.on_pose_progress(0.0, 0.0)
    marked = nav._last_progress_pos

    nav.cancel()
    nav.goal(NavGoalSpec(2.0, 0.0, 0.0))
    executor.settle()

    assert nav._last_progress_pos is None and marked is not None


# --- 소유권과 중재 ---------------------------------------------------------------


def test_an_operator_goal_during_a_follow_is_refused_not_silently_overwritten():
    swarm, nav, executor, clock, _events, _safety, _docking = build()
    swarm.follow(params())
    stream(swarm, executor, clock, 1.0)

    with pytest.raises(NavigationError) as raised:
        nav.goal(NavGoalSpec(9.0, 9.0, 0.0))

    assert raised.value.code == "NAVIGATION_ACTIVE"
    assert "moving-goal session" in str(raised.value)


def test_the_estop_ends_the_follow_and_release_alone_does_not_restart_it():
    """리뷰가 재현한 경로: 해제 뒤 참조 프레임 하나로 다시 달리기 시작했다."""
    swarm, nav, executor, clock, events, safety, _docking = build()
    swarm.follow(params())
    stream(swarm, executor, clock, 1.0)

    safety.trigger_estop("operator")
    swarm.tick()

    assert swarm.active is False
    assert executor.cancelled_handles >= 1
    aborted = [data for type_, data in events.published if type_ == "swarm.aborted"]
    assert aborted and aborted[-1]["reason"] == "estop"

    safety.release("admin")
    before = len(executor.goals)
    swarm.on_reference_pose(ReferencePose("rosy_02", 5.0, 0.0, 0.0))

    assert len(executor.goals) == before, "a pose alone must not re-arm the follow"


def test_the_follow_yields_to_a_docking_run():
    """DOCKING(4) > NAVIGATION(5). SAF-005 저배터리 복귀가 이 경로로 간다."""
    swarm, nav, executor, clock, events, _safety, docking = build()
    swarm.follow(params())
    stream(swarm, executor, clock, 1.0)

    docking["active"] = True
    swarm.tick()

    assert swarm.active is False
    aborted = [data for type_, data in events.published if type_ == "swarm.aborted"]
    assert aborted and aborted[-1]["reason"] == "docking"


def test_a_goal_that_lost_the_race_with_a_cancel_is_refused_by_navigation():
    """추종자가 자기 락을 쥔 채 nav 를 부르지 않아도 되는 이유.

    목표에는 세션 토큰이 붙는다. 취소가 먼저 도착하면 토큰이 닫히고, 뒤늦게
    도착한 목표는 nav 의 락 안에서 버려진다 — 아무도 거두지 않는 목표가
    남지 않는다.
    """
    swarm, nav, executor, clock, _events, _safety, _docking = build()
    swarm.follow(params())
    stream(swarm, executor, clock, 1.0)
    stale_session = nav._moving_session
    before = len(executor.goals)

    swarm.cancel()

    assert nav.moving_goal(NavGoalSpec(9.0, 9.0, 0.0), session=stale_session) is False
    assert len(executor.goals) == before


def test_a_goal_carrying_the_live_session_is_accepted():
    swarm, nav, executor, clock, _events, _safety, _docking = build()
    swarm.follow(params())

    assert nav.moving_goal(NavGoalSpec(1.0, 0.0, 0.0),
                           session=nav._moving_session) is True


def test_a_hold_keeps_the_session_open_so_the_stream_can_resume():
    """HOLD 는 목표만 거둔다. 세션까지 닫으면 돌아온 스트림이 거절당한다."""
    swarm, nav, executor, clock, _events, _safety, _docking = build()
    swarm.follow(params(stream_timeout_ms=1000))
    stream(swarm, executor, clock, 1.0)

    clock.advance(1.0)
    swarm.tick()
    assert swarm.holding is True

    clock.advance(0.1)
    issued = swarm.on_reference_pose(ReferencePose("rosy_02", 3.0, 0.0, 0.0))

    assert issued is True
    assert executor.goals[-1].x == pytest.approx(2.5)


# --- NAV-006 는 추종을 끝낸다. 자동 재시도가 아니다 -------------------------------


def test_a_stuck_follower_ends_the_session_instead_of_retrying_forever():
    """리뷰가 재현한 경로: 취소하고 0.5 초 뒤 다시 목표를 내며 무한 반복했다."""
    swarm, nav, executor, clock, events, _safety, _docking = build()
    swarm.follow(params())
    stream(swarm, executor, clock, 1.0)
    nav.on_pose_progress(0.0, 0.0)

    import time as _time
    nav._last_progress_ts = _time.monotonic() - 60.0
    nav.on_pose_progress(0.0, 0.0)

    assert "nav.stuck" in events.types()
    assert swarm.active is False, "the follow must end; retrying is the operator's call"
    aborted = [data for type_, data in events.published if type_ == "swarm.aborted"]
    assert aborted and aborted[-1]["reason"] == "stuck"

    # 리더가 계속 흘려도 다시 달리지 않는다.
    before = len(executor.goals)
    for step in range(5):
        swarm.on_reference_pose(ReferencePose("rosy_02", 10.0 + step, 0.0, 0.0))
        clock.advance(0.5)
    assert len(executor.goals) == before
    assert events.types().count("nav.stuck") == 1


def test_a_cancel_resets_the_stuck_baseline():
    """남겨 두면 다음 목표가 만료된 기준으로 곧장 다시 stuck 판정을 받는다."""
    swarm, nav, executor, clock, _events, _safety, _docking = build()
    nav.goal(NavGoalSpec(1.0, 0.0, 0.0))
    executor.settle()
    nav.on_pose_progress(0.0, 0.0)
    import time as _time
    nav._last_progress_ts = _time.monotonic() - 60.0

    nav.cancel(source="test")

    assert nav._last_progress_pos is None
    assert nav._last_progress_ts > _time.monotonic() - 1.0


def test_the_formation_geometry_reaches_the_executor_unchanged():
    swarm, _nav, executor, clock, _events, _safety, _docking = build()
    swarm.follow(params(distance=0.8, lateral=0.3))

    swarm.on_reference_pose(ReferencePose("rosy_02", 2.0, 1.0, math.pi / 2))

    spec = executor.goals[-1]
    assert spec.x == pytest.approx(2.0 - 0.3)
    assert spec.y == pytest.approx(1.0 - 0.8)
    assert spec.frame == "map"


# --- 도킹은 문 앞에서 막는다 -----------------------------------------------------


def test_a_follow_is_refused_while_a_docking_run_owns_navigation():
    """받아들인 뒤 다음 틱에 조용히 푸는 것은 거절보다 나쁘다."""
    swarm, _nav, _executor, _clock, _events, _safety, docking = build()
    docking["active"] = True

    with pytest.raises(SwarmError) as raised:
        swarm.follow(params())

    assert raised.value.code == "DOCKING_ACTIVE"
    assert swarm.active is False


def test_the_estop_listener_ends_the_follow_without_waiting_for_a_tick():
    swarm, _nav, executor, clock, events, safety, _docking = build()
    swarm.follow(params())
    stream(swarm, executor, clock, 1.0)

    safety.trigger_estop("operator")

    assert swarm.active is False
    aborted = [data for type_, data in events.published if type_ == "swarm.aborted"]
    assert aborted and aborted[-1]["reason"] == "estop"


def test_an_operator_goal_stays_refused_while_the_follow_is_merely_holding():
    """HOLD 중이라고 목표의 임자가 바뀌지는 않는다 — 돌아온 스트림이 곧 덮는다."""
    swarm, nav, executor, clock, _events, _safety, _docking = build()
    swarm.follow(params(stream_timeout_ms=1000))
    stream(swarm, executor, clock, 1.0)
    clock.advance(1.0)
    swarm.tick()
    assert swarm.holding is True

    with pytest.raises(NavigationError) as raised:
        nav.goal(NavGoalSpec(9.0, 9.0, 0.0))
    assert raised.value.code == "NAVIGATION_ACTIVE"


# --- A1: 세션을 닫는 길은 추종자 말고도 있다 -------------------------------------


def test_an_operator_navigation_cancel_ends_the_follow():
    """세션만 닫히고 추종이 남으면, 목표를 하나도 못 내면서 스냅샷에는
    active: true 로 보인다 — 참조가 계속 오니 스트림도 신선해 보인다."""
    swarm, nav, executor, clock, events, _safety, _docking = build()
    swarm.follow(params())
    stream(swarm, executor, clock, 1.0)

    nav.cancel(source="api:operator")

    assert swarm.active is False
    aborted = [data for type_, data in events.published if type_ == "swarm.aborted"]
    assert aborted and aborted[-1]["reason"] == "navigation_canceled"

    before = len(executor.goals)
    swarm.on_reference_pose(ReferencePose("rosy_02", 5.0, 0.0, 0.0))
    assert len(executor.goals) == before


def test_the_swarms_own_cancel_does_not_bounce_back_through_the_listener():
    swarm, _nav, _executor, clock, events, _safety, _docking = build()
    swarm.follow(params())

    swarm.cancel()

    assert [t for t, _ in events.published].count("swarm.aborted") == 1


def test_a_follow_never_outlives_its_session():
    """어느 길로 세션이 닫히든 추종 상태와 어긋나지 않는다."""
    for closer in ("api:operator", "mode:operator", "stuck_detector"):
        swarm, nav, _executor, clock, _events, _safety, _docking = build()
        swarm.follow(params())
        stream(swarm, nav.executor, clock, 1.0)

        nav.cancel(source=closer)

        assert swarm.active is False, closer
        assert nav._moving_session is None, closer
        assert swarm.state_payload()["active"] is False, closer


def test_a_refused_arming_leaves_no_session_behind():
    """세션을 여는 것과 무장은 한 구간이다.

    락 밖에서 열면 그 사이에 도착한 cancel 이 임자 없는 세션을 남기고,
    그러면 단발 목표가 영영 NAVIGATION_ACTIVE 로 거절당한다.
    """
    swarm, nav, executor, _clock, _events, safety, _docking = build()
    original = swarm.check_follow

    def trip(body):
        original(body)
        safety.trigger_estop("operator")

    swarm.check_follow = trip
    with pytest.raises(SwarmError):
        swarm.follow(params())

    assert nav._moving_session is None
    safety.release("admin")
    nav.goal(NavGoalSpec(1.0, 0.0, 0.0))
    assert executor.goals[-1].x == pytest.approx(1.0)


def test_a_stale_cancel_does_not_close_a_reissued_follow():
    """추종자가 락을 놓은 사이에 새 follow 가 무장하면, 옛 취소는 남의 세션이다."""
    swarm, nav, executor, clock, _events, _safety, _docking = build()
    swarm.follow(params())
    stale_session = nav._moving_session

    swarm.follow(params(distance=0.9))   # 새 세션
    nav.cancel(source="swarm", session=stale_session)

    assert swarm.active is True
    assert nav._moving_session is not None
    assert swarm.on_reference_pose(ReferencePose("rosy_02", 3.0, 0.0, 0.0)) is True


def test_an_estop_landing_during_arming_does_not_leave_a_follow_armed():
    """check_follow 와 무장 사이의 창. 무장 직전에 한 번 더 본다."""
    swarm, _nav, _executor, _clock, _events, safety, _docking = build()
    original = swarm.check_follow

    def trip(body):
        original(body)
        safety.trigger_estop("operator")

    swarm.check_follow = trip

    with pytest.raises(SwarmError) as raised:
        swarm.follow(params())

    assert raised.value.code == "EMERGENCY_ACTIVE"
    assert swarm.active is False


# --- SWM-002 max_speed: 검증이 아니라 실제 제한 -----------------------------------


def command_manager(safety, events):
    from core_features.command.arbitration import Mode, ModeMachine, SourceRegistry
    from core_features.command.manager import CommandManager

    modes = ModeMachine()
    modes.transition(Mode.NAVIGATION)
    return CommandManager(SourceRegistry(), modes, safety, events=events), modes


def test_the_follow_cap_reaches_the_wheels_not_just_the_validator():
    """D-2 의 단일 통로를 그대로 쓴다 — Nav2 파라미터 없이도 실제로 느려진다."""
    from core_features.command.manager import Twist

    swarm, _nav, _executor, _clock, events, safety, _docking = build()
    command, _modes = command_manager(safety, events)
    swarm.follow(params(max_speed=0.05))

    command.set_nav_twist(Twist(0.20, 0.0))

    assert command.select_output().linear == pytest.approx(0.05)


def test_cancelling_the_follow_gives_the_profile_limit_back():
    from core_features.command.manager import Twist

    swarm, _nav, _executor, _clock, events, safety, _docking = build()
    command, _modes = command_manager(safety, events)
    ceiling = safety.limits.max_linear
    swarm.follow(params(max_speed=0.05))

    swarm.cancel()
    command.set_nav_twist(Twist(0.20, 0.0))

    assert command.select_output().linear == pytest.approx(ceiling)


def test_the_session_cap_can_only_lower_the_limit():
    """활동이 프로필 상한을 넘겨 달릴 수는 없다 (SAF-004)."""
    swarm, _nav, _executor, _clock, _events, safety, _docking = build()
    ceiling = safety.limits.max_linear
    safety.set_session_speed(ceiling * 5)

    assert safety.clip(ceiling * 5, 0.0, "nav")[0] == pytest.approx(ceiling)


def test_the_cap_applies_to_manual_teleop_too_while_a_formation_runs():
    """상한은 활동 구간의 것이다. 추종 중 수동으로 밀어도 그 위로는 못 간다."""
    swarm, _nav, _executor, _clock, _events, safety, _docking = build()
    swarm.follow(params(max_speed=0.05))

    assert safety.clip(0.20, 0.0, "manual")[0] == pytest.approx(0.05)


def test_an_estop_still_wins_over_the_clipped_twist():
    from core_features.command.manager import Twist

    swarm, _nav, _executor, _clock, events, safety, _docking = build()
    command, _modes = command_manager(safety, events)
    swarm.follow(params(max_speed=0.05))
    command.set_nav_twist(Twist(0.20, 0.0))

    safety.trigger_estop("operator")

    assert command.select_output().linear == pytest.approx(0.0)
    assert swarm.active is False, "the estop listener also ends the formation"
    assert safety.session_linear is None, "and the cap comes off with it"


def test_a_manual_takeover_during_a_hold_gives_the_operator_their_speed_back():
    """전역 캡을 옹호하는 근거가 서는 자리.

    HOLD 중에는 아무도 목표를 내지 않는데 캡은 걸려 있다. 그 상태가 갇힘이
    아닌 이유는 오직 하나 — 운영자가 수동으로 넘어가는 그 동작이 대형을
    끝내고 캡을 함께 푼다는 것. 그 경로가 끊기면 조용히 느린 로봇이 남는다.
    """
    swarm, nav, executor, clock, _events, safety, _docking = build()
    swarm.follow(params(max_speed=0.05, stream_timeout_ms=1000))
    stream(swarm, executor, clock, 1.0)
    clock.advance(1.0)
    swarm.tick()
    assert swarm.holding is True and safety.session_linear == pytest.approx(0.05)

    # control.py 가 MANUAL 전환에서 보내는 것과 같은 취소.
    nav.cancel(source="mode:operator")

    assert swarm.active is False
    assert safety.session_linear is None
    assert safety.clip(0.20, 0.0, "manual")[0] == pytest.approx(
        safety.limits.manual_linear)


def test_the_cap_comes_off_when_the_formation_ends_for_any_reason():
    swarm, nav, _executor, clock, _events, safety, _docking = build()
    for closer in ("api:operator", "stuck_detector"):
        swarm.follow(params(max_speed=0.05))
        assert safety.session_linear == pytest.approx(0.05), closer

        nav.cancel(source=closer)

        assert swarm.active is False, closer
        assert safety.session_linear is None, closer


# --- MAP-002 를 추종에도 (D-31 의 남은 구멍) -------------------------------------


def follow_on_map(map_id="site_a"):
    swarm, nav, executor, clock, events, safety, docking = build()
    swarm._state.set_map_id(map_id)
    swarm.follow(params())
    return swarm, nav, executor, clock, events


def test_a_reference_from_another_map_is_not_turned_into_a_goal():
    """웨이포인트에는 MAP_MISMATCH 가드가 있는데 추종에는 없었다.

    다른 맵의 좌표를 그대로 목표로 삼으면 그럴듯해 보이는 엉뚱한 지점으로 간다.
    """
    swarm, _nav, executor, _clock, events = follow_on_map("site_a")

    issued = swarm.on_reference_pose(
        ReferencePose("rosy_02", 4.0, 0.0, 0.0, map_id="site_b"))

    assert issued is False
    assert executor.goals == []
    holds = [d for t, d in events.published if t == "swarm.hold"]
    assert holds and holds[-1]["reason"] == "map_mismatch"
    assert holds[-1]["reference_map_id"] == "site_b" and holds[-1]["map_id"] == "site_a"


def test_a_map_mismatch_is_announced_once_not_every_frame():
    swarm, _nav, _executor, clock, events = follow_on_map("site_a")

    for _ in range(5):
        swarm.on_reference_pose(ReferencePose("rosy_02", 4.0, 0.0, 0.0, map_id="site_b"))
        clock.advance(0.1)

    assert [t for t, _ in events.published].count("swarm.hold") == 1
    assert swarm.state_payload()["map_mismatch"] == "site_b"


def test_a_map_mismatch_withdraws_the_goal_but_keeps_the_formation():
    swarm, nav, executor, clock, _events = follow_on_map("site_a")
    swarm.on_reference_pose(ReferencePose("rosy_02", 1.0, 0.0, 0.0, map_id="site_a"))
    executor.settle()
    clock.advance(0.5)

    swarm.on_reference_pose(ReferencePose("rosy_02", 4.0, 0.0, 0.0, map_id="site_b"))

    assert executor.cancelled_handles >= 1
    assert swarm.active is True
    assert nav._moving_session is not None, "the session survives so the stream can resume"


def test_a_leader_returning_to_our_map_resumes_the_formation():
    swarm, _nav, executor, clock, _events = follow_on_map("site_a")
    swarm.on_reference_pose(ReferencePose("rosy_02", 4.0, 0.0, 0.0, map_id="site_b"))
    assert swarm.state_payload()["map_mismatch"] == "site_b"

    clock.advance(0.6)
    issued = swarm.on_reference_pose(
        ReferencePose("rosy_02", 2.0, 0.0, 0.0, map_id="site_a"))

    assert issued is True
    assert swarm.state_payload()["map_mismatch"] is None
    assert executor.goals[-1].x == pytest.approx(1.5)


def test_a_reference_without_a_map_id_is_still_followed():
    """이 필드는 additive 다. 그것을 모르는 Fleet 릴레이가 계속 동작해야 한다."""
    swarm, _nav, executor, _clock, _events = follow_on_map("site_a")

    assert swarm.on_reference_pose(ReferencePose("rosy_02", 1.0, 0.0, 0.0)) is True
    assert executor.goals


def test_a_robot_with_no_map_of_its_own_does_not_refuse_the_leader():
    """비교할 것이 없으면 확인할 수 없다. 확인 실패로 읽어 멈추면 안 된다."""
    swarm, _nav, _executor, _clock, _events, _safety, _docking = build()
    swarm.follow(params())

    assert swarm.on_reference_pose(
        ReferencePose("rosy_02", 1.0, 0.0, 0.0, map_id="site_b")) is True


def test_a_map_mismatch_does_not_read_as_a_lost_stream():
    """표본은 도착하고 있다. SWM-004 타임아웃을 걸면 원인을 잘못 말한다."""
    swarm, _nav, _executor, clock, events = follow_on_map("site_a")
    swarm.on_reference_pose(ReferencePose("rosy_02", 4.0, 0.0, 0.0, map_id="site_b"))

    clock.advance(0.5)
    swarm.tick()

    assert swarm.holding is False
    reasons = [d.get("reason") for t, d in events.published if t == "swarm.hold"]
    assert reasons == ["map_mismatch"]


# --- SLAM 과 추종은 같은 주행을 두고 다툰다 ---------------------------------------


def test_mapping_cannot_start_under_a_formation():
    """`moving_goal` 은 맵핑 중을 막는다. 이쪽이 반대 방향이다."""
    swarm, nav, executor, clock, _events, _safety, _docking = build()
    swarm.follow(params())
    stream(swarm, executor, clock, 1.0)

    with pytest.raises(NavigationError) as raised:
        nav.start_mapping()

    assert raised.value.code == "NAVIGATION_ACTIVE"
    assert "moving-goal session" in str(raised.value)


def test_a_hold_does_not_open_the_door_to_mapping():
    """HOLD 중에는 나가 있는 목표가 없다. `_nav_state` 만 보면 열려 보인다 —
    그러나 대형은 여전히 목표의 임자이고, 스트림이 돌아오면 이어간다."""
    swarm, nav, executor, clock, _events, _safety, _docking = build()
    swarm.follow(params(stream_timeout_ms=1000))
    stream(swarm, executor, clock, 1.0)
    clock.advance(1.0)
    swarm.tick()
    assert swarm.holding is True

    with pytest.raises(NavigationError) as raised:
        nav.start_mapping()
    assert raised.value.code == "NAVIGATION_ACTIVE"


def test_mapping_starts_normally_once_the_formation_is_cancelled():
    swarm, nav, executor, clock, _events, _safety, _docking = build()
    swarm.follow(params())
    stream(swarm, executor, clock, 1.0)
    swarm.cancel()

    nav.start_mapping()

    assert nav.mapping_active is True


def test_a_follow_is_refused_at_the_door_during_a_mapping_session():
    """두 게이트가 양방향을 닫는다.

    받아들이면 목표 투입이 MAPPING_ACTIVE 로 거절되는데 그 예외는 참조
    소켓이 삼킨다 — 운영자는 200 을 보고, 대형은 무장된 채 아무것도 못 한다.
    """
    swarm, nav, _executor, _clock, _events, _safety, _docking = build()
    nav.start_mapping()

    with pytest.raises(SwarmError) as raised:
        swarm.follow(params())

    assert raised.value.code == "MAPPING_ACTIVE"
    assert swarm.active is False


def test_a_mismatch_arriving_during_a_stream_loss_hold_corrects_the_reason():
    """`holding: true` 와 갓 갱신된 `stream_age_s` 가 나란히 보이면 안 된다.

    프레임이 도착했다는 것은 스트림이 살아 있다는 뜻이다. 멈춘 이유는 이제
    단절이 아니라 맵 불일치이고, 상태는 그렇게 말해야 한다.
    """
    swarm, _nav, executor, clock, events, _safety, _docking = build()
    swarm._state.set_map_id("site_a")
    swarm.follow(params(stream_timeout_ms=1000))
    swarm.on_reference_pose(ReferencePose("rosy_02", 1.0, 0.0, 0.0, map_id="site_a"))
    executor.settle()
    clock.advance(1.0)
    swarm.tick()
    assert swarm.state_payload()["holding"] is True

    clock.advance(0.1)
    swarm.on_reference_pose(ReferencePose("rosy_02", 4.0, 0.0, 0.0, map_id="site_b"))

    body = swarm.state_payload()
    assert body["holding"] is False
    assert body["map_mismatch"] == "site_b"
    assert body["stream_age_s"] == pytest.approx(0.0)
    assert [d.get("reason") for t, d in events.published if t == "swarm.hold"] == [
        "reference stream lost", "map_mismatch"]


def test_a_matching_frame_after_that_clears_both():
    swarm, _nav, executor, clock, _events, _safety, _docking = build()
    swarm._state.set_map_id("site_a")
    swarm.follow(params(stream_timeout_ms=1000))
    swarm.on_reference_pose(ReferencePose("rosy_02", 1.0, 0.0, 0.0, map_id="site_a"))
    executor.settle()
    clock.advance(1.0)
    swarm.tick()
    clock.advance(0.1)
    swarm.on_reference_pose(ReferencePose("rosy_02", 4.0, 0.0, 0.0, map_id="site_b"))

    clock.advance(0.6)
    issued = swarm.on_reference_pose(
        ReferencePose("rosy_02", 2.0, 0.0, 0.0, map_id="site_a"))

    assert issued is True
    body = swarm.state_payload()
    assert body["holding"] is False and body["map_mismatch"] is None


def test_mapping_starting_between_the_check_and_the_arming_is_refused():
    """게이트를 양쪽에 두는 것만으로는 부족하다.

    확인과 무장 사이에 상대가 시작되면 둘 다 주행의 임자가 된다. 결정은
    세션을 여는 항법 락 안에서 난다.
    """
    swarm, nav, _executor, _clock, _events, _safety, _docking = build()
    original = swarm.check_follow

    def trip(body):
        original(body)
        nav.start_mapping()   # 운영자의 POST /slam/start 가 이 틈에 도착한다

    swarm.check_follow = trip

    with pytest.raises(SwarmError) as raised:
        swarm.follow(params())

    assert raised.value.code == "MAPPING_ACTIVE"
    assert swarm.active is False
    assert nav._moving_session is None, "no session may survive the refusal"


def test_a_refused_arming_does_not_leave_the_speed_cap_on():
    swarm, nav, _executor, _clock, _events, safety, _docking = build()
    original = swarm.check_follow

    def trip(body):
        original(body)
        nav.start_mapping()

    swarm.check_follow = trip

    with pytest.raises(SwarmError):
        swarm.follow(params(max_speed=0.05))

    assert safety.session_linear is None


def test_a_standing_map_mismatch_does_not_relabel_itself_as_a_lost_stream():
    """서 있는 이유는 불일치다. 타임아웃이 지난다고 원인이 바뀌지 않는다."""
    swarm, _nav, executor, clock, events, _safety, _docking = build()
    swarm._state.set_map_id("site_a")
    swarm.follow(params(stream_timeout_ms=1000))
    swarm.on_reference_pose(ReferencePose("rosy_02", 1.0, 0.0, 0.0, map_id="site_a"))
    executor.settle()
    clock.advance(0.6)
    swarm.on_reference_pose(ReferencePose("rosy_02", 4.0, 0.0, 0.0, map_id="site_b"))

    for _ in range(4):
        clock.advance(1.0)
        swarm.tick()

    reasons = [d.get("reason") for t, d in events.published if t == "swarm.hold"]
    assert reasons == ["map_mismatch"], reasons

