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
    state = {"robot_id": "r1", "map_grid_id": "occupancy:123456789012",
             "pose": {"x": 0.0, "y": 0.0, "yaw": 0.0},
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


def test_tiebreak_camera_callback_resolves_led_fallback_and_shared_site_map_amcl():
    def run_case(*, phase, map_id, active_map="site-a", cam_xy=(-0.9, 0.4)):
        clock = FakeClock()
        r = robot(phase)
        if map_id is not None:
            r._state["map_id"] = map_id
        svc = LocalizationService(lambda: {"r1": r}, slots=[], squares=[], sightings=None, clock=clock, wall=clock)
        svc.set_active_map_id(lambda: active_map)
        svc.set_tiebreak_camera(lambda rid, m: cam_xy if (rid == "r1" and m == active_map) else None)
        ticks(svc, clock, 3.0)
        return r.decisions

    d_wait = run_case(phase="WAITING_LOCALIZATION", map_id="wall-local")
    assert len(d_wait) == 1 and d_wait[0].evidence.get("tiebreak") == "twin"
    assert (d_wait[0].pose.x, d_wait[0].pose.y) == (-1.0, 0.5)

    d_amcl = run_case(phase=None, map_id="site-a")
    assert len(d_amcl) == 1 and d_amcl[0].evidence.get("tiebreak") == "twin"
    assert (d_amcl[0].pose.x, d_amcl[0].pose.y) == (-1.0, 0.5)

    assert run_case(phase=None, map_id="wrong-map") == []
    assert run_case(phase=None, map_id=None) == []
    for bad_phase in ("MONITORING", "ACTIVE", "STOPPING", "SWITCHING", "FAILED"):
        assert run_case(phase=bad_phase, map_id="site-a") == []


def test_shared_map_twin_tiebreak_anchors_first_pinky_to_localize_peer_by_unmapped_objects():
    class SharedMapRobot(FakeRobot):
        async def localization_decision(self, decision) -> dict:
            out = await super().localization_decision(decision)
            pose = (
                decision.pose
                if decision.pose is not None
                else self.candidates.candidates[decision.candidate_index]
            )
            self._state = {
                "robot_id": self.robot_id,
                "map_id": self._state.get("map_id"),
                "map_grid_id": self._state["map_grid_id"],
                "pose": {"x": pose.x, "y": pose.y, "yaw": pose.yaw},
                "localization": {"state": "LOCALIZED", "pose_frame": "map", "request_id": None},
            }
            return out

    clock = FakeClock()
    r1 = SharedMapRobot("r1", state={
        "robot_id": "r1", "map_id": "site-a", "map_grid_id": "occupancy:123456789012",
        "pose": {"x": 0.0, "y": 0.0, "yaw": 0.0},
        "localization": {"state": "CANDIDATES", "pose_frame": "odom", "request_id": "r1-1"},
    })
    r1.candidates = report()

    r2 = SharedMapRobot("r2", state={
        "robot_id": "r2", "map_id": "site-a", "map_grid_id": "occupancy:123456789012",
        "pose": {"x": 0.0, "y": 0.0, "yaw": 0.0},
        "localization": {"state": "CANDIDATES", "pose_frame": "odom", "request_id": "r2-1"},
    })
    r2.candidates = CandidateReport.model_validate({
        "robot_id": "r2", "request_id": "r2-1", "stamp": 1.0,
        "candidates": [
            {"x": -1.0, "y": 1.5, "yaw": 0.0, "scan_fit": 0.99},
            {"x": 1.0, "y": -1.5, "yaw": math.pi, "scan_fit": 0.99},
        ],
        "unmapped_objects": [{"x": 0.0, "y": -1.0}],
    })

    svc = LocalizationService(
        lambda: {"r1": r1, "r2": r2}, slots=[], squares=[], sightings=None, clock=clock, wall=clock,
    )
    svc.set_active_map_id(lambda: "site-a")
    svc.set_tiebreak_camera(lambda rid, m: (-0.9, 0.4) if (rid == "r1" and m == "site-a") else None)

    ticks(svc, clock, 8.0)

    assert len(r1.decisions) == 1
    assert r1.decisions[0].evidence.get("tiebreak") == "twin"
    assert len(r2.decisions) == 1
    assert [c.value for c in r2.decisions[0].cues] == ["peers"]
    assert r2.decisions[0].candidate_index == 0
    assert svc.anchors() == {"r1", "r2"}


def test_tiebreak_rejects_three_candidates_wrong_map_sighting_and_tracks_unconfirmed_or_refusal():
    from fleet.server.auto_locate_service import AutoLocateService
    from fleet.swarm.transport import RobotApiError

    three = report(poses=(A, MIRROR, (0.0, 2.0, 1.0)), fits=(0.99, 0.99, 0.90))
    assert decide(three, (-0.9, 0.4)) is None
    assert decide(report(fits=(0.95, 0.84)), (-0.9, 0.4)) is None

    # Wrong-map sighting does not shadow AutoLocateService.tiebreak_camera_xy on the active site map.
    clock = FakeClock()
    r = robot(None)
    r._state["map_id"] = "site-a"
    wrong_sightings = SimpleNamespace(snapshot=lambda: {"sightings": [{
        "robot_id": "r1", "map_id": "site-b", "x": 0.9, "y": -0.4, "yaw": math.pi, "captured_at": clock(),
    }]})
    identity = SimpleNamespace(confirmed_track_pose=lambda rid: {
        "state": "CONFIRMED", "mode": "led", "x": -0.9, "y": 0.4, "yaw": 0.0,
        "age_s": 0.1, "source_id": "cam-1", "map_id": "site-a",
    })
    tracking = SimpleNamespace(identity=identity, sources=[], source_fps=lambda sid: 10.0)
    map_pose = SimpleNamespace(config=SimpleNamespace(track_modes=("led",)), active_map_id=lambda: "site-a")
    auto_loc = AutoLocateService(tracking, map_pose=map_pose, clock=clock)
    svc = LocalizationService(lambda: {"r1": r}, slots=[], squares=[], sightings=wrong_sightings,
                              clock=clock, wall=clock)
    svc.set_active_map_id(map_pose.active_map_id)
    svc.set_tiebreak_camera(auto_loc.tiebreak_camera_xy)
    ticks(svc, clock, 3.0)
    assert len(r.decisions) == 1 and (r.decisions[0].pose.x, r.decisions[0].pose.y) == (-1.0, 0.5)

    # RobotApiError refusal must not anchor even if the robot later reports LOCALIZED on its own.
    c_err = FakeClock()
    r_err = robot(None)
    r_err._state["map_id"] = "site-a"
    r_err.decision_error = RobotApiError("r1", 409, "NO_ASYMMETRIC_CUE", "rejected")
    svc_err = LocalizationService(lambda: {"r1": r_err}, slots=[], squares=[], sightings=None, clock=c_err, wall=c_err)
    svc_err.set_active_map_id(lambda: "site-a")
    svc_err.set_tiebreak_camera(lambda rid, m: (-0.9, 0.4) if m == "site-a" else None)
    ticks(svc_err, c_err, 3.0)
    r_err._state = {"robot_id": "r1", "map_id": "site-a", "map_grid_id": "occupancy:123456789012",
                    "pose": {"x": -1.0, "y": 0.5, "yaw": 0.0},
                    "localization": {"state": "LOCALIZED", "pose_frame": "map"}}
    ticks(svc_err, c_err, 0.5)
    assert svc_err.anchors() == set()

    # Timed-out twin tiebreak remains unconfirmed and still anchors once robot reaches that pose.
    c_to = FakeClock()
    r_to = robot(None)
    r_to._state["map_id"] = "site-a"
    r_to.decision_error = asyncio.TimeoutError()
    svc_to = LocalizationService(lambda: {"r1": r_to}, slots=[], squares=[], sightings=None, clock=c_to, wall=c_to)
    svc_to.set_active_map_id(lambda: "site-a")
    svc_to.set_tiebreak_camera(lambda rid, m: (-0.9, 0.4) if m == "site-a" else None)
    ticks(svc_to, c_to, 3.0)
    r_to._state = {"robot_id": "r1", "map_id": "site-a", "map_grid_id": "occupancy:123456789012",
                    "pose": {"x": -1.0, "y": 0.5, "yaw": 0.0},
                    "localization": {"state": "LOCALIZED", "pose_frame": "map"}}
    ticks(svc_to, c_to, 0.5)
    assert svc_to.anchors() == {"r1"}


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


def test_unique_candidate_corroboration_and_cross_frame_bound_tiebreak():
    from fleet.localization.map_binding import Fit
    from fleet.server.site_map_store import SiteMapStore

    single = report(poses=(A,), fits=(0.91,))
    assert decide(single, (-0.9, 0.4)) is not None
    assert decide(single, (-0.9, 0.4)).evidence.get("tiebreak") == "unique"
    # Too far from overhead camera (> 0.35 m) -> rejected
    assert decide(single, (-0.55, 0.5)) is None
    # Below MIN_FIT -> rejected
    assert decide(report(poses=(A,), fits=(0.84,)), A[:2]) is None
    # Three candidates remain rejected
    assert decide(report(poses=(A, MIRROR, (0.0, 2.0, 1.0)), fits=(0.99, 0.99, 0.90)), (-0.9, 0.4)) is None

    # Cross-frame tiebreak: robot holds its own occupancy grid while overhead sees active site coords
    fit_truth = Fit(math.radians(90.0), 1.5, -0.5, ())
    store = SiteMapStore()
    site_map = SimpleNamespace(active=lambda: (4, SimpleNamespace(map_id="site-a")), map_bindings=store.map_bindings)
    site_pts = [(-1.0, -0.5), (1.0, -0.5), (0.9, 0.45), (-0.6, 0.4)]
    pairs = [{"site": list(p), "robot": list(fit_truth.inverse(p))} for p in site_pts]
    holdout = [{"site": list((0.0, 0.0)), "robot": list(fit_truth.inverse((0.0, 0.0)))}]
    grid_id = "occupancy:crossframe1"
    store.map_bindings.approve(
        "r1", {"map_id": "robot_map", "map_grid_id": grid_id,
               "localization": {"state": "LOCALIZED", "pose_frame": "map"}},
        ("site-a", 4), pairs, holdout, "op",
    )

    clock = FakeClock()
    r = FakeRobot("r1", {"robot_id": "r1", "map_id": "robot_map", "map_grid_id": grid_id,
                         "pose": {"x": 0.0, "y": 0.0, "yaw": 0.0},
                         "localization": {"state": "CANDIDATES", "pose_frame": "odom"}},
                  reports=[report(poses=(A, MIRROR), fits=(0.99, 0.99))])
    r.decisions = []

    async def _post(decision):
        r.decisions.append(decision)
        return {"accepted": True}

    r.localization_decision = _post
    svc = LocalizationService(lambda: {"r1": r}, slots=[], squares=[], sightings=None, clock=clock, wall=clock)
    svc.set_active_map_id(lambda: "site-a")
    svc.set_site_maps(site_map)
    cam_site = fit_truth.apply((-0.9, 0.4))
    svc.set_tiebreak_camera(lambda rid, m: cam_site if (rid == "r1" and m == "site-a") else None)
    ticks(svc, clock, 3.0)
    assert len(r.decisions) == 1
    assert (r.decisions[0].pose.x, r.decisions[0].pose.y, r.decisions[0].pose.yaw) == A
    assert svc.anchors() == {"r1"}
