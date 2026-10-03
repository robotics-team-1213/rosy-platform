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
from fleet.server.localization_service import CALL_TIMEOUT_S, LocalizationService, load_lane_rules
from fleet.swarm.transport import RobotApiError

LANE_RULES = ((Path(__file__).resolve().parents[3] / "src") / "runtime" / "sensing" / "map" / "map_v2_fleet"
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
    return report("r2", observer or ON_A, objects=objects).unmapped_objects


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


def test_a_paused_ladder_does_not_count_the_pause():
    """S1 re-run R2/R6: no time counts while a lead is pending or the robot checks."""
    ladder = Ladder()
    assert ladder.update("r", LocState.CANDIDATES, 0.0) is None
    assert ladder.update("r", LocState.CANDIDATES, 5.0) is None
    for t in (5.5, 9.0, 10.5, 15.0):
        assert ladder.update("r", LocState.CANDIDATES, t, paused=True) is None
    assert ladder.holding("r") is True
    assert ladder.update("r", LocState.CANDIDATES, 20.0) is None          # 10 s counted
    assert ladder.holding("r") is False
    assert ladder.update("r", LocState.CANDIDATES, 20.5) == "rotate"


def test_the_pause_is_capped_so_a_stuck_lead_still_reaches_a_human():
    ladder = Ladder()
    ladder.update("r", LocState.CANDIDATES, 0.0)
    rungs = {}
    t = 0.5
    while t <= 200.0:
        rung = ladder.update("r", LocState.CANDIDATES, t, paused=True)
        if rung is not None:
            rungs[rung] = t
        t += 0.5
    cap = service_logic.LADDER_PAUSE_MAX_S
    assert rungs == {"rotate": 10.5 + cap, "homing": 45.5 + cap, "needs_human": 120.5 + cap}
    assert ladder.holding("r") is False


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


RUNNING = {"kind": "rotate_in_place", "state": "running", "reason": None}
DONE = {"kind": "rotate_in_place", "state": "done", "reason": "done"}


def _read(robot):
    """How often the service read the robot's candidates: once per arbitrated poll."""
    return sum(1 for c in robot.calls if c[0] == "localization_candidates")


def test_no_decision_while_a_mission_runs_nor_1_s_after_it_ends():
    """S1 re-run (F1 WSL run): Fleet decided while `rotate_in_place` still turned r2."""
    clock = FakeClock()
    r1 = FakeRobot("r1", state=state("r1", "CANDIDATES", "odom"))
    r1.candidates = report("r1", ON_A, stamp=1.0)
    r1.mission_status = dict(RUNNING)
    svc = service(r1, clock=clock)
    ticks(svc, clock, 5.0)
    assert r1.decisions == [] and _read(r1) == 0

    r1.mission_status = dict(DONE)
    ticks(svc, clock, 1.0)                              # the end is seen at t, quiet at t + 0.5
    assert _read(r1) == 0
    ticks(svc, clock, 0.5)                              # t + 1 s: the arbiter runs again
    assert _read(r1) == 1
    ticks(svc, clock, 2.5)                              # its own 2 s hold, from scratch
    assert len(r1.decisions) == 1


def test_a_core_without_missions_is_never_quiet():
    clock = FakeClock()
    r1 = FakeRobot("r1", state=state("r1", "CANDIDATES", "odom"))
    r1.candidates = report("r1", ON_A, stamp=1.0)
    r1.mission_status_error = RobotApiError("r1", 501, "CAPABILITY_NOT_SUPPORTED", "no missions")
    ticks(service(r1, clock=clock), clock, 2.5)
    assert len(r1.decisions) == 1


def test_an_unreadable_mission_status_skips_that_poll():
    clock = FakeClock()
    r1 = FakeRobot("r1", state=state("r1", "CANDIDATES", "odom"))
    r1.candidates = report("r1", ON_A, stamp=1.0)
    r1.mission_status_error = ConnectionError("unreachable")
    svc = service(r1, clock=clock)
    ticks(svc, clock, 1.0)
    assert _read(r1) == 0
    r1.mission_status_error = None
    ticks(svc, clock, 0.5)
    assert _read(r1) == 1


def test_a_mission_seen_before_candidates_still_quiets_the_first_decision():
    """A SUSPECT robot turns, ends, and reports CANDIDATES within the quiet second."""
    clock = FakeClock()
    r1 = FakeRobot("r1", state=state("r1", "SUSPECT", "odom"))
    r1.mission_status = dict(RUNNING)
    svc = service(r1, clock=clock)
    ticks(svc, clock, 1.0)
    r1.mission_status = dict(DONE)
    r1._state = state("r1", "CANDIDATES", "odom")
    r1.candidates = report("r1", ON_A, stamp=2.0)
    ticks(svc, clock, 1.0)
    assert _read(r1) == 0
    ticks(svc, clock, 0.5)
    assert _read(r1) == 1


def test_localized_robots_are_not_asked_for_their_mission():
    clock = FakeClock()
    r1 = FakeRobot("r1", state=state("r1", "LOCALIZED"))
    ticks(service(r1, clock=clock), clock, 1.0)
    assert not any(c[0] == "localization_mission_status" for c in r1.calls)


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


def test_a_peer_fleet_first_saw_localized_is_not_an_anchor():
    """Unknown provenance (a direct injection, a Fleet or CORE restart): not a peer."""
    assert _peer_case("LOCALIZED").decisions == []


def seen_from(observer, target):
    """`target` (map) as a base_link point of a robot at `observer`."""
    dx, dy = target[0] - observer[0], target[1] - observer[1]
    c, s = math.cos(observer[2]), math.sin(observer[2])
    return (c * dx + s * dy, -s * dx + c * dy)


class Localizing(FakeRobot):
    """CANDIDATES at `pose` with its mirror; accepts a decision and is then LOCALIZED at
    the decided candidate (the robot's 3 s check passes)."""

    def __init__(self, robot_id, pose, objects=(), request_id=None):
        super().__init__(robot_id, state=state(robot_id, "CANDIDATES", "odom"))
        self.candidates = report(robot_id, pose, objects=objects, request_id=request_id)

    async def localization_decision(self, decision):
        out = await super().localization_decision(decision)
        c = self.candidates.candidates[decision.candidate_index]
        self._state = state(self.robot_id, "LOCALIZED", pose=(c.x, c.y, c.yaw))
        self.candidates = None
        return out

    def search(self, pose, objects=(), request_id="again"):
        """Back to CANDIDATES (a pickup) with a new report."""
        self._state = state(self.robot_id, "CANDIDATES", "odom")
        self.candidates = report(self.robot_id, pose, objects=objects, request_id=request_id)


X_OFF = (-0.9, -0.509, 0.0)               # sees A at 1.06 m; its twin is 2.4 m from A
Z_OFF = (0.9, -0.2, math.pi)              # sees X_OFF only (A is 2.27 m away)


def test_an_anchored_chain_localizes_through_peers():
    """slot -> peers from the slot anchor -> peers from that anchor."""
    clock = FakeClock()
    a = Localizing("a", ON_A)
    x = Localizing("x", X_OFF, objects=[seen_from(X_OFF, ON_A)])
    z = Localizing("z", Z_OFF, objects=[seen_from(Z_OFF, X_OFF)])
    svc = service(a, x, z, clock=clock)
    ticks(svc, clock, 15.0)
    assert [[c.value for c in r.decisions[0].cues] for r in (a, x, z)] == [["slot"], ["peers"], ["peers"]]
    assert all(r.decisions[0].candidate_index == 0 for r in (a, x, z))
    assert svc.anchors() == {"a", "x", "z"}


def test_a_robot_that_leaves_localized_loses_its_anchor():
    clock = FakeClock()
    a = Localizing("a", ON_A)
    svc = service(a, clock=clock)
    ticks(svc, clock, 5.0)
    assert svc.anchors() == {"a"}
    a._state = state("a", "SUSPECT", "map", pose=ON_A)
    ticks(svc, clock, 0.5)
    a._state = state("a", "LOCALIZED", pose=ON_A)          # back without a Fleet decision
    x = Localizing("x", X_OFF, objects=[seen_from(X_OFF, ON_A)])
    svc._clients = lambda: {"a": a, "x": x}
    ticks(svc, clock, 5.0)
    assert svc.anchors() == set() and x.decisions == []


def test_an_anchor_whose_pose_jumps_while_localized_loses_its_anchor():
    """A pose injected straight into AMCL keeps the robot LOCALIZED; the jump shows it."""
    clock = FakeClock()
    a = Localizing("a", ON_A)
    svc = service(a, clock=clock)
    ticks(svc, clock, 5.0)
    a._state = state("a", "LOCALIZED", pose=(ON_A[0], ON_A[1] - 0.05, ON_A[2]))   # driving
    ticks(svc, clock, 0.5)
    assert svc.anchors() == {"a"}
    a._state = state("a", "LOCALIZED", pose=mirror(ON_A))
    ticks(svc, clock, 0.5)
    assert svc.anchors() == set()


def test_the_jump_bound_caps_dt_at_1_s_so_a_180_degree_flip_always_counts():
    """S1 run 3 T1: polls 4-10 s apart let a mirror injection pass as motion."""
    before = (0.70, -0.15, 0.0)
    for dt in (0.5, 1.0, 8.0, 60.0):
        assert service_logic.jumped(before, mirror(before), dt)
        assert service_logic.jumped(before, (*before[:2], math.pi), dt)        # turned in place
    assert not service_logic.jumped(before, (0.70, -0.15 + 0.7, 2.4), 60.0)    # under 0.75 m, 2.5 rad
    assert service_logic.jumped(before, (0.70, -0.15 + 0.8, 0.0), 60.0)


def test_the_mirror_signature_is_independent_of_dt():
    before = (0.10, 0.05, 0.3)
    near_twin = (-0.10 + 0.2, -0.05, cues.wrap(0.3 + math.pi + 0.4))
    assert service_logic.mirrored(before, near_twin)
    assert not service_logic.mirrored(before, (-0.10 + 0.35, -0.05, cues.wrap(0.3 + math.pi)))
    assert not service_logic.mirrored(before, (-0.10, -0.05, cues.wrap(0.3 + math.pi + 0.6)))
    assert not service_logic.mirrored(before, before)


def _poll_every(svc, clock, gap_s, polls, move=None):
    for i in range(polls):
        if move is not None:
            move(i)
        run(svc.tick())
        clock.advance(gap_s)


def test_s1_run3_a_mirror_injection_between_8_s_polls_drops_the_anchor():
    """S1 run 3 (c) a2: Fleet polled ~10 s apart under load; the injection stayed an anchor."""
    clock = FakeClock()
    r1, r2, svc = _two_anchors(clock)
    _poll_every(svc, clock, 8.0, 2)                                  # slow polls, standing still
    assert svc.anchors() == {"r1", "r2"}
    r2._state = state("r2", "LOCALIZED", pose=mirror(R2_TRUE))      # the injected fault
    _poll_every(svc, clock, 8.0, 1)
    assert svc.anchors() == {"r1"}


def test_a_genuine_slow_move_at_8_s_polls_loses_the_anchor():
    """Fail safe, documented: 0.8 m between two polls 8 s apart may have been driven, but
    Fleet cannot tell it from a reset, so the robot stops being evidence until it re-localizes."""
    clock = FakeClock()
    a = Localizing("a", ON_A)
    svc = service(a, clock=clock)
    ticks(svc, clock, 5.0)
    assert svc.anchors() == {"a"}
    clock.advance(7.5)
    a._state = state("a", "LOCALIZED", pose=(ON_A[0], ON_A[1] - 0.8, ON_A[2]))   # 0.1 m/s
    ticks(svc, clock, 0.5)
    assert svc.anchors() == set()


def test_a_robot_moving_and_turning_at_normal_polls_keeps_its_anchor():
    clock = FakeClock()
    a = Localizing("a", ON_A)
    svc = service(a, clock=clock)
    ticks(svc, clock, 5.0)

    def drive(i):            # 0.3 m/s and 1.5 rad/s, polled every 0.5 s
        a._state = state("a", "LOCALIZED", pose=(ON_A[0], ON_A[1] - 0.15 * (i + 1),
                                                cues.wrap(ON_A[2] + 0.75 * (i + 1))))
    _poll_every(svc, clock, 0.5, 12, move=drive)
    assert svc.anchors() == {"a"}


def test_a_decision_that_ends_elsewhere_does_not_anchor():
    """LOCALIZED away from the decided pose was not that decision."""
    clock = FakeClock()
    a = Localizing("a", ON_A)
    original = a.localization_decision

    async def decide(decision):
        out = await original(decision)
        a._state = state("a", "LOCALIZED", pose=mirror(ON_A))
        return out

    a.localization_decision = decide
    svc = service(a, clock=clock)
    ticks(svc, clock, 5.0)
    assert len(a.decisions) == 1 and svc.anchors() == set()


R2_TRUE = (-0.70, 0.15, math.pi)          # S1 layout a: off-slot, 0.66 m from r1 on A


def test_s1_a_mirror_locked_peer_gives_its_observer_no_lead():
    """S1 p7a1/p7a3: r2, LOCALIZED by peers from r1, is injected at its twin and stays
    LOCALIZED. r1 is picked up and re-searches; it sees the real r2, which its own twin
    places exactly on r2's mirror-locked pose. Before: twin peers +1 led the slot by 0.5."""
    clock = FakeClock()
    r1 = Localizing("r1", ON_A)
    r2 = Localizing("r2", R2_TRUE, objects=[seen_from(R2_TRUE, ON_A)])
    svc = service(r1, r2, clock=clock)
    ticks(svc, clock, 10.0)
    assert [[c.value for c in r.decisions[0].cues] for r in (r1, r2)] == [["slot"], ["peers"]]
    assert svc.anchors() == {"r1", "r2"}

    r2._state = state("r2", "LOCALIZED", pose=mirror(R2_TRUE))     # the injected fault
    r1.search(ON_A, objects=[seen_from(ON_A, R2_TRUE)])            # the pickup pulse
    ticks(svc, clock, 5.0)
    assert "r2" not in svc.anchors()
    decision = r1.decisions[-1]
    assert len(r1.decisions) == 2 and decision.candidate_index == 0          # the truth
    assert [c.value for c in decision.cues] == ["slot"]
    assert decision.evidence["cues"]["peers"] == 0.0
    assert decision.evidence["totals"][1] == pytest.approx(0.99)           # the twin: scan fit only


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


# --- D-395 rev. 4 §5 follow-up (S1 R1): LOCALIZED anchors observe LOCALIZED robots ----------


class Anchor(Localizing):
    """Localizes through Fleet like `Localizing`; `see()` then puts unmapped objects in its
    LOCALIZED status, re-stamped on every read (2 Hz state) unless `restamp=False`."""

    def __init__(self, robot_id, pose, clock, objects=()):
        super().__init__(robot_id, pose, objects=objects)
        self.clock, self.seeing, self.restamp, self._stamp = clock, None, True, None

    def see(self, objects, restamp=True):
        self.seeing, self.restamp, self._stamp = list(objects), restamp, None

    async def state(self):
        out = await super().state()
        if self.seeing is not None:
            if self.restamp or self._stamp is None:
                self._stamp = self.clock() + 1000.0          # a robot clock, not Fleet's
            out["localization"] = {**out["localization"], "objects_stamp": self._stamp,
                                   "unmapped_objects": [{"x": x, "y": y} for x, y in self.seeing]}
        return out


def _two_anchors(clock):
    """S1 layout a: r1 on square A by `slot`, r2 off-slot by `peers` from r1."""
    r1 = Anchor("r1", ON_A, clock)
    r2 = Anchor("r2", R2_TRUE, clock, objects=[seen_from(R2_TRUE, ON_A)])
    svc = service(r1, r2, clock=clock)
    ticks(svc, clock, 10.0)
    assert svc.anchors() == {"r1", "r2"}
    return r1, r2, svc


def test_an_anchor_marks_a_mirror_injected_anchor_suspect_after_two_polls():
    """S1 (c) while both are LOCALIZED: r2 is injected at its twin (the jump drops its
    anchor); r1 keeps seeing the real r2 and reports it on every state."""
    clock = FakeClock()
    r1, r2, svc = _two_anchors(clock)
    r2._state = state("r2", "LOCALIZED", pose=mirror(R2_TRUE))
    r2.see([seen_from(R2_TRUE, ON_A)])          # placed from its wrong pose: r1's mirror
    r1.see([seen_from(ON_A, R2_TRUE)])
    ticks(svc, clock, 0.5)
    assert svc.anchors() == {"r1"} and r2.suspects == []
    ticks(svc, clock, 0.5)
    assert r2.suspects == ["fleet_monitor"] and r1.suspects == []


def test_a_mirror_locked_non_anchor_cannot_accuse_an_anchor():
    clock = FakeClock()
    r1 = Anchor("r1", ON_A, clock)
    svc = service(r1, clock=clock)
    ticks(svc, clock, 5.0)
    r2 = Anchor("r2", R2_TRUE, clock)
    r2._state = state("r2", "LOCALIZED", pose=mirror(R2_TRUE))     # first seen LOCALIZED
    r2.see([seen_from(R2_TRUE, ON_A)])
    svc._clients = lambda: {"r1": r1, "r2": r2}
    ticks(svc, clock, 5.0)
    assert svc.anchors() == {"r1"} and r1.suspects == []


def test_two_anchors_in_one_poll_count_as_two_observations():
    clock = FakeClock()
    a = Anchor("a", ON_A, clock)
    x = Anchor("x", X_OFF, clock, objects=[seen_from(X_OFF, ON_A)])
    svc = service(a, x, clock=clock)
    ticks(svc, clock, 10.0)
    assert svc.anchors() == {"a", "x"}
    t = FakeRobot("t", state=state("t", "LOCALIZED", pose=mirror(R2_TRUE)))
    a.see([seen_from(ON_A, R2_TRUE)])
    x.see([seen_from(X_OFF, R2_TRUE)])
    svc._clients = lambda: {"a": a, "x": x, "t": t}
    ticks(svc, clock, 0.5)
    assert t.suspects == ["fleet_monitor"] and a.suspects == x.suspects == []


@pytest.mark.parametrize("objects", [[], [(0.3, -0.8)]])
def test_a_hidden_robot_or_an_unrelated_object_gives_no_evidence(objects):
    clock = FakeClock()
    r1, r2, svc = _two_anchors(clock)
    r2._state = state("r2", "LOCALIZED", pose=mirror(R2_TRUE))
    r1.see(objects)
    ticks(svc, clock, 5.0)
    assert r2.suspects == [] and r1.suspects == []


def test_an_agreeing_anchor_observation_never_marks_suspect():
    clock = FakeClock()
    r1, r2, svc = _two_anchors(clock)
    r1.see([seen_from(ON_A, R2_TRUE)])
    r2.see([seen_from(R2_TRUE, ON_A)])
    ticks(svc, clock, 5.0)
    assert r1.suspects == r2.suspects == [] and svc.anchors() == {"r1", "r2"}


def test_a_stale_anchor_status_is_ignored():
    """The same objects_stamp re-read counts once and stops counting 1 s after Fleet first
    saw it: a robot whose state stopped arriving (CORE serves it for 3 s) is no evidence."""
    clock = FakeClock()
    r1, r2, svc = _two_anchors(clock)
    r2._state = state("r2", "LOCALIZED", pose=mirror(R2_TRUE))
    r1.see([seen_from(ON_A, R2_TRUE)], restamp=False)
    ticks(svc, clock, 5.0)
    assert r2.suspects == []


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


def test_a_decision_after_needs_human_clears_the_flag():
    """S1 run 3 T3: needs_human is a flag, not a stop. Fleet keeps arbitrating, and the
    flag (badge "위치 확인 필요") clears once the robot is LOCALIZED."""
    from fleet.localization import trust
    clock = FakeClock()
    r1 = Localizing("r1", ON_A)
    candidates, r1.candidates = r1.candidates, None                 # nothing to decide yet
    svc = service(r1, clock=clock)
    ticks(svc, clock, 121.0)
    assert svc.view("r1")["needs_human"] is True
    assert trust.badge(run(r1.state()), svc.view("r1"))["label"] == trust.NEEDS_HUMAN_LABEL
    r1.candidates = candidates                                       # a slot report arrives
    ticks(svc, clock, 3.0)
    assert [[c.value for c in d.cues] for d in r1.decisions] == [["slot"]]
    ticks(svc, clock, 0.5)
    view = svc.view("r1")
    assert view["needs_human"] is False and view["rung"] is None
    assert trust.badge(run(r1.state()), view)["label"] != trust.NEEDS_HUMAN_LABEL
    assert svc.anchors() == {"r1"}


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


def test_an_unsupported_kind_is_not_asked_again_in_the_same_ladder_episode():
    """S1: while the rotate still ran, Fleet alternated to_square (unsupported) and
    lane_to_stopline (busy) every ~2.4 s. unsupported is final until LOCALIZED."""
    clock = FakeClock()
    r1 = FakeRobot("r1", state=state("r1", "CANDIDATES", "odom"))
    r1.candidates = report("r1", OFF)
    r1.decision_error = RobotApiError("r1", 409, "STALE_REQUEST", "keep the ladder running")
    calls = []
    busy = {"lane": True}
    original = r1.localization_mission

    async def mission(kind, **kwargs):
        calls.append(kind)
        if kind == "to_square":
            raise RobotApiError("r1", 409, "unsupported", "follow-up")
        if kind == "lane_to_stopline" and busy["lane"]:
            raise RobotApiError("r1", 409, "busy", "rotate_in_place is running")
        return await original(kind, **kwargs)

    r1.localization_mission = mission
    svc = service(r1, clock=clock)
    ticks(svc, clock, 46.0)
    assert calls == ["rotate_in_place", "to_square", "lane_to_stopline"]
    ticks(svc, clock, 6.0)                                   # busy retries: the lane mission only
    assert calls.count("to_square") == 1 and calls.count("lane_to_stopline") >= 3
    busy["lane"] = False
    ticks(svc, clock, 2.5)
    assert calls[-1] == "lane_to_stopline" and calls.count("to_square") == 1

    r1._state = state("r1", "LOCALIZED")                     # the episode ends
    ticks(svc, clock, 0.5)
    r1._state = state("r1", "CANDIDATES", "odom")            # a new one tries to_square again
    calls.clear()
    ticks(svc, clock, 46.5)
    assert "to_square" in calls


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


def test_the_default_call_timeout_is_2_5_s_and_hung_robots_wait_side_by_side():
    """S1 run 3 T2: 1 s lost observer evidence under load. Three hung robots still cost one
    timeout per tick, not three, and the healthy robot is read in the same tick."""
    assert CALL_TIMEOUT_S == 2.5
    clock = FakeClock()
    hung = [Hanging(f"h{i}", state=state(f"h{i}", "CANDIDATES", "odom")) for i in range(3)]
    ok = FakeRobot("ok", state=state("ok", "CANDIDATES", "odom"))
    ok.candidates = report("ok", ON_A)
    svc = service(*hung, ok, clock=clock)
    run(asyncio.wait_for(svc.tick(), CALL_TIMEOUT_S + 1.0))
    assert ("localization_candidates",) in ok.calls


class TimingOut(Localizing):
    """CORE takes the decision, but Fleet's call times out (S1 run 3 d3); the robot stays
    in its check until the test moves it."""

    async def localization_decision(self, decision):
        await FakeRobot.localization_decision(self, decision)
        raise asyncio.TimeoutError()


def _unconfirmed(clock):
    r = TimingOut("r", ON_A)
    svc = service(r, clock=clock)
    ticks(svc, clock, 5.0)
    assert len(r.decisions) == 1 and svc.anchors() == set()
    assert svc.view("r")["last_decision"]["result"] == "unreachable"
    return r, svc


def test_an_unconfirmed_decision_the_robot_then_reaches_gives_an_anchor():
    clock = FakeClock()
    r, svc = _unconfirmed(clock)
    r._state = state("r", "LOCALIZED", pose=(ON_A[0] + 0.03, ON_A[1], ON_A[2] + math.radians(3)))
    ticks(svc, clock, 0.5)
    assert svc.anchors() == {"r"}


@pytest.mark.parametrize("pose", [(ON_A[0] + 0.06, ON_A[1], ON_A[2]),
                                  (ON_A[0], ON_A[1], ON_A[2] + math.radians(6)), mirror(ON_A)])
def test_an_unconfirmed_decision_reached_elsewhere_gives_no_anchor(pose):
    clock = FakeClock()
    r, svc = _unconfirmed(clock)
    r._state = state("r", "LOCALIZED", pose=pose)
    ticks(svc, clock, 0.5)
    assert svc.anchors() == set()


def test_an_unconfirmed_decision_reached_after_15_s_gives_no_anchor():
    clock = FakeClock()
    r, svc = _unconfirmed(clock)
    ticks(svc, clock, 15.0)
    r._state = state("r", "LOCALIZED", pose=ON_A)
    ticks(svc, clock, 0.5)
    assert svc.anchors() == set()


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


# --- ladder pauses (S1 re-run R2, R6) ---------------------------------------------------------


def candidates_state(robot_id, request_id, reason=None):
    return {"robot_id": robot_id, "pose": {"x": 0.0, "y": 0.0, "yaw": 0.0},
            "localization": {"state": "CANDIDATES", "pose_frame": "odom", "reason": reason,
                             "request_id": request_id}}


def test_s1_a_lead_pending_at_the_rotate_rung_holds_the_ladder_until_the_decision():
    """S1 re-run R2 timeline: the peer r1 is anchored at 9.0 s, r2's peers lead starts then
    and its 2 s hold ends at 11.0 s. The ladder's rotate rung (> 10 s) must not fire at
    10.5 s; the decision comes at the hold end and no mission is ever sent."""
    clock = FakeClock()
    start = clock()
    r1 = Localizing("r1", ON_A)
    r1._state, r1.candidates = state("r1", "UNKNOWN", "odom"), None
    r2 = Localizing("r2", X_OFF, objects=[seen_from(X_OFF, ON_A)], request_id="r2-1")
    r2._state = candidates_state("r2", "r2-1")
    svc = service(r1, r2, clock=clock)
    ticks(svc, clock, 6.5)
    r1._state = candidates_state("r1", "r1-1")                  # r1's slot report: 6.5 s
    r1.candidates = report("r1", ON_A, request_id="r1-1")
    while clock() - start < 10.75:                              # through the 10.5 s poll
        run(svc.tick())
        clock.advance(0.5)
    assert len(r1.decisions) == 1 and svc.anchors() == {"r1"}
    assert r2.decisions == [] and r2.missions == []
    assert svc.view("r2")["candidates_for_s"] < 10.0            # the pending lead did not count
    run(svc.tick())                                             # 11.0 s: the hold ends
    assert clock() - start == pytest.approx(11.0)
    assert [[c.value for c in d.cues] for d in r2.decisions] == [["peers"]]
    ticks(svc, clock, 2.0)
    assert r2.missions == []


def test_no_ladder_mission_while_the_robot_runs_its_check():
    """S1 re-run R6: d1-d3 started rotate_in_place over a running 3 s check."""
    clock = FakeClock()
    r1 = FakeRobot("r1", state=candidates_state("r1", "r1-1"))
    svc = service(r1, clock=clock)
    ticks(svc, clock, 9.0)
    r1._state = candidates_state("r1", "r1-1", reason="checking")
    ticks(svc, clock, 5.0)
    assert r1.missions == []
    r1._state = candidates_state("r1", "r1-1")                  # rejected: back to searching
    ticks(svc, clock, 1.5)
    assert r1.missions == []                                    # 5 s of checking did not count
    ticks(svc, clock, 0.5)
    assert [m[0] for m in r1.missions] == ["rotate_in_place"]


def test_a_busy_rung_is_not_retried_while_the_robot_checks():
    clock = FakeClock()
    r1 = FakeRobot("r1", state=candidates_state("r1", "r1-1"))
    r1.mission_error = RobotApiError("r1", 409, "busy", "mission rotate_in_place is running")
    svc = service(r1, clock=clock)
    ticks(svc, clock, 11.0)
    assert len(r1.missions) == 1
    r1._state = candidates_state("r1", "r1-1", reason="checking")
    ticks(svc, clock, 5.0)
    assert len(r1.missions) == 1
    r1._state = candidates_state("r1", "r1-1")
    ticks(svc, clock, 0.5)
    assert len(r1.missions) == 2                                # retried once the check is over
