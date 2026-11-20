"""SLAM -> wall map fallback supervisor policy, with fakes for every port (2026-11-18: always automatic)."""
import pytest

from core_features.localization.slam_fallback import (
    ACTIVE, DECISION_TIMEOUT_S, FAILED, MONITORING, STOPPING, SWITCHING, WAITING, ZERO_S, HostReply, Ports, SlamFallback)
from core_features.localization.slam_health import LOST_CONSECUTIVE, Sample


class Status:
    def __init__(self, state, frame="map"):
        self.state, self.pose_frame = type("V", (), {"value": state}), type("V", (), {"value": frame})


class Events:
    def __init__(self, seen):
        self.seen = seen

    def publish(self, kind, severity="info", source="", data=None):
        self.seen.append((kind, severity))


class World:
    """The fake CORE: a clock, a velocity, a goal flag and a host that records what it was asked."""

    def __init__(self, marker=None):
        self.t, self.speed, self.goal = 0.0, (0.0, 0.0), False
        self.bad_jump, self.loc, self.events, self.calls, self.evidence = None, None, [], [], []
        self.halts, self.searches, self.swapped = 0, 0, 0
        self.report_count, self.marker, self.marker_fails = 0, marker, False
        self.host_replies = {}
        self.host_phase = {"phase": "IDLE", "backend": "slam"}

    def report(self, status):
        """A localization report arrives from the robot."""
        self.loc, self.report_count = status, self.report_count + 1

    def write_marker(self, data):
        if self.marker_fails and data is not None:
            raise OSError("read-only")
        self.calls.append(("marker", data))
        self.marker = data

    def sample(self, now):
        return Sample(t=now, jump_m=self.bad_jump, moving=self.goal or self.speed != (0.0, 0.0))

    def host(self, command, **params):
        self.calls.append((command, params))
        reply = self.host_replies.get(command)
        if reply is not None:
            return reply
        if command == "navigation_fallback.status":
            return HostReply(True, "OK", {**self.host_phase, "wall_map": {"map_id": "a", "version": 1, "sha256": "x"}})
        return HostReply(True, "OK", {})

    def ports(self):
        return Ports(sample=self.sample, speed=lambda: self.speed, goal_active=lambda: self.goal,
                     halt=lambda: setattr(self, "halts", self.halts + 1), write_evidence=self.evidence.append,
                     request=self.host, localization=lambda: self.loc, reports=lambda: self.report_count,
                     request_search=lambda: setattr(self, "searches", self.searches + 1),
                     after_switch=lambda: setattr(self, "swapped", self.swapped + 1),
                     events=Events(self.events), read_marker=lambda: self.marker, write_marker=self.write_marker)


def make(backend="slam", marker=None):
    world = World(marker)
    return world, SlamFallback(world.ports(), backend, clock=lambda: world.t, wall=lambda: 1000.0 + world.t)


def step(world, fallback, seconds=1.0, n=1):
    for _ in range(n):
        world.t += seconds
        fallback.tick()


def lose(world, fallback):
    world.bad_jump = 0.5
    step(world, fallback, n=LOST_CONSECUTIVE)
    assert fallback.phase == STOPPING


def stopped_for_a_while(world, fallback):
    step(world, fallback, n=int(ZERO_S) + 2)


def test_it_is_inert_on_the_localization_backend():
    world, fallback = make("localization")
    world.bad_jump = 0.5
    step(world, fallback, n=20)
    assert fallback.phase is None and fallback.status() is None and fallback.hold_reason() is None
    assert world.calls == [] and world.halts == 0 and world.events == []


def test_a_healthy_slam_robot_is_only_watched():
    world, fallback = make()
    step(world, fallback, n=30)
    assert fallback.phase == MONITORING and world.halts == 0 and not [c for c in world.calls if c[0].endswith("switch")]


def test_lost_halts_first_and_refuses_goals_before_anything_is_switched():
    world, fallback = make()
    lose(world, fallback)
    assert world.halts == 1 and fallback.hold_reason() == "slam_fallback_stopping"
    assert not [c for c in world.calls if c[0].endswith("switch")]


def test_it_waits_for_zero_velocity_for_two_seconds_and_writes_that_evidence():
    world, fallback = make()
    lose(world, fallback)
    world.speed = (0.2, 0.0)
    step(world, fallback, n=5)
    assert fallback.phase == STOPPING and world.evidence[-1]["zero_since"] is None
    world.speed = (0.0, 0.0)
    step(world, fallback, n=2)
    assert fallback.phase == STOPPING  # zero for ~1 s only
    step(world, fallback, n=3)
    switches = [c for c in world.calls if c[0] == "navigation_fallback.switch"]
    assert switches == [("navigation_fallback.switch", {"reason": "slam_lost"})]
    assert world.evidence[-1]["written_at"] - world.evidence[-1]["zero_since"] >= ZERO_S  # one monotonic clock
    assert world.evidence[-1]["goal_active"] is False and fallback.phase == SWITCHING


def test_an_unknown_velocity_is_never_zero_and_a_goal_blocks_the_switch():
    world, fallback = make()
    lose(world, fallback)
    world.speed = None
    step(world, fallback, n=10)
    assert fallback.phase == STOPPING
    world.speed, world.goal = (0.0, 0.0), True
    step(world, fallback, n=10)
    assert fallback.phase == STOPPING and world.halts > 1  # the new goal was cancelled again
    assert not [c for c in world.calls if c[0].endswith("switch")]


def test_a_robot_that_cannot_stop_raises_an_alert_and_keeps_trying():
    world, fallback = make()
    lose(world, fallback)
    world.speed = (0.3, 0.0)
    step(world, fallback, n=70)
    assert fallback.phase == STOPPING and fallback.alert and ("slam_fallback.alert", "critical") in world.events


def go_to_switching(world, fallback):
    lose(world, fallback)
    stopped_for_a_while(world, fallback)
    assert fallback.phase == SWITCHING


def test_a_successful_host_switch_swaps_readiness_and_keeps_goals_refused_until_localized():
    world, fallback = make()
    go_to_switching(world, fallback)
    world.host_phase = {"phase": "SWITCHED"}
    step(world, fallback)
    assert fallback.phase == WAITING and world.swapped == 1 and fallback.hold_reason() == "slam_fallback_waiting_pose"
    world.report(Status("CANDIDATES"))
    step(world, fallback, n=3)
    assert fallback.phase == WAITING and fallback.hold_reason()
    world.report(Status("LOCALIZED", frame="odom"))
    step(world, fallback)
    assert fallback.phase == WAITING  # LOCALIZED in the odom frame is not a pose Fleet trusts
    world.report(Status("LOCALIZED"))
    step(world, fallback)
    assert fallback.phase == ACTIVE and fallback.hold_reason() is None and fallback.status()["fallback_active"] is True
    assert world.marker is not None  # the wait was written down for a CORE restart


def test_it_asks_loc_assist_to_search_while_unknown_and_alerts_when_nobody_decides():
    world, fallback = make()
    go_to_switching(world, fallback)
    world.host_phase = {"phase": "SWITCHED"}
    step(world, fallback)
    world.report(Status("UNKNOWN", frame="odom"))
    step(world, fallback, n=25)
    assert world.searches >= 2
    step(world, fallback, n=int(DECISION_TIMEOUT_S))
    assert fallback.phase == WAITING and fallback.alert and fallback.hold_reason()  # stays stopped


@pytest.mark.parametrize("ended", ["ROLLED_BACK", "FAILED", "REFUSED"])
def test_a_failed_host_switch_stays_stopped_alerts_and_does_not_retry(ended):
    world, fallback = make()
    go_to_switching(world, fallback)
    world.host_phase = {"phase": ended, "reason": "boom"}
    step(world, fallback)
    assert fallback.phase == FAILED and fallback.alert and fallback.hold_reason() == "slam_fallback_failed"
    before = len(world.calls)
    step(world, fallback, n=30)
    assert [c for c in world.calls[before:] if c[0].endswith("switch")] == []
    assert fallback.phase == FAILED and fallback.status()["fallback_active"] is False


def test_an_operator_reset_after_a_refused_switch_rearms_monitoring_and_the_host_still_decides():
    world, fallback = make()
    world.host_replies["navigation_fallback.switch"] = HostReply(False, "HOST_AGENT_ROLE_INSUFFICIENT", None, "no")
    lose(world, fallback)
    stopped_for_a_while(world, fallback)
    assert fallback.phase == FAILED
    assert fallback.reset() is True and fallback.phase == MONITORING
    world.calls.clear()
    world.bad_jump = None
    step(world, fallback, n=20)  # health recovers
    lose(world, fallback)
    assert fallback.phase == STOPPING
    stopped_for_a_while(world, fallback)
    assert [c for c in world.calls if c[0].endswith("switch")] == [("navigation_fallback.switch", {"reason": "slam_lost"})]


def test_an_unreachable_host_is_retried_a_few_times_then_fails():
    world, fallback = make()
    world.host_replies["navigation_fallback.switch"] = HostReply(False, "HOST_AGENT_UNAVAILABLE")
    lose(world, fallback)
    stopped_for_a_while(world, fallback)
    step(world, fallback, n=6)
    assert fallback.phase == FAILED
    assert len([c for c in world.calls if c[0].endswith("switch")]) == 3


def test_there_is_no_way_back_after_the_switch():
    world, fallback = make()
    go_to_switching(world, fallback)
    world.host_phase = {"phase": "SWITCHED"}
    step(world, fallback)
    assert fallback.reset() is False  # reset only leaves FAILED, and never after a switch
    world.report(Status("LOCALIZED"))
    step(world, fallback)
    world.bad_jump = 5.0
    world.calls.clear()
    step(world, fallback, n=30)
    assert fallback.phase == ACTIVE and world.calls == []


def test_degraded_only_reports():
    world, fallback = make()
    world.sample = lambda now: Sample(t=now, map_verdict="fail", jump_m=0.0)
    fallback = SlamFallback(world.ports(), "slam", clock=lambda: world.t, wall=lambda: 1000.0 + world.t)
    step(world, fallback, n=130)
    assert fallback.phase == MONITORING and world.halts == 0
    assert ("slam_fallback.health", "warning") in world.events


def test_a_localized_reading_from_before_the_restart_does_not_end_the_wait():
    world, fallback = make()
    world.report(Status("LOCALIZED"))  # the old SLAM pose, still the latest report when the switch lands
    go_to_switching(world, fallback)
    world.host_phase = {"phase": "SWITCHED"}
    step(world, fallback, n=5)
    assert fallback.phase == WAITING and fallback.hold_reason() == "slam_fallback_waiting_pose"
    world.report(Status("LOCALIZED"))  # a report that arrived after the restart
    step(world, fallback)
    assert fallback.phase == ACTIVE


def test_the_stop_evidence_keeps_coming_until_the_host_has_answered():
    world, fallback = make()
    go_to_switching(world, fallback)
    written = len(world.evidence)
    step(world, fallback, n=5)  # the host unit is slow to start
    assert len(world.evidence) == written + 5 and world.evidence[-1]["zero_since"] is not None
    world.goal = True  # a goal appears during the restart: it is cancelled and the evidence stops claiming zero
    halts = world.halts
    step(world, fallback)
    assert world.halts > halts and world.evidence[-1]["goal_active"] is True and world.evidence[-1]["zero_since"] is None


def test_teleop_is_cleared_on_every_tick_while_stopping_and_switching():
    world, fallback = make()
    lose(world, fallback)
    world.speed = (0.2, 0.0)  # an operator drives
    halts = world.halts
    step(world, fallback, n=3)
    assert world.halts == halts + 3
    world.speed = (0.0, 0.0)
    stopped_for_a_while(world, fallback)
    assert fallback.phase == SWITCHING
    world.speed, halts = (0.2, 0.0), world.halts
    step(world, fallback, n=2)
    assert world.halts == halts + 2 and world.evidence[-1]["zero_since"] is None


def test_the_wall_map_is_not_replaced_while_a_switch_runs():
    world, fallback = make()
    assert fallback.stage().ok
    go_to_switching(world, fallback)
    world.calls.clear()
    reply = fallback.stage()
    assert not reply.ok and reply.code == "SWITCH_RUNNING" and not [c for c in world.calls if c[0].endswith("stage")]


def test_a_core_restart_after_the_switch_keeps_goals_refused_until_a_new_localized_report():
    marker = {"reason": "map_odom_jump", "since": 1000.0}
    world, fallback = make("localization", marker)  # the runtime now reads backend=localization
    assert fallback.enabled and fallback.phase == WAITING and fallback.hold_reason() == "slam_fallback_waiting_pose"
    assert fallback.status()["fallback_active"] is True and fallback.reset() is False
    world.host_phase = {"phase": "SWITCHED"}
    step(world, fallback)
    assert fallback.phase == WAITING  # confirmed, but nothing newer than the confirmation yet
    world.report(Status("LOCALIZED"))
    step(world, fallback)
    assert fallback.phase == ACTIVE and fallback.hold_reason() is None and world.marker == marker
    assert not [c for c in world.calls if c[0].endswith("switch")]


def test_a_restart_that_cannot_reach_the_host_stays_held_even_with_a_localized_report_and_alerts():
    world, fallback = make("localization", {"reason": "x"})
    world.host_replies["navigation_fallback.status"] = HostReply(False, "HOST_AGENT_UNAVAILABLE")
    world.report(Status("LOCALIZED"))
    step(world, fallback, n=int(DECISION_TIMEOUT_S) + 5)
    assert fallback.phase == WAITING and fallback.hold_reason() and fallback.alert
    world.host_replies.clear()
    world.host_phase = {"phase": "SWITCHED"}
    step(world, fallback)
    assert fallback.phase == WAITING  # the host is back and confirms; the old report does not count
    world.report(Status("LOCALIZED"))
    step(world, fallback)
    assert fallback.phase == ACTIVE


def test_a_restart_with_a_host_that_did_not_switch_releases_the_hold_and_forgets_the_marker():
    world, fallback = make("localization", {"reason": "x"})
    world.host_phase = {"phase": "IDLE", "backend": "slam"}  # a person reset the host: no switch is owed
    step(world, fallback)
    assert fallback.phase is None and fallback.enabled is False and fallback.hold_reason() is None and world.marker is None


def test_a_localization_robot_without_a_marker_never_calls_the_host():
    world, fallback = make("localization")
    step(world, fallback, n=5)
    assert fallback.enabled is False and world.calls == []


def test_the_supervisor_thread_ends_when_stopped_and_a_localization_robot_starts_none():
    world, fallback = make()
    fallback.start(0.01)
    thread = fallback._thread
    assert thread is not None and thread.is_alive()
    fallback.stop()
    assert not thread.is_alive()
    inert_world, inert = make("localization")
    inert.start()
    inert.stop()
    assert inert._thread is None


def test_the_marker_is_written_before_the_host_is_asked_to_switch():
    world, fallback = make()
    go_to_switching(world, fallback)
    order = [c[0] for c in world.calls if c[0] in ("marker", "navigation_fallback.switch")]
    assert order == ["marker", "navigation_fallback.switch"] and world.marker["phase"] == SWITCHING


@pytest.mark.parametrize("backend", ["slam", "localization"])
def test_a_core_restart_while_the_switch_unit_runs_keeps_the_hold_until_the_host_says_switched(backend):
    world, fallback = make(backend, {"phase": SWITCHING, "reason": "x"})
    assert fallback.hold_reason() == "slam_fallback_waiting_pose"
    world.host_phase = {"phase": "SWITCHING", "backend": backend}
    world.report(Status("LOCALIZED"))
    step(world, fallback, n=5)
    assert fallback.phase == WAITING and fallback.hold_reason()  # the unit may still commit
    world.host_phase = {"phase": "SWITCHED", "backend": "localization"}
    step(world, fallback)
    assert fallback.phase == WAITING  # the LOCALIZED report above came from the old navigation: it does not count
    world.report(Status("LOCALIZED"))
    step(world, fallback)
    assert fallback.phase == ACTIVE and world.swapped == (1 if backend == "slam" else 0)


@pytest.mark.parametrize("phase", ["FAILED", "ROLLED_BACK", "REFUSED", "IDLE"])
def test_a_restart_releases_the_hold_only_when_the_runtime_is_confirmed_back_on_slam(phase):
    world, fallback = make("localization", {"phase": SWITCHING, "reason": "x"})
    world.host_phase = {"phase": phase, "backend": "localization"}
    step(world, fallback, n=3)
    assert fallback.hold_reason() and world.marker is not None  # the runtime may be on the wall map
    world2, slam = make("slam", {"phase": SWITCHING, "reason": "x"})
    world2.host_phase = {"phase": phase, "backend": "slam"}
    step(world2, slam)
    assert slam.phase == MONITORING and slam.hold_reason() is None and world2.marker is None


def test_a_marker_that_cannot_be_written_keeps_the_robot_stopped_and_starts_no_switch():
    world, fallback = make()
    world.marker_fails = True
    lose(world, fallback)
    stopped_for_a_while(world, fallback)
    assert fallback.phase == STOPPING and fallback.hold_reason() and fallback.alert
    assert not [c for c in world.calls if c[0].endswith("switch")]
    world.marker_fails = False
    step(world, fallback)
    assert fallback.phase == SWITCHING


def test_a_corrupt_or_unreadable_marker_holds():
    world, fallback = make("localization", {"reason": "marker_unreadable"})
    assert fallback.hold_reason()
    world2 = World()
    world2.read_boom = True
    ports = world2.ports()
    ports.read_marker = lambda: (_ for _ in ()).throw(ValueError("corrupt"))
    held = SlamFallback(ports, "localization", clock=lambda: 0.0, wall=lambda: 0.0)
    assert held.hold_reason() == "slam_fallback_waiting_pose"


def test_a_switch_that_finishes_after_the_timeout_still_ends_in_waiting_and_reset_cannot_drop_the_hold():
    world, fallback = make()
    go_to_switching(world, fallback)
    world.host_phase = {"phase": "SWITCHING", "backend": "slam"}
    step(world, fallback, n=100)
    assert fallback.phase == FAILED
    assert fallback.reset() is False and fallback.hold_reason()  # N1: a SWITCHING unit may still commit
    world.host_phase = {"phase": "SWITCHED", "backend": "localization"}
    assert fallback.reset() is False and fallback.hold_reason()  # the runtime is already the wall map
    step(world, fallback, n=6)
    assert fallback.phase == WAITING and fallback.hold_reason() and fallback.reset() is False
