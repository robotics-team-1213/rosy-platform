"""SLAM fallback on the Fleet side: the camera tie-break between mirror twins, and the wall grid push (2026-11-18)."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import math
from types import SimpleNamespace

from core_common.protocol.localization import CandidateReport
from fakes import FakeClock, FakeRobot, run
from fleet.localization import wall_tiebreak
from fleet.localization.wall_tiebreak import Tiebreak
from fleet.server.localization_service import LocalizationService
from fleet.server.wall_map_sync import RETRY_S, WallMapSync

A = (-1.0, 0.5, 0.0)
MIRROR = (1.0, -0.5, math.pi)


def report(poses=(A, MIRROR), fits=(0.99, 0.99), stamp=1.0, request_id="r1-1"):
    return CandidateReport.model_validate({
        "robot_id": "r1", "request_id": request_id, "stamp": stamp,
        "candidates": [dict(zip(("x", "y", "yaw", "scan_fit"), (*p, f))) for p, f in zip(poses, fits)]})


def decide(rep, camera, tie=None, start=0.0, hold=wall_tiebreak.HOLD_S):
    tie = tie or Tiebreak()
    assert tie.observe(rep, camera, start) is None  # the hold has not passed yet
    return tie.observe(rep, camera, start + hold + 0.1)


def test_the_camera_breaks_a_tie_between_mirror_twins_after_the_hold():
    decision = decide(report(), (-0.9, 0.4))
    assert decision.source.value == "overhead" and [c.value for c in decision.cues] == ["overhead"]
    assert (decision.pose.x, decision.pose.y, decision.pose.yaw) == A and decision.request_id == "r1-1"
    assert decide(report(), (0.9, -0.4)).pose.x == 1.0  # the other twin when the camera is there


def test_no_fresh_sighting_means_no_decision():
    assert decide(report(), None) is None


def test_twins_that_do_not_fit_the_scan_well_are_not_decided_by_the_camera():
    assert decide(report(fits=(0.80, 0.80)), (-0.9, 0.4)) is None  # two poor, similar candidates: below loc_assist's own floor
    assert decide(report(fits=(wall_tiebreak.MIN_FIT, wall_tiebreak.MIN_FIT)), (-0.9, 0.4)) is not None


def test_candidates_that_are_not_mirror_twins_are_not_the_cameras_to_choose():
    near_yaw = ((-1.0, 0.5, 0.0), (1.0, -0.5, 0.3))
    assert decide(report(near_yaw), (-0.9, 0.4)) is None
    close = ((-1.0, 0.5, 0.0), (-0.5, 0.5, math.pi))  # 0.5 m apart: one place, not two
    assert decide(report(close), (-0.9, 0.4)) is None
    assert decide(report(fits=(0.99, 0.7)), (-0.9, 0.4)) is None  # the second is no twin: a worse fit


def test_a_camera_that_is_not_clearly_near_one_twin_decides_nothing():
    assert decide(report(), (0.0, 0.0)) is None      # between them
    assert decide(report(), (-1.0, 1.4)) is None     # too far from both
    assert decide(report(), (-0.1, 0.5)) is None     # near neither enough, and not by margin


def test_the_lead_must_hold_on_the_same_twin_and_a_request_is_decided_once():
    tie = Tiebreak()
    assert tie.observe(report(), (-0.9, 0.4), 0.0) is None
    assert tie.observe(report(), (0.9, -0.4), 1.5) is None   # the camera changed its mind: the hold restarts
    assert tie.observe(report(), (0.9, -0.4), 3.0) is None
    first = tie.observe(report(), (0.9, -0.4), 3.7)
    assert first is not None and tie.observe(report(), (0.9, -0.4), 9.0) is None  # once per (request, stamp)
    assert tie.observe(report(stamp=2.0), (0.9, -0.4), 10.0) is None  # a new stamp starts a new hold
    assert tie.observe(report(stamp=2.0), (0.9, -0.4), 12.3) is not None


class Sightings:
    def __init__(self, clock):
        self.clock, self.rows = clock, {}

    def see(self, x, y):
        self.rows["r1"] = {"robot_id": "r1", "x": x, "y": y, "yaw": 0.0, "captured_at": self.clock()}

    def snapshot(self):
        return {"sightings": list(self.rows.values())}


def robot(phase):
    state = {"robot_id": "r1", "pose": {"x": 0.0, "y": 0.0, "yaw": 0.0},
             "localization": {"state": "CANDIDATES", "pose_frame": "odom", "request_id": "r1-1"}}
    if phase is not None:
        state["slam_fallback"] = {"phase": phase, "fallback_active": phase in ("WAITING_LOCALIZATION", "ACTIVE")}
    r = FakeRobot("r1", state=state)
    r.candidates = report()
    return r


def service(r, clock, sightings):
    # No slots and no squares: no scan cue can separate the twins, which is exactly the fallback situation.
    return LocalizationService(lambda: {"r1": r}, slots=[], squares=[], sightings=sightings, clock=clock, wall=clock)


def ticks(svc, clock, seconds):
    for _ in range(int(round(seconds / 0.5))):
        run(svc.tick())
        clock.advance(0.5)


def test_after_the_fallback_switch_the_camera_decides_even_with_the_d257_overhead_cue_off():
    clock = FakeClock()
    r, seen = robot("WAITING_LOCALIZATION"), Sightings(clock)
    svc = service(r, clock, seen)
    for _ in range(12):
        seen.see(-0.9, 0.4)
        ticks(svc, clock, 0.5)
    assert len(r.decisions) == 1 and r.decisions[0].source.value == "overhead"
    assert (r.decisions[0].pose.x, r.decisions[0].pose.y) == (-1.0, 0.5)


def test_only_while_waiting_for_the_first_pose_and_only_with_a_sighting_is_anything_decided():
    clock = FakeClock()
    for phase in (None, "MONITORING", "ACTIVE"):  # never once the robot has its pose (ACTIVE), never on a healthy SLAM robot
        r, seen = robot(phase), Sightings(clock)
        svc = service(r, clock, seen)
        for _ in range(12):
            seen.see(-0.9, 0.4)
            ticks(svc, clock, 0.5)
        assert r.decisions == []
    r, seen = robot("WAITING_LOCALIZATION"), Sightings(clock)
    ticks(service(r, clock, seen), clock, 8.0)
    assert r.decisions == []


# --- the wall grid push ------------------------------------------------------------------------


def site(map_id="site-a", version=3):
    walls = [SimpleNamespace(face=((0.0, 0.0), (2.0, 0.0))), SimpleNamespace(face=((2.0, 0.0), (2.0, 1.0))),
             SimpleNamespace(face=((2.0, 1.0), (0.0, 1.0))), SimpleNamespace(face=((0.0, 1.0), (0.0, 0.0)))]
    return SimpleNamespace(active=lambda: (version, SimpleNamespace(map_id=map_id, walls=walls)))


class Client:
    def __init__(self, fail=False):
        self.pushed, self.fail = [], fail

    async def slam_fallback_wall_map(self, payload):
        if self.fail:
            raise RuntimeError("refused")
        self.pushed.append(payload)
        return {"staged": True}


def fallback_state(staged_sha=None):
    return {"slam_fallback": {"phase": "MONITORING", "wall_map": None if staged_sha is None else {"sha256": staged_sha}}}


def test_the_grid_goes_only_to_slam_fallback_robots_and_the_robot_can_verify_its_sha():
    now = [0.0]
    a, b = Client(), Client()
    sync = WallMapSync(site(), lambda: {"a": a, "b": b}, lambda: now[0])
    run(sync.sync({"a": fallback_state(), "b": {"localization": {}}}))
    assert len(a.pushed) == 1 and b.pushed == []
    payload = a.pushed[0]
    assert payload["map_id"] == "site-a" and payload["version"] == 3
    assert hashlib.sha256(base64.b64decode(payload["pgm_base64"])).hexdigest() == payload["sha256"]
    assert len(payload["origin"]) == 3 and payload["resolution"] > 0


def test_a_robot_that_already_holds_the_current_grid_gets_nothing_and_a_retry_waits():
    now = [0.0]
    c = Client()
    sync = WallMapSync(site(), lambda: {"a": c}, lambda: now[0])
    sha = sync.artifact()["sha256"]
    run(sync.sync({"a": fallback_state(sha)}))
    assert c.pushed == []
    run(sync.sync({"a": fallback_state("0" * 64)}))
    run(sync.sync({"a": fallback_state("0" * 64)}))
    assert len(c.pushed) == 1                       # not again inside RETRY_S
    now[0] = RETRY_S + 1
    run(sync.sync({"a": fallback_state("0" * 64)}))
    assert len(c.pushed) == 2


def test_one_refusing_robot_does_not_stop_the_others_and_a_changed_map_is_rebuilt():
    now = [0.0]
    bad, good = Client(fail=True), Client()
    sync = WallMapSync(site(), lambda: {"a": bad, "b": good}, lambda: now[0])
    run(sync.sync({"a": fallback_state(), "b": fallback_state()}))
    assert len(good.pushed) == 1
    first = sync.artifact()["sha256"]
    sync._site_maps = site(version=4)
    assert sync.artifact()["version"] == 4 and sync.artifact()["sha256"] == first  # same walls, same bytes


def test_no_active_site_map_or_no_walls_pushes_nothing():
    c = Client()
    none = SimpleNamespace(active=lambda: None)
    run(WallMapSync(none, lambda: {"a": c}, lambda: 0.0).sync({"a": fallback_state()}))
    empty = SimpleNamespace(active=lambda: (1, SimpleNamespace(map_id="m", walls=[])))
    run(WallMapSync(empty, lambda: {"a": c}, lambda: 0.0).sync({"a": fallback_state()}))
    assert c.pushed == []
