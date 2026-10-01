"""D-395 P2-6 Fleet localization service: poll, arbitrate, post; monitor; ladder (contract §3).

Fake robots and a fake clock; every tick is one 0.5 s poll."""

from __future__ import annotations

import asyncio
import logging
import math
from pathlib import Path

import pytest

from core_common.protocol.localization import CandidateReport, LocState
from fakes import FakeClock, FakeRobot, run
from fleet.localization import cues, service_logic
from fleet.localization.service_logic import Ladder, Monitor
from fleet.server.localization_service import LocalizationService, load_lane_rules
from fleet.swarm.transport import RobotApiError

LANE_RULES = (Path(__file__).resolve().parents[3] / "runtime" / "sensing" / "map" / "map_v2_fleet"
              / "lane_rules.yaml")
A, B = (-1.26, 0.49), (0.86, -0.52)
SLOTS = [cues.Slot(*A, math.pi / 2), cues.Slot(*B, 0.0)]
ON_A = (-1.26, 0.49, -math.pi / 2)
OFF = (-0.9, -0.509, 0.0)


def mirror(pose):
    return (-pose[0], -pose[1], cues.wrap(pose[2] + math.pi))


def report(robot_id, pose, *, stamp=0.0, request_id=None, objects=()):
    """Candidates: the pose and its mirror, equal scan fit (the symmetric track)."""
    return CandidateReport.model_validate({
        "robot_id": robot_id, "request_id": request_id or f"{robot_id}-1", "stamp": stamp,
        "candidates": [dict(zip(("x", "y", "yaw", "scan_fit"), (*p, 0.99))) for p in (pose, mirror(pose))],
        "unmapped_objects": [{"x": x, "y": y} for x, y in objects]})


def state(robot_id, loc_state, frame="map", pose=(0.0, 0.0, 0.0)):
    return {"robot_id": robot_id, "pose": {"x": pose[0], "y": pose[1], "yaw": pose[2]},
            "localization": {"state": loc_state, "pose_frame": frame}}


class FakeSightings:
    def __init__(self, clock):
        self.clock = clock
        self.rows = {}

    def see(self, robot_id, x, y, yaw, age_s=0.1):
        self.rows[robot_id] = {"robot_id": robot_id, "x": x, "y": y, "yaw": yaw,
                               "captured_at": self.clock() - age_s}

    def snapshot(self):
        return {"sightings": list(self.rows.values())}


def service(*robots, clock, **kwargs):
    clients = {r.robot_id: r for r in robots}
    kwargs.setdefault("slots", SLOTS)
    kwargs.setdefault("squares", [A, B])
    return LocalizationService(lambda: clients, clock=clock, wall=clock, **kwargs)


def ticks(svc, clock, seconds):
    for _ in range(int(round(seconds / 0.5))):
        run(svc.tick())
        clock.advance(0.5)


# --- pure pieces ------------------------------------------------------------------------


def test_the_lane_rules_squares_become_slots_with_heading_axes():
    slots, squares = service_logic.parse_reference_squares(load_lane_rules(LANE_RULES))
    assert squares == [A, B]
    assert slots[0] == cues.Slot(*A, math.radians(90.0)) and slots[1] == cues.Slot(*B, 0.0)


def test_a_missing_lane_rules_file_gives_no_squares(tmp_path):
    assert load_lane_rules(tmp_path / "absent.yaml") == {}


def test_disagreement_is_25_cm_or_60_degrees():
    assert not service_logic.disagrees((0, 0, 0), (0.24, 0, None))
    assert service_logic.disagrees((0, 0, 0), (0.26, 0, None))
    assert not service_logic.disagrees((0, 0, 0), (0, 0, math.radians(59)))
    assert service_logic.disagrees((0, 0, 0), (0, 0, math.radians(61)))


def test_the_monitor_counts_two_distinct_disagreeing_reports():
    """S1 finding 7: count reports, not wall-time continuity."""
    m = Monitor()
    assert not m.update("r", [("a", True)], 0.0)
    assert not m.update("r", [("a", True)], 0.5)    # the same report again is not a second one
    assert not m.update("r", [], 3.0)               # a gap in evidence keeps the count
    assert m.update("r", [("b", True)], 5.0)
    assert not m.update("r", [("c", True)], 6.0)    # fired; the count starts again
    assert m.update("r", [("d", True)], 7.0)


def test_an_agreeing_report_between_two_disagreeing_ones_resets_the_count():
    m = Monitor()
    assert not m.update("r", [("a", True)], 0.0)
    assert not m.update("r", [("b", False)], 2.0)
    assert not m.update("r", [("c", True)], 4.0)
    assert m.update("r", [("d", True)], 6.0)


def test_two_disagreeing_reports_more_than_15_s_apart_are_not_enough():
    m = Monitor()
    assert not m.update("r", [("a", True)], 0.0)
    assert not m.update("r", [("b", True)], 15.5)
    assert m.update("r", [("c", True)], 20.0)       # b and c are inside one window


def test_disagreement_wins_over_agreement_in_the_same_tick():
    """Two observers in one poll: a missed mirror lock is worse than a needless SUSPECT."""
    m = Monitor()
    assert not m.update("r", [("a", True), ("b", False)], 0.0)
    assert m.update("r", [("c", True)], 0.5)


def test_forget_drops_the_count():
    m = Monitor()
    assert not m.update("r", [("a", True)], 0.0)
    m.forget("r")
    assert not m.update("r", [("b", True)], 1.0)


def _report_at(objects, observer=None):
    return report("r2", observer or ON_A, objects=objects)


def test_a_peer_is_seen_only_by_an_object_within_25_cm_of_its_reported_pose():
    seen = service_logic.peer_observations(_report_at([(0.5, 0.1)]), ON_A, {"r1": (-1.26, -0.01, 0.0)})
    assert seen["r1"][:2] == pytest.approx((-1.16, -0.01)) and seen["r1"][2] is None
    assert not service_logic.disagrees((-1.26, -0.01, 0.0), seen["r1"])


def test_an_unrelated_object_is_no_evidence_about_a_hidden_peer():
    # The peer is hidden; the only object is 0.8 m away from it and from its mirror.
    assert service_logic.peer_observations(_report_at([(0.3, 0.8)]), ON_A,
                                           {"r1": (-1.26, -0.01, 0.0)}) == {}
    assert service_logic.peer_observations(_report_at([]), ON_A, {"r1": (-1.26, -0.01, 0.0)}) == {}


def test_the_mirror_signature_is_one_object_at_the_mirror_and_none_at_the_reported_pose():
    reported = (1.26, 0.01, math.pi)                     # mirror of (-1.26, -0.01, 0)
    seen = service_logic.peer_observations(_report_at([(0.5, 0.0)]), ON_A, {"r1": reported})
    assert seen["r1"][:2] == pytest.approx((-1.26, -0.01))
    assert service_logic.disagrees(reported, seen["r1"])
    # Two objects at the mirror: ambiguous, no evidence.
    assert service_logic.peer_observations(_report_at([(0.5, 0.0), (0.5, 0.1)]), ON_A,
                                           {"r1": reported}) == {}


def test_the_ladder_rungs_and_their_reset():
    ladder = Ladder()
    assert ladder.update("r", LocState.UNKNOWN, 0.0) is None          # not CANDIDATES yet
    assert ladder.update("r", LocState.CANDIDATES, 1.0) is None
    assert ladder.update("r", LocState.CANDIDATES, 11.0) is None      # exactly 10 s: not yet
    assert ladder.update("r", LocState.CANDIDATES, 11.5) == "rotate"
    assert ladder.update("r", LocState.SUSPECT, 20.0) is None         # a rejection keeps the clock
    assert ladder.update("r", LocState.CANDIDATES, 46.5) == "homing"
    assert ladder.update("r", LocState.CANDIDATES, 121.5) == "needs_human"
    assert ladder.view("r", 121.5)["needs_human"] is True
    assert ladder.update("r", LocState.LOCALIZED, 122.0) is None
    assert ladder.view("r", 122.0)["needs_human"] is False


def test_each_rung_starts_after_the_previous_mission_can_have_ended():
    """Review fix: rotate (sent at 10 s, at most 30 s) ends before homing; homing ends
    before needs_human, so the ladder can complete."""
    rotate_d, rotate_t = service_logic.MISSION_LIMITS["rotate_in_place"]
    lane_d, lane_t = service_logic.MISSION_LIMITS["lane_to_stopline"]
    assert service_logic.LADDER_ROTATE_S + rotate_t < service_logic.LADDER_HOMING_S
    assert service_logic.LADDER_HOMING_S + lane_t < service_logic.LADDER_HUMAN_S


# --- the service ------------------------------------------------------------------------


def test_a_decision_is_posted_once_per_stamp_and_again_for_a_new_stamp():
    clock = FakeClock()
    r1 = FakeRobot("r1", state=state("r1", "CANDIDATES", "odom"))
    r1.candidates = report("r1", ON_A, stamp=1.0)
    svc = service(r1, clock=clock)

    ticks(svc, clock, 5.0)
    assert len(r1.decisions) == 1
    assert r1.decisions[0].candidate_index == 0 and r1.decisions[0].source.value == "candidate"
    assert [c.value for c in r1.decisions[0].cues] == ["slot"]

    r1.candidates = report("r1", ON_A, stamp=3.0)          # the robot re-reports (lost decision)
    ticks(svc, clock, 5.0)
    assert len(r1.decisions) == 2


def test_a_stale_request_is_logged_not_retried(caplog):
    clock = FakeClock()
    r1 = FakeRobot("r1", state=state("r1", "CANDIDATES", "odom"))
    r1.candidates = report("r1", ON_A)
    r1.decision_error = RobotApiError("r1", 409, "STALE_REQUEST", "not the open request")
    svc = service(r1, clock=clock)
    with caplog.at_level(logging.INFO, logger="fleet.localization"):
        ticks(svc, clock, 5.0)
    assert sum(1 for c in r1.calls if c[0] == "localization_decision") == 1
    assert "STALE_REQUEST" in caplog.text


def test_candidates_are_read_only_from_robots_in_candidates():
    clock = FakeClock()
    r1 = FakeRobot("r1", state=state("r1", "LOCALIZED"))
    r2 = FakeRobot("r2", state={"robot_id": "r2", "pose": {"x": 0, "y": 0, "yaw": 0}})   # legacy
    ticks(service(r1, r2, clock=clock), clock, 1.0)
    assert not any(c[0] == "localization_candidates" for c in r1.calls + r2.calls)


def _peer_case(peer_state, peer_frame="map"):
    """'a peer seen where it is' (arbiter case), with the peer reported by a second robot."""
    clock = FakeClock()
    r1 = FakeRobot("r1", state=state("r1", "CANDIDATES", "odom"))
    r1.candidates = report("r1", OFF, objects=[(0.3, 0.9)])
    peer = FakeRobot("r2", state=state("r2", peer_state, peer_frame, pose=(-0.6, 0.391, 0.0)))
    svc = service(r1, peer, clock=clock, slots=(), squares=())
    ticks(svc, clock, 4.0)
    return r1


def test_a_localized_peer_carries_the_decision():
    r1 = _peer_case("LOCALIZED")
    assert len(r1.decisions) == 1 and [c.value for c in r1.decisions[0].cues] == ["peers"]


@pytest.mark.parametrize("peer_state, frame", [("SUSPECT", "map"), ("CANDIDATES", "odom"),
                                                ("LOCALIZED", "odom")])
def test_only_localized_map_frame_peers_are_context(peer_state, frame):
    assert _peer_case(peer_state, frame).decisions == []


class Reporting(FakeRobot):
    """Re-stamps its report on every read with its own clock, `skew_s` off Fleet's (D-395
    rev. 3: the clocks are not synced). `restamp=False`: the re-report stopped arriving."""

    def __init__(self, robot_id, clock, pose, objects, skew_s=0.0, restamp=True):
        super().__init__(robot_id, state=state(robot_id, "CANDIDATES", "odom"))
        self.clock, self.pose, self.objects = clock, pose, objects
        self.skew_s, self.restamp, self._stamp = skew_s, restamp, None

    async def localization_candidates(self):
        self._record("localization_candidates")
        if self.restamp or self._stamp is None:
            self._stamp = self.clock() + self.skew_s
        return report(self.robot_id, self.pose, objects=self.objects, stamp=self._stamp)


def _mirror_locked(clock, objects=((0.5, 0.0),), skew_s=0.0, restamp=True, **kwargs):
    """r1 says it is LOCALIZED at the 180-degree mirror of where it is; r2 on slot A sees it
    0.5 m ahead. With the peers cue, r1's wrong pose would pull r2 to its own mirror."""
    truth = (-1.26, -0.01, 0.0)                          # ON_A faces -y: 0.5 m ahead is here
    reported = (1.26, 0.01, math.pi)
    r1 = FakeRobot("r1", state=state("r1", "LOCALIZED", pose=reported))
    r2 = Reporting("r2", clock, ON_A, list(objects), skew_s, restamp)
    return truth, r1, r2, service(r1, r2, clock=clock, **kwargs)


def test_a_peer_observation_alone_marks_a_mirror_locked_robot_suspect_on_the_second_report():
    clock = FakeClock()
    _, r1, _, svc = _mirror_locked(clock)
    ticks(svc, clock, 0.5)                               # first report
    assert r1.suspects == []
    ticks(svc, clock, 0.5)                               # a second, distinct report
    assert r1.suspects == ["fleet_monitor"]


class Periodic(Reporting):
    """Re-reports only every `period_s` of Fleet time (S1: reports 4-7 s apart at RTF ~0.4)."""

    def __init__(self, *args, period_s, **kwargs):
        super().__init__(*args, **kwargs)
        self.period_s, self._last = period_s, None

    async def localization_candidates(self):
        self._record("localization_candidates")
        if self._last is None or self.clock() - self._last >= self.period_s:
            self._last, self._stamp = self.clock(), self.clock()
        return report(self.robot_id, self.pose, objects=self.objects, stamp=self._stamp)


@pytest.mark.parametrize("period_s", [4.0, 5.5, 7.0])
def test_the_monitor_fires_at_the_s1_report_cadence(period_s):
    """S1 finding 7: twelve disagreeing reports 3.8-6.7 s apart never held 1.5 s of
    continuity. Two distinct fresh reports are enough now."""
    clock = FakeClock()
    truth, r1, _, svc = _mirror_locked(clock)
    r2 = Periodic("r2", clock, ON_A, [(0.5, 0.0)], period_s=period_s)
    svc = service(r1, r2, clock=clock)
    ticks(svc, clock, period_s - 0.5)                    # only the first report so far
    assert r1.suspects == []
    ticks(svc, clock, 1.0)
    assert r1.suspects == ["fleet_monitor"]


def test_an_agreeing_peer_observation_never_marks_suspect():
    clock = FakeClock()
    truth, r1, _, svc = _mirror_locked(clock)
    r1._state = state("r1", "LOCALIZED", pose=truth)
    ticks(svc, clock, 5.0)
    assert r1.suspects == []


def test_a_hidden_peer_and_an_unrelated_object_never_mark_suspect():
    """Review fix: the nearest object used to count as the peer however far away it was."""
    clock = FakeClock()
    truth, r1, _, svc = _mirror_locked(clock, objects=[(0.3, 0.8)])
    r1._state = state("r1", "LOCALIZED", pose=truth)
    ticks(svc, clock, 5.0)
    assert r1.suspects == []


@pytest.mark.parametrize("skew_s", [-3600.0, 3600.0])
def test_a_fresh_report_is_evidence_whatever_the_robot_clock_says(skew_s):
    """Freshness is counted from Fleet's first sighting of the report, never the robot clock."""
    clock = FakeClock()
    _, r1, _, svc = _mirror_locked(clock, skew_s=skew_s)
    ticks(svc, clock, 1.0)                               # two re-stamped reports
    assert r1.suspects == ["fleet_monitor"]


def test_an_unchanged_report_goes_stale_1_s_after_fleet_first_saw_it():
    """Re-fetching the same (request_id, stamp) keeps its first-seen time and counts once:
    a robot whose re-reports stopped arriving gives one report, never the two needed."""
    clock = FakeClock()
    _, r1, _, svc = _mirror_locked(clock, restamp=False)
    ticks(svc, clock, 5.0)
    assert r1.suspects == []


def test_the_overhead_sighting_is_ignored_while_the_flag_is_off():
    clock = FakeClock()
    sightings = FakeSightings(clock)
    r1 = FakeRobot("r1", state=state("r1", "LOCALIZED", pose=(0.0, 0.0, 0.0)))
    svc = service(r1, clock=clock, sightings=sightings)
    for _ in range(8):
        sightings.see("r1", 1.0, 0.0, 0.0)
        ticks(svc, clock, 0.5)
    assert r1.suspects == []
    assert svc.overhead_cue is False


def test_the_overhead_sighting_counts_when_the_flag_is_on_and_only_when_fresh():
    clock = FakeClock()
    sightings = FakeSightings(clock)
    r1 = FakeRobot("r1", state=state("r1", "LOCALIZED", pose=(0.0, 0.0, 0.0)))
    svc = service(r1, clock=clock, sightings=sightings, overhead_cue=True)
    for _ in range(8):
        sightings.see("r1", 1.0, 0.0, 0.0, age_s=0.4)   # older than 300 ms: not a cue
        ticks(svc, clock, 0.5)
    assert r1.suspects == []
    for _ in range(2):
        sightings.see("r1", 0.0, 0.0, math.radians(90))  # fresh, 90 degrees off
        ticks(svc, clock, 0.5)
    assert r1.suspects == ["fleet_monitor"]


def test_one_overhead_sighting_re_read_counts_once():
    clock = FakeClock()
    sightings = FakeSightings(clock)
    r1 = FakeRobot("r1", state=state("r1", "LOCALIZED", pose=(0.0, 0.0, 0.0)))
    svc = service(r1, clock=clock, sightings=sightings, overhead_cue=True)
    sightings.see("r1", 0.0, 0.0, math.radians(90), age_s=0.0)
    ticks(svc, clock, 0.5)
    ticks(svc, clock, 0.5)                               # the same row, 0.5 s old, read again
    assert r1.suspects == []


def test_the_ladder_sends_missions_then_raises_needs_human(caplog):
    clock = FakeClock()
    r1 = FakeRobot("r1", state=state("r1", "CANDIDATES", "odom"))   # no report: never decided
    svc = service(r1, clock=clock)
    with caplog.at_level(logging.INFO, logger="fleet.localization"):
        ticks(svc, clock, 10.0)
        assert svc.view("r1")["rung"] is None and r1.missions == []
        ticks(svc, clock, 1.0)
        assert svc.view("r1")["rung"] == "rotate"
        assert r1.missions == [("rotate_in_place", 0.0, 30.0, None)]
        ticks(svc, clock, 35.0)
        assert svc.view("r1")["rung"] == "homing"
        # No candidate report, so no square target: straight to the lane mission.
        assert r1.missions[1:] == [("lane_to_stopline", 0.6, 40.0, None)]
        assert svc.view("r1")["last_mission"] == {"kind": "lane_to_stopline", "rung": "homing",
                                                  "held": [], "result": "sent"}
        ticks(svc, clock, 75.0)
    assert svc.view("r1")["needs_human"] is True
    assert len(r1.missions) == 2                                    # needs_human sends nothing

    r1._state = state("r1", "LOCALIZED")
    ticks(svc, clock, 0.5)
    assert svc.view("r1")["needs_human"] is False


def test_homing_tries_to_square_first_and_falls_back_when_core_refuses_it():
    clock = FakeClock()
    r1 = FakeRobot("r1", state=state("r1", "CANDIDATES", "odom"))
    r1.candidates = report("r1", OFF)
    r1.decision_error = RobotApiError("r1", 409, "STALE_REQUEST", "keep the ladder running")

    calls = []
    original = r1.localization_mission

    async def mission(kind, **kwargs):
        calls.append(kind)
        if kind == "to_square":
            raise RobotApiError("r1", 409, "unsupported", "follow-up")
        return await original(kind, **kwargs)

    r1.localization_mission = mission
    svc = service(r1, clock=clock)
    ticks(svc, clock, 46.0)
    assert calls == ["rotate_in_place", "to_square", "lane_to_stopline"]
    [lane] = [m for m in r1.missions if m[0] == "lane_to_stopline"]
    assert lane[3] is None                                       # only to_square carries a target
    assert svc.view("r1")["last_mission"]["kind"] == "lane_to_stopline"


def test_the_square_target_is_the_square_nearest_the_first_candidate():
    target = service_logic.square_target(report("r1", OFF), [A, B])
    assert target == {"square": [A[0], A[1]], "candidate_index": 0, "request_id": "r1-1"}
    assert service_logic.square_target(None, [A, B]) is None
    assert service_logic.square_target(report("r1", OFF), []) is None


@pytest.mark.parametrize("code", ["path_not_clear", "localized", "estop", "calibration_lease"])
def test_a_refused_mission_is_recorded_not_retried(code):
    clock = FakeClock()
    r1 = FakeRobot("r1", state=state("r1", "CANDIDATES", "odom"))
    r1.mission_error = RobotApiError("r1", 409, code, "refused")
    svc = service(r1, clock=clock)
    ticks(svc, clock, 12.0)
    assert [m[0] for m in r1.missions] == ["rotate_in_place"]
    assert svc.view("r1")["last_mission"]["result"] == code


def test_legacy_and_localized_robots_never_get_a_mission():
    clock = FakeClock()
    legacy = FakeRobot("r1", state={"robot_id": "r1", "pose": {"x": 0, "y": 0, "yaw": 0},
                                    "localization": None})
    localized = FakeRobot("r2", state=state("r2", "LOCALIZED"))
    svc = service(legacy, localized, clock=clock)
    ticks(svc, clock, 70.0)
    assert legacy.missions == [] and localized.missions == []


def test_traffic_is_held_before_every_mission():
    clock = FakeClock()
    r1 = FakeRobot("r1", state=state("r1", "CANDIDATES", "odom"))
    order = []
    original = r1.localization_mission

    async def hold(robot_id):
        order.append(("hold", robot_id))
        return ["r2"]

    async def mission(kind, **kwargs):
        order.append(("mission", kind))
        return await original(kind, **kwargs)

    r1.localization_mission = mission
    svc = service(r1, clock=clock, traffic_hold=hold)
    ticks(svc, clock, 46.0)
    assert order == [("hold", "r1"), ("mission", "rotate_in_place"),
                     ("hold", "r1"), ("mission", "lane_to_stopline")]
    assert svc.view("r1")["last_mission"]["held"] == ["r2"]


def test_a_failed_traffic_hold_sends_no_mission():
    clock = FakeClock()
    r1 = FakeRobot("r1", state=state("r1", "CANDIDATES", "odom"))

    async def hold(robot_id):
        raise RuntimeError("navigation goal cancellation was not confirmed")

    svc = service(r1, clock=clock, traffic_hold=hold)
    ticks(svc, clock, 12.0)
    assert r1.missions == []
    assert svc.view("r1")["last_mission"]["result"] == "traffic_hold_failed"


def test_an_offline_robot_is_skipped_and_a_removed_one_forgotten():
    clock = FakeClock()
    r1 = FakeRobot("r1", state=state("r1", "CANDIDATES", "odom"))
    r1.state_error = ConnectionError("down")
    clients = {"r1": r1}
    svc = LocalizationService(lambda: clients, clock=clock, wall=clock)
    ticks(svc, clock, 1.0)
    assert svc.view("r1")["rung"] is None
    clients.clear()
    ticks(svc, clock, 0.5)
    assert svc.view("r1") is None


class Hanging(FakeRobot):
    """Never answers the candidates read (a robot whose CORE stalls)."""

    async def localization_candidates(self):
        self._record("localization_candidates")
        await asyncio.Event().wait()


def test_one_hung_robot_does_not_stall_the_others():
    """Review fix: each robot's calls are bounded and run side by side."""
    clock = FakeClock()
    stuck_state = FakeRobot("r0", state=state("r0", "CANDIDATES", "odom"))
    stuck_state.state_gate = asyncio.Event()                 # state() never returns
    stuck_candidates = Hanging("r1", state=state("r1", "CANDIDATES", "odom"))
    ok = FakeRobot("r2", state=state("r2", "CANDIDATES", "odom"))
    ok.candidates = report("r2", ON_A)
    svc = service(stuck_state, stuck_candidates, ok, clock=clock, call_timeout_s=0.05)

    async def drive():
        for _ in range(8):
            await asyncio.wait_for(svc.tick(), 1.0)
            clock.advance(0.5)
    run(drive())

    assert len(ok.decisions) == 1


def test_the_cli_wiring_holds_traffic_through_the_console():
    from types import SimpleNamespace
    from fleet.server.localization_service import build_localization_service

    async def hold(robot_id):
        return []

    console = SimpleNamespace(clients=lambda: {}, hold_for_localization=hold)
    svc = build_localization_service(console, None, lane_rules=LANE_RULES)
    assert svc._traffic_hold is hold


def test_a_busy_refusal_is_retried_on_later_polls():
    """Review fix: homing found the rotate still running; it must go out once CORE is free."""
    clock = FakeClock()
    r1 = FakeRobot("r1", state=state("r1", "CANDIDATES", "odom"))
    r1.mission_error = RobotApiError("r1", 409, "busy", "mission rotate_in_place is running")
    svc = service(r1, clock=clock)
    ticks(svc, clock, 11.0)
    assert [m[0] for m in r1.missions] == ["rotate_in_place"]
    ticks(svc, clock, 1.0)                                    # within the retry interval
    assert len(r1.missions) == 1
    ticks(svc, clock, 2.0)
    assert [m[0] for m in r1.missions] == ["rotate_in_place"] * 2
    r1.mission_error = None
    ticks(svc, clock, 2.5)
    assert svc.view("r1")["last_mission"]["result"] == "sent"
    sent = len(r1.missions)
    ticks(svc, clock, 5.0)
    assert len(r1.missions) == sent                           # accepted: no more retries
