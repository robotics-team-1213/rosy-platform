"""SAF-003 Fleet 연결 상실 정책 (D-419).

판정 규칙: FleetAgent 가 설정돼 돌고 있고(`configured`), 링크가 끊긴 순간에 Fleet 이
보낸 주행 목표(correlation_id 가 있는 목표, D-316)가 진행 중이었으며, 그 목표가 그대로인
채로 `fleet_loss_timeout_s` 동안 링크가 끊겨 있으면 정책을 한 번 적용한다.
시계를 주입해 기다리지 않는다.
"""

from __future__ import annotations

import math

import pytest

from core_common.protocol.schemas import NavigationState
from core_features.navigation.manager import NavGoalSpec, NavigationManager
from core_features.safety.fleet_loss import (
    DEFAULT_TIMEOUT_S,
    FleetLossMonitor,
    fleet_loss_timeout_s,
    normalize_policy,
    validate_link_timing,
)
from core_features.safety.manager import BatteryPolicy, SafetyManager, SpeedLimits
from core_features.state.manager import StateManager


class FakeClock:
    def __init__(self) -> None:
        self.now = 500.0

    def __call__(self) -> float:
        return self.now


class FakeEvents:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, dict]] = []

    def publish(self, type_, severity="info", source="", data=None):
        self.published.append((type_, severity, data or {}))

    def types(self) -> list[str]:
        return [t for t, _, _ in self.published]

    def last(self, type_: str) -> dict:
        return [d for t, _, d in self.published if t == type_][-1]


class FakeExecutor:
    def __init__(self) -> None:
        self.sent: list[tuple[NavGoalSpec, str | None]] = []
        self.cancelled = 0

    def send_goal(self, spec, *, correlation_id=None):
        self.sent.append((spec, correlation_id))

    def cancel_goal(self):
        self.cancelled += 1


class FakeWaypoints:
    def __init__(self, home=None) -> None:
        self.home = home

    def get(self, name):
        if name == "__home__" and self.home is not None:
            return self.home
        raise KeyError(name)


class Link:
    def __init__(self, configured=True, connected=True) -> None:
        self.configured = configured
        self.connected = connected
        self.last_rx = None          # None = no freshness signal (pre-review behaviour)


class Rig:
    def __init__(self, policy="STOP", home=None, timeout_s=3.0, configured=True,
                 stop_goal=None) -> None:
        self.clock = FakeClock()
        self.events = FakeEvents()
        self.safety = SafetyManager(SpeedLimits(), BatteryPolicy(), fleet_loss_policy=policy)
        self.nav = NavigationManager(self.events, StateManager(robot_id="rosy_01"),
                                     FakeWaypoints(home), self.safety)
        self.executor = FakeExecutor()
        self.nav.executor = self.executor
        self.link = Link(configured=configured)
        self.home_calls = 0

        def go_home():
            self.home_calls += 1
            self.nav.home(source="fleet_loss")

        self.monitor = FleetLossMonitor(
            events=self.events,
            link_configured=lambda: self.link.configured,
            link_connected=lambda: self.link.connected,
            link_last_rx=lambda: self.link.last_rx,
            fleet_goal=self.nav.fleet_goal,
            policy=lambda: self.safety.fleet_loss_policy,
            stop_goal=stop_goal or (
                lambda cid: self.nav.cancel(source="fleet_loss", correlation_id=cid)),
            return_home=go_home,
            timeout_s=timeout_s,
            clock=self.clock,
        )

    def fleet_goal(self, cid="attempt-1"):
        self.nav.goal(NavGoalSpec(1.0, 2.0, 0.5), source="api:operator", correlation_id=cid)
        self.nav.on_goal_accepted()

    def run(self, seconds: float, step: float = 0.2) -> None:
        end = self.clock.now + seconds
        while self.clock.now < end - 1e-9:
            self.monitor.tick()
            self.clock.now += step
        self.monitor.tick()


# --- 설정 ------------------------------------------------------------------


def test_policy_names_normalise_and_unknown_falls_back_to_stop():
    assert normalize_policy("STOP") == ("STOP", True)
    assert normalize_policy("hold") == ("HOLD", True)
    assert normalize_policy("CONTINUE_CURRENT_NAVIGATION") == ("CONTINUE", True)
    assert normalize_policy("RETURN_HOME") == ("RETURN_HOME", True)
    assert normalize_policy("PANIC") == ("STOP", False)
    assert normalize_policy(None) == ("STOP", False)


def test_timeout_defaults_and_rejects_out_of_range_values():
    assert fleet_loss_timeout_s({}) == DEFAULT_TIMEOUT_S == 5.0
    assert fleet_loss_timeout_s({"fleet_loss_timeout_s": 4}) == 4.0
    assert fleet_loss_timeout_s({"fleet_loss_timeout_s": 10}) == 10.0
    for bad in (0, 0.5, 3, 3.9, 61, -1, math.nan, math.inf, "5", True):
        with pytest.raises(ValueError):
            fleet_loss_timeout_s({"fleet_loss_timeout_s": bad})


def test_timeout_must_outlast_heartbeat_period_plus_reply_deadline():
    validate_link_timing(4.0, 1.0, 2.0)
    validate_link_timing(5.0, 1.0, 3.0)
    with pytest.raises(ValueError, match="heartbeat_reply_timeout_s"):
        validate_link_timing(4.0, 1.0, 2.5)


class Cadence:
    """The agent's 1 Hz heartbeat on the rig clock (agent clock = rig clock): the reply
    lands `latency` s after a send and refreshes last_rx, the next send waits one period;
    once the hub falls silent the agent drops the socket at the 2 s reply deadline. The
    monitor ticks at 5 Hz like the bridge power timer."""

    def __init__(self, rig: "Rig", *, latency: float, period: float = 1.0,
                 reply_timeout: float = 2.0) -> None:
        self.rig, self.latency, self.period, self.reply_timeout = rig, latency, period, reply_timeout
        self.hub_answers = True
        self.next_send = rig.clock.now
        self.reply_at = None
        self.deadline = None

    def run(self, seconds: float) -> None:
        rig = self.rig
        end = rig.clock.now + seconds
        while rig.clock.now < end - 1e-9:
            now = rig.clock.now
            if self.reply_at is not None and now >= self.reply_at - 1e-9:
                rig.link.last_rx = self.reply_at
                self.reply_at, self.deadline = None, None
                self.next_send = now + self.period
            if (rig.link.connected and self.reply_at is None and self.deadline is None
                    and now >= self.next_send - 1e-9):
                self.deadline = now + self.reply_timeout
                if self.hub_answers:
                    self.reply_at = now + self.latency
            if self.deadline is not None and self.reply_at is None and now >= self.deadline - 1e-9:
                rig.link.connected = False
            rig.monitor.tick()
            rig.clock.now = round(now + 0.2, 6)


def test_healthy_1hz_link_at_the_lowest_timeout_never_fires():
    """HIGH: freshness is the heartbeat's silence budget, not the policy timeout. A slow
    but healthy hub (1.8 s replies, just inside the 2 s deadline) at the lowest allowed
    timeout (4 s) must never read as lost."""
    rig = Rig("STOP", timeout_s=4.0)
    rig.link.last_rx = rig.clock.now
    rig.fleet_goal()
    Cadence(rig, latency=1.8).run(60.0)
    assert rig.link.connected
    assert rig.executor.cancelled == 0
    assert "safety.fleet_lost" not in rig.events.types()


def test_one_missed_reply_at_defaults_fires_timeout_after_last_rx():
    """Defaults (timeout 5 s, reply deadline 2 s): the hub stops answering; the agent drops
    the socket ~2 s after the unanswered heartbeat, and the policy fires 5 s after the
    last hub message — not later, not earlier."""
    rig = Rig("STOP", timeout_s=5.0)
    rig.link.last_rx = rig.clock.now
    rig.fleet_goal()
    cadence = Cadence(rig, latency=0.2)
    cadence.run(10.0)
    cadence.hub_answers = False
    last_rx = rig.link.last_rx
    while rig.clock.now < last_rx + 4.8:
        cadence.run(0.2)
    assert not rig.link.connected
    assert rig.executor.cancelled == 0, "not before timeout_s after the last hub message"
    cadence.run(0.6)
    assert rig.executor.cancelled == 1
    lost = rig.events.last("safety.fleet_lost")
    assert 5.0 <= lost["disconnected_s"] < 5.5


# --- 적용 범위 --------------------------------------------------------------


def test_stop_cancels_the_fleet_goal_after_the_timeout_and_reports_once():
    rig = Rig("STOP")
    rig.fleet_goal()
    rig.run(1.0)
    rig.link.connected = False
    rig.run(2.8)
    assert rig.executor.cancelled == 0, "링크 상실 판정은 timeout 전에는 아무것도 하지 않는다"
    rig.run(0.4)
    assert rig.executor.cancelled == 1
    assert rig.nav.nav_state is NavigationState.CANCELED
    assert not rig.safety.estop, "STOP 은 래칭 e-stop 이 아니다"
    lost = rig.events.last("safety.fleet_lost")
    assert lost["policy"] == "STOP" and lost["applied"] == "STOP"
    assert lost["correlation_id"] == "attempt-1" and lost["activity"] == "navigation"
    assert lost["goal"] == {"x": 1.0, "y": 2.0, "yaw": 0.5}
    assert lost["disconnected_s"] >= 3.0 and lost["reason"] is None
    canceled = rig.events.last("nav.canceled")
    assert canceled == {"source": "fleet_loss", "correlation_id": "attempt-1"}
    rig.run(5.0)
    assert rig.events.types().count("safety.fleet_lost") == 1
    assert rig.executor.cancelled == 1


def test_restored_link_reports_but_does_not_resume():
    rig = Rig("STOP")
    rig.fleet_goal()
    rig.link.connected = False
    rig.run(3.4)
    rig.link.connected = True
    rig.run(0.4)
    restored = rig.events.last("safety.fleet_restored")
    assert restored["applied"] == "STOP" and restored["correlation_id"] == "attempt-1"
    assert restored["held_goal"] is None
    assert len(rig.executor.sent) == 1, "재접속은 목표를 다시 내지 않는다"


def test_short_outage_below_the_timeout_does_nothing():
    rig = Rig("STOP")
    rig.fleet_goal()
    rig.link.connected = False
    rig.run(2.0)
    rig.link.connected = True
    rig.run(0.4)
    rig.link.connected = False
    rig.run(2.0)
    assert rig.executor.cancelled == 0
    assert "safety.fleet_lost" not in rig.events.types()
    assert "safety.fleet_restored" not in rig.events.types()


def test_local_goal_without_correlation_id_is_not_affected():
    rig = Rig("STOP")
    rig.nav.goal(NavGoalSpec(1.0, 0.0, 0.0), source="api:operator")
    rig.link.connected = False
    rig.run(10.0)
    assert rig.executor.cancelled == 0
    assert "safety.fleet_lost" not in rig.events.types()


def test_robot_without_a_configured_agent_is_not_affected():
    rig = Rig("STOP", configured=False)
    rig.link.connected = False
    rig.fleet_goal()
    rig.run(10.0)
    assert rig.executor.cancelled == 0
    assert rig.events.types().count("safety.fleet_lost") == 0


def test_goal_started_during_an_outage_is_not_affected():
    """REST 로 들어온 Fleet 목표는 Fleet 이 이 로봇에 닿았다는 증거다. SAF-003 은
    '명령 수행 중 연결 장애'만 다루므로, 끊긴 뒤 시작된 목표에는 정책을 걸지 않는다."""
    rig = Rig("STOP")
    rig.link.connected = False
    rig.run(1.0)
    rig.fleet_goal("attempt-2")
    rig.run(10.0)
    assert rig.executor.cancelled == 0
    assert "safety.fleet_lost" not in rig.events.types()


def test_goal_that_finishes_before_the_timeout_is_left_alone():
    rig = Rig("STOP")
    rig.fleet_goal()
    rig.link.connected = False
    rig.run(1.0)
    rig.nav.on_result(True, correlation_id="attempt-1")
    rig.run(5.0)
    assert rig.executor.cancelled == 0
    assert "safety.fleet_lost" not in rig.events.types()


def test_replaced_goal_is_not_cancelled_by_a_stale_decision():
    """판정 사이에 운영자가 취소하고 다른 Fleet 목표를 냈으면 그 목표는 건드리지 않는다."""
    rig = Rig("STOP")
    rig.fleet_goal("attempt-1")
    rig.link.connected = False
    rig.run(1.0)
    rig.nav.cancel(source="api:operator")
    rig.fleet_goal("attempt-9")
    rig.run(5.0)
    assert rig.executor.cancelled == 1      # only the operator's cancel
    assert rig.nav.nav_state is NavigationState.NAVIGATING


def test_nav_cancel_with_correlation_id_refuses_a_different_goal():
    rig = Rig("STOP")
    rig.fleet_goal("attempt-1")
    assert rig.nav.cancel(source="fleet_loss", correlation_id="other") is False
    assert rig.executor.cancelled == 0
    assert rig.nav.cancel(source="fleet_loss", correlation_id="attempt-1") is True
    assert rig.executor.cancelled == 1


# --- 정책별 ------------------------------------------------------------------


def test_hold_stops_like_stop_and_keeps_the_goal_for_an_explicit_resume():
    rig = Rig("HOLD")
    rig.fleet_goal()
    rig.link.connected = False
    rig.run(3.4)
    assert rig.executor.cancelled == 1 and not rig.safety.estop
    lost = rig.events.last("safety.fleet_lost")
    assert lost["applied"] == "HOLD"
    assert rig.monitor.status()["held_goal"] == {
        "correlation_id": "attempt-1", "x": 1.0, "y": 2.0, "yaw": 0.5}
    rig.link.connected = True
    rig.run(1.0)
    restored = rig.events.last("safety.fleet_restored")
    assert restored["held_goal"] == {"correlation_id": "attempt-1", "x": 1.0, "y": 2.0, "yaw": 0.5}
    assert len(rig.executor.sent) == 1, "HOLD 는 스스로 재개하지 않는다"
    assert rig.monitor.status()["held_goal"] is None


def test_continue_lets_the_goal_run_and_only_reports():
    rig = Rig("CONTINUE")
    rig.fleet_goal()
    rig.link.connected = False
    rig.run(5.0)
    assert rig.executor.cancelled == 0
    assert rig.nav.nav_state is NavigationState.NAVIGATING
    lost = rig.events.last("safety.fleet_lost")
    assert lost["policy"] == "CONTINUE" and lost["applied"] == "CONTINUE"


def test_return_home_cancels_and_drives_to_the_home_waypoint():
    from types import SimpleNamespace
    rig = Rig("RETURN_HOME", home=SimpleNamespace(x=0.0, y=0.0, yaw=0.0, map_id=None))
    rig.fleet_goal()
    rig.link.connected = False
    rig.run(3.4)
    assert rig.executor.cancelled == 1 and rig.home_calls == 1
    home_spec, home_cid = rig.executor.sent[-1]
    assert (home_spec.x, home_spec.y, home_cid) == (0.0, 0.0, None)
    lost = rig.events.last("safety.fleet_lost")
    assert lost["applied"] == "RETURN_HOME" and lost["reason"] is None
    assert rig.nav.fleet_goal() is None, "귀환 목표는 Fleet 목표가 아니다"


def test_return_home_without_a_home_point_stays_stopped():
    rig = Rig("RETURN_HOME", home=None)
    rig.fleet_goal()
    rig.link.connected = False
    rig.run(3.4)
    assert rig.executor.cancelled == 1 and not rig.safety.estop
    lost = rig.events.last("safety.fleet_lost")
    assert lost["policy"] == "RETURN_HOME" and lost["applied"] == "STOP"
    assert lost["reason"].startswith("home_unavailable")
    assert rig.nav.nav_state is NavigationState.CANCELED


def test_unknown_policy_value_acts_as_stop_with_a_reason():
    rig = Rig("PANIC")
    rig.fleet_goal()
    rig.link.connected = False
    rig.run(3.4)
    assert rig.executor.cancelled == 1
    lost = rig.events.last("safety.fleet_lost")
    assert lost["policy"] == "PANIC" and lost["applied"] == "STOP"
    assert lost["reason"] == "unknown_policy"


def test_status_reports_the_link_and_the_applied_policy():
    rig = Rig("STOP")
    status = rig.monitor.status()
    assert status == {"configured": True, "connected": True, "lost": False,
                      "timeout_s": 3.0, "applied": None, "correlation_id": None,
                      "disconnected_s": None, "held_goal": None}
    rig.fleet_goal()
    rig.link.connected = False
    rig.run(3.4)
    status = rig.monitor.status()
    assert status["lost"] and status["applied"] == "STOP"
    assert status["correlation_id"] == "attempt-1" and status["disconnected_s"] >= 3.0


def test_goal_that_fails_before_the_timeout_is_left_alone():
    rig = Rig("STOP")
    rig.fleet_goal()
    rig.link.connected = False
    rig.run(1.0)
    rig.nav.on_result(False, "ABORTED", correlation_id="attempt-1")
    rig.run(5.0)
    assert rig.executor.cancelled == 0
    assert "safety.fleet_lost" not in rig.events.types()


# --- D-419 review ----------------------------------------------------------


def test_agent_going_unconfigured_mid_outage_still_counts_as_lost():
    """I1: a rejected hello or stop() must not disarm the monitor during an outage."""
    rig = Rig("STOP")
    rig.fleet_goal()
    rig.link.connected = False
    rig.run(1.0)
    rig.link.configured = False
    rig.run(3.0)
    assert rig.executor.cancelled == 1
    assert rig.events.last("safety.fleet_lost")["applied"] == "STOP"


def test_open_socket_without_hub_traffic_counts_as_down():
    """I2: a socket the hub stopped answering (last_rx stale) is a lost link, so a link
    that flaps up for a moment without fresh hub traffic does not restart the timer."""
    rig = Rig("STOP")
    rig.link.last_rx = rig.clock.now
    rig.fleet_goal()
    rig.run(0.4)
    for _ in range(5):                       # flapping: connected flips, no hub message
        rig.link.connected = not rig.link.connected
        rig.run(0.8)
    assert rig.executor.cancelled == 1
    lost = rig.events.last("safety.fleet_lost")
    assert lost["disconnected_s"] >= 3.0
    assert "safety.fleet_restored" not in rig.events.types()


def test_fresh_hub_traffic_keeps_the_link_up():
    rig = Rig("STOP")
    rig.fleet_goal()
    for _ in range(30):
        rig.link.last_rx = rig.clock.now
        rig.run(0.4)
    assert rig.executor.cancelled == 0
    assert rig.monitor.status()["connected"] is True


@pytest.mark.parametrize("policy", ["STOP", "HOLD", "RETURN_HOME"])
def test_cancel_that_finds_another_goal_applies_nothing(policy):
    """I3: the correlated cancel returned False (goal ended or replaced between the
    check and the cancel) — no home drive, no HOLD record."""
    from types import SimpleNamespace
    rig = Rig(policy, home=SimpleNamespace(x=0.0, y=0.0, yaw=0.0, map_id=None),
              stop_goal=lambda _cid: False)
    rig.fleet_goal()
    rig.link.connected = False
    rig.run(3.4)
    lost = rig.events.last("safety.fleet_lost")
    assert lost["applied"] == "NONE" and lost["reason"] == "goal_changed"
    assert rig.home_calls == 0 and len(rig.executor.sent) == 1
    assert rig.monitor.status()["held_goal"] is None


def test_a_failing_action_does_not_break_the_tick():
    def boom(_cid):
        raise RuntimeError("executor gone")

    rig = Rig("STOP", stop_goal=boom)
    rig.fleet_goal()
    rig.link.connected = False
    rig.run(3.4)
    lost = rig.events.last("safety.fleet_lost")
    assert lost["applied"] == "NONE" and lost["reason"].startswith("action_failed")


# --- D-419 round 3: the real FleetAgent session driving a real monitor ------


def _agent_rig(hub, *, period=0.05, reply=0.15, slack=0.05, timeout=0.6):
    """A real FleetAgent (scaled heartbeat period, reply deadline, slack) feeding a real
    FleetLossMonitor on the real monotonic clock — the agent's own `last_rx` clock."""
    import time
    from types import SimpleNamespace

    from core_features.fleet_agent.agent import FleetAgent
    from fleet_hub_fake import FakeHub  # noqa: F401  (documents where `hub` comes from)

    class Bus:
        def subscribe(self, _cb):
            return lambda: None

    agent = FleetAgent(StateManager(robot_id="rosy_01"), Bus(),
                       {"fleet": {"hub_url": "ws://hub.invalid/", "pairing_token": "t"}},
                       SimpleNamespace(robot_id="rosy_01"))
    agent.enabled = True
    agent.heartbeat_period_s, agent.reply_timeout_s, agent.link_slack_s = period, reply, slack
    rig = Rig("STOP", timeout_s=timeout)
    rig.monitor = FleetLossMonitor(
        events=rig.events, link_configured=lambda: True,
        link_connected=lambda: agent.connected, link_last_rx=lambda: agent.last_rx,
        fleet_goal=rig.nav.fleet_goal, policy=lambda: rig.safety.fleet_loss_policy,
        stop_goal=lambda cid: rig.nav.cancel(source="fleet_loss", correlation_id=cid),
        return_home=lambda: None, timeout_s=timeout, freshness_s=agent.link_fresh_s,
        clock=time.monotonic)
    return agent, rig


async def _tick_for(rig, seconds, step=0.02, until=None):
    import asyncio
    import time
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        rig.monitor.tick()
        if until is not None and until():
            return time.monotonic()
        await asyncio.sleep(step)
    return None


def test_real_agent_session_slow_but_healthy_hub_never_stops():
    """Replies land under the reply deadline (0.35 of 0.50 s). The 150 ms of headroom is
    deliberate: a loaded Windows run (the full suite beside other sessions) stalled the
    loop past an 80 ms margin, which is test jitter, not a link loss. No STOP."""
    import asyncio
    from fleet_hub_fake import FakeHub

    hub = FakeHub(delay=0.35)
    agent, rig = _agent_rig(hub, reply=0.50, timeout=1.0)
    rig.fleet_goal()

    async def run():
        serve = asyncio.create_task(agent._serve(hub))
        await _tick_for(rig, 1.2)
        connected = agent.connected
        agent.enabled = False
        hub._abort()
        await serve
        return connected
    assert asyncio.run(run()) is True
    assert rig.executor.cancelled == 0
    assert "safety.fleet_lost" not in rig.events.types()


def test_real_agent_session_silent_hub_stops_at_last_rx_plus_timeout():
    import asyncio
    from fleet_hub_fake import FakeHub

    hub = FakeHub(delay=0.02)
    agent, rig = _agent_rig(hub, timeout=0.6)
    rig.fleet_goal()

    async def run():
        serve = asyncio.create_task(agent._serve(hub))
        await _tick_for(rig, 0.5)
        hub.answer_heartbeats = False                    # the hub falls silent
        fired_at = await _tick_for(rig, 2.0, until=lambda: rig.executor.cancelled > 0)
        await asyncio.wait_for(serve, timeout=1.0)        # the deadline aborted it
        return fired_at
    fired_at = asyncio.run(run())
    assert fired_at is not None and hub.aborted
    after_last_rx = fired_at - agent.last_rx
    assert 0.6 <= after_last_rx < 0.6 + 0.25, after_last_rx   # tick 20 ms + load jitter
    assert rig.events.last("safety.fleet_lost")["applied"] == "STOP"


def test_real_agent_session_degraded_hub_error_never_stops():
    """Round 3 HIGH, end to end: every heartbeat answered with ERROR
    TASK_PROJECTION_UNAVAILABLE keeps the link up; SAF-003 never fires."""
    import asyncio
    from fleet_hub_fake import FakeHub

    hub = FakeHub(heartbeat_error="TASK_PROJECTION_UNAVAILABLE", delay=0.02)
    agent, rig = _agent_rig(hub)
    rig.fleet_goal()

    async def run():
        serve = asyncio.create_task(agent._serve(hub))
        await _tick_for(rig, 1.0)
        connected = agent.connected
        agent.enabled = False
        hub._abort()
        return connected, await serve
    connected, stable = asyncio.run(run())
    assert connected is True and stable is True
    assert rig.executor.cancelled == 0
    assert "safety.fleet_lost" not in rig.events.types()
