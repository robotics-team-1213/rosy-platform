"""The bay pose by LiDAR against the dock's stored seated scan (bay_scan_pose.py, bay_zone.scan_geometry).

Real y8xs scans (2026-11-20, data_y8xs_bay_scans.json): the seated reference, the robot 0.084 m out and turned 21 deg
(measured by the evaluator's ICP), and a sideways wrong fit. The zone check takes the scan pose only when it is
good; the map path stays for everything else."""

from __future__ import annotations

import json
import math
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.bridge.observation import bay_body_scan
from core_common.protocol.schemas import DockState
from core_common.robot_body import PINKY_PRO
from core_features.docking.bay_scan_pose import BayScanPose, locate
from core_features.docking.bay_zone import classify, scan_geometry
from core_features.docking.detector import DockObservation
from core_features.docking.model import DockingConfig, DockPhase
from test_docking_bay import a_bay, done
from test_docking_bay_zone import a_row, moved, run_row

SCANS = json.loads((Path(__file__).parent / "data_y8xs_bay_scans.json").read_text())
CFG = DockingConfig()


def pts(name):
    return PINKY_PRO.scan_view(SCANS[name], forward_deg=180.0).points


def good(**kw):
    args = dict(x=0.15, y=0.0, heading=0.0, inliers=0.95, margin=0.5, median_m=0.002)
    args.update(kw)
    return BayScanPose(**args)


@pytest.mark.parametrize("other_x", [0.1, 0.4])
def test_simultaneous_grid_builds_keep_the_reference_requested_by_each_matcher(monkeypatch, other_x):
    from concurrent.futures import ThreadPoolExecutor
    from core_features.docking import bay_scan_pose
    pytest.importorskip("numpy")
    started, release = threading.Event(), threading.Event()
    local = threading.local()

    class Field:
        def __init__(self, ref):
            self.ref = ref
            if getattr(local, "slow", False):
                started.set()
                assert release.wait(5)

    def icp(cur, field, *args):
        return float(field.ref[0][0]), 0.0, 0.0, 0.9, 0.001

    monkeypatch.setattr(bay_scan_pose, "_FIELD", (None, None))
    monkeypatch.setattr(bay_scan_pose, "_Field", Field)
    monkeypatch.setattr(bay_scan_pose, "_icp", icp)
    def slow_match():
        local.slow = True
        return locate([(0.1, 0.0)] * 45, [(0.1, 0.0)] * 45)
    with ThreadPoolExecutor(max_workers=2) as workers:
        slow = workers.submit(slow_match)
        try:
            assert started.wait(2)
            points = [(other_x, 0.0)] * 45
            fast = workers.submit(bay_scan_pose.locate_track, points, points, (0., 0., 0.))
            assert fast.result(timeout=2).x == pytest.approx(other_x)
        finally:
            release.set()
        assert slow.result(timeout=2).x == pytest.approx(0.1)
    assert bay_scan_pose.locate_near(points, points, (0., 0., 0.)).x == pytest.approx(other_x)


def test_the_seated_scan_matches_itself_at_the_origin():
    m = locate(pts("seated"), pts("seated"))
    assert m is not None and m.inliers >= 0.95 and m.margin >= 0.4
    assert abs(m.x) < 0.01 and abs(m.y) < 0.01 and abs(m.heading) < math.radians(2.0)


def test_another_bays_robot_scan_never_passes_against_this_bays_reference():
    # L1: b8xy (rosy_46) standing in its own bay C1 against the y8xs C2 reference: panel B measured inliers 0.37 margin
    # 0.01 with the first matcher; the grid matcher gives about the same. Wrong bay = refused, with the heading cap off.
    loose = DockingConfig(bay_scan_heading_max_rad=10.0)
    m = locate(pts("seated"), pts("neighbour_b8xy_c1"))
    assert m is not None
    assert m.inliers < loose.bay_scan_inlier_min and m.margin < loose.bay_scan_margin_min, m
    assert scan_geometry(m, 0.32, loose) is None


# L3: the grid matcher on real y8xs scans against the evaluator's ICP poses (loop/scans manifest). Lateral only reached
# -0.006..+0.022 m (the lateral moves timed out), so lateral is not exercised beyond that. Pass/refuse at the thresholds
# (inliers 0.70, margin 0.40, |y| 0.11, heading 45): every true fit passes except the farthest (x 0.31: inliers 0.71, margin 0.26),
# which falls back to the map path / the corridor-only stop; the lowest passing margin is 0.40 (x 0.21, heading -10.8).
GRID = json.loads((Path(__file__).parent / "data_y8xs_bay_grid.json").read_text())["scans"]
REFUSED_AT_X31 = {"g_x31_yp4_h0.json"}


@pytest.mark.parametrize("name", sorted(GRID))
def test_the_grid_matcher_agrees_with_the_evaluator_icp_and_the_thresholds_split_as_tabled(name):
    entry = GRID[name]
    scan = PINKY_PRO.scan_view(entry["scan"], forward_deg=180.0).points
    m = locate(pts("seated"), scan)
    pose = entry["pose"]
    assert m.x == pytest.approx(pose["x"], abs=0.01)
    assert m.y == pytest.approx(pose["y"], abs=0.02)             # up to 15 mm apart on the same stand
    assert math.degrees(m.heading) == pytest.approx(pose["th_deg"], abs=3.0)
    assert (scan_geometry(m, 0.32, CFG) is None) == (name in REFUSED_AT_X31), (name, m)


def test_a_robot_out_of_the_bay_is_measured_in_the_bay_frame():
    m = locate(pts("seated"), pts("near"))
    # the evaluator's ICP on the same scans: x 0.084 y -0.016 heading 20.7 deg
    assert m.x == pytest.approx(0.084, abs=0.015) and m.y == pytest.approx(-0.016, abs=0.015)
    assert math.degrees(m.heading) == pytest.approx(20.8, abs=1.5)
    assert m.inliers >= CFG.bay_scan_inlier_min and m.margin >= CFG.bay_scan_margin_min
    assert scan_geometry(m, 0.32, CFG) is not None


def test_a_sideways_wrong_fit_is_not_trusted():
    m = locate(pts("seated"), pts("sideways"))
    assert m is not None and scan_geometry(m, 0.32, CFG) is None


def test_the_margin_alone_refuses_the_sideways_wrong_fit_and_keeps_every_true_one():
    # the heading cap is off here: only inliers and margin decide (panel B, aea665322c: the grid matcher gave 0.27)
    loose = DockingConfig(bay_scan_heading_max_rad=10.0)
    wrong = locate(pts("seated"), pts("sideways"))
    assert wrong.inliers >= loose.bay_scan_inlier_min and wrong.margin < loose.bay_scan_margin_min
    assert scan_geometry(wrong, 0.32, loose) is None
    for name in ("seated", "near"):
        m = locate(pts("seated"), pts(name))
        assert m.margin >= loose.bay_scan_margin_min and scan_geometry(m, 0.32, loose) is not None, (name, m)


@pytest.mark.parametrize("change", [
    dict(inliers=0.69), dict(margin=0.24), dict(y=0.12), dict(y=-0.12), dict(heading=0.8), dict(x=0.32), dict(x=0.5),
    dict(inliers=float("nan")),
])
def test_scan_geometry_refuses_a_weak_or_out_of_lane_match(change):
    assert scan_geometry(good(**change), 0.32, CFG) is None
    assert scan_geometry(None, 0.32, CFG) is None


def test_scan_geometry_turns_the_bay_frame_into_the_dock_frame():
    # bay frame y is the seated robot's left; the dock's lateral has the opposite sign
    along, lateral, heading = scan_geometry(good(x=0.2, y=-0.034, heading=0.05), 0.32, CFG)
    assert (along, lateral, heading) == pytest.approx((0.2, 0.034, 0.05))


def _obs(lateral, heading=0.0, measured=True):
    """base_link stop-face observation of a robot nose-out at the given lateral (dock frame) and heading."""
    yaw = math.pi - heading
    ax, ay = math.cos(yaw), math.sin(yaw)
    along = 0.15
    # rear_errors: along = x ax + y ay, lateral = ay x - ax y  ->  solve for x, y
    return DockObservation(x=along * ax + lateral * ay, y=along * ay - lateral * ax, yaw=yaw,
                           confidence=0.9, at=0.0, lateral_measured=measured)


def test_a_measured_line_lateral_must_agree_with_the_scan_lateral():
    scan = (0.15, 0.0, 0.0)
    assert classify(None, None, 0.32, _obs(0.02), CFG, scan).kind in ("acquire", "exit")
    refused = classify(None, None, 0.32, _obs(0.10), CFG, scan)
    assert refused.kind == "manual" and "disagree (lateral scan" in refused.reason


def test_a_corridor_only_frame_gives_the_heading_only_never_a_filled_lateral():
    scan = (0.15, 0.0, 0.0)
    # the lateral CORE filled (here 0.10, from a stale map) is not compared: heading agrees, lateral is the scan's
    assert classify(None, None, 0.32, _obs(0.10, measured=False), CFG, scan).kind in ("acquire", "exit")
    refused = classify(None, None, 0.32, _obs(0.10, heading=0.3, measured=False), CFG, scan)
    assert refused.kind == "manual" and "disagree" in refused.reason


def test_a_dock_carries_a_bounded_reference_scan_and_keeps_it_through_a_teach():
    from core_features.docking.database import DockInstance  # noqa: PLC0415
    ok = DockInstance(id="d", type="t", metadata={"reference_scan": SCANS["seated"]})
    assert ok.taught_at(x=1.0, y=2.0, yaw=0.5, map_id=None).metadata["reference_scan"] == SCANS["seated"]
    for bad in ({"ranges": [1.0] * 10, **{k: 0.0 for k in ("angle_min", "angle_increment", "range_min", "range_max")}},
                dict(SCANS["seated"], angle_min=float("nan")), dict(SCANS["seated"], ranges=["x"] * 100), "scan"):
        with pytest.raises(ValueError):
            DockInstance(id="d", type="t", metadata={"reference_scan": bad})


def site_evidence(**over):
    """Valid site_pose_evidence as Fleet sends it (sighting anchor, small camera residual, the robot's map id)."""
    return {"anchor_source": "sighting", "identity_mode": "led", "anchor_age_s": 2.0, "camera_residual_m": 0.02, "camera_residual_deg": 1.0, "map_id": "map-1", "at": 0.0, **over}


def with_reference(p, verified=False):
    """The dock gets its reference scan. By default NOT verified: a reference-scan dock then never stages on the map (b8xy nosein-4). verified=True: the dock command carries
    accepted site_pose_evidence, as a real Nav2 staging start needs (tests of the Nav2 path opt in)."""
    p.manager._db.get("bay1").metadata["reference_scan"] = SCANS["seated"]
    if verified:
        p.manager._map_id_provider = lambda: "map-1"
        orig = p.manager.dock
        p.manager.dock = lambda *a, **k: orig(*a, **{"site_pose_evidence": site_evidence(), **k})
    return p


def answer(match):
    """What the bridge does once per zone check: take the request, hand back the match."""
    def until(m):
        request = m.bay_scan_request()
        if request is not None:
            m.note_bay_scan_match(true_bay_pose(m.executor) if m._bay_phases._req_kind in ("align", "rowpose")
                                  else good(x=0.0) if m.phase is DockPhase.SETTLING else match, request_id=request[0])
        return done(m)
    return until


def answer_both(zone_match, seated_match):
    """The bridge for both asks: the zone check's, then the seated check's in SETTLING."""
    def until(m):
        request = m.bay_scan_request()
        if request is not None:
            m.note_bay_scan_match(true_bay_pose(m.executor) if m._bay_phases._req_kind in ("align", "rowpose")
                                  else seated_match if m.phase is DockPhase.SETTLING else zone_match, request_id=request[0])
        return done(m)
    return until


def test_stopped_well_short_of_the_stop_face_is_a_blocked_failure_not_a_40_s_wait():
    # y8xs 2026-11-20: the body was held 7.5 cm out; CORE waited 40 s for a charge that could not come
    p, row = a_row(start=(-0.15, 0.0, math.pi), others=(), charges=False)
    with_reference(p)
    p.manager.dock()
    run_row(p, row, until=answer_both(good(x=0.15), good(x=0.078)))
    assert p.manager.state is DockState.DOCK_FAILED
    retries = [d["reason"] for kind, d in p.events if kind == "docking.retry"]      # the retry's back-off then stops: no sim gap feed
    assert any("blocked short of the stop face (0.078 m out" in r for r in retries), retries


def test_seated_by_the_scan_keeps_waiting_for_the_charge_and_an_unverified_seat_never_drives_out():
    for seated, words in ((good(x=0.01), "charge NOT confirmed"),                         # verified straight: stays DOCKED, never drives out
                          (good(x=0.078, margin=0.1), "bay seat not measurable"),    # reference scan but no good fit: fail closed
                          (None, "bay seat not measurable")):
        p, row = a_row(start=(-0.15, 0.0, math.pi), others=(), charges=False)
        with_reference(p)
        p.manager.dock()
        run_row(p, row, until=answer_both(good(x=0.15), seated))
        retries = [d["reason"] for kind, d in p.events if kind == "docking.retry"]
        if "NOT confirmed" in words:
            assert p.manager.state is DockState.DOCKED and words in p.manager.status().last_event, p.manager.status().last_event
            assert not [c for ph, c in p.world.commands if ph is DockPhase.BACKOFF and c[0] > 0.0]
            continue
        assert p.manager.state is DockState.DOCK_FAILED
        if "not measurable" in words:
            assert words in p.manager._error, p.manager._error      # failed closed at the seat, no retry at all
            assert not [c for ph, c in p.world.commands if ph is DockPhase.BACKOFF]      # and it never drove out
        else:
            assert any(words in r for r in retries), retries         # verified straight: the retry happened (its back-off then stops, no sim gap)


def true_bay_pose(world, heading_lie=0.0):
    """The LiDAR bay pose of the sim robot: x out of the stop face, y = -lateral (bay frame), heading (the camera line's own formulas)."""
    x, y, yaw = world.pose
    c, sn = math.cos(yaw), math.sin(yaw)
    ox, oy = c * -x + sn * -y, -sn * -x + c * -y
    oyaw = math.atan2(-sn, c)
    ax, ay = math.cos(oyaw), math.sin(oyaw)
    lateral = ay * ox - ax * oy
    heading = math.remainder(yaw - math.pi, math.tau)
    return BayScanPose(x=max(0.0, ox * ax + oy * ay - 0.05), y=-lateral, heading=heading + heading_lie, inliers=0.95, margin=0.6, median_m=0.003)


def answer_kinds(zone=None, entry=None, seat=None, log=None, find=None):
    """The bridge for every ask, by what the phases are asking for."""
    answers = {"zone": zone or good(x=0.15), "entry": entry, "seat": seat or good(x=0.0), "find": find or good(x=0.5), "align": None, "alignpose": None, "rowpose": None}
    find_asks = []

    def until(m):
        request = m.bay_scan_request()
        if request is not None:
            kind = m._bay_phases._req_kind
            if log is not None:
                log.append((kind, request[0]))
            answer = answers[kind]
            if kind in ("entry", "seat") and isinstance(answer, str) and answer == "true":
                answer = true_bay_pose(m.executor)
            if kind in ("align", "alignpose", "rowpose"):
                answer = true_bay_pose(m.executor)              # the sim body is where the LiDAR says
            if kind == "find":
                find_asks.append(1)
                answer = answer(len(find_asks)) if callable(answer) else answer         # a callable gets the number of the ask
            m.note_bay_scan_match(answer, request_id=request[0])
            if kind == "seat":
                m.note_bay_seat_matches({"bay1": answer}, request[-1])
        return done(m)
    return until


def test_a_corridor_only_line_with_no_scan_pose_is_not_a_map_only_start():
    # L2: heading from the corridor line, but a lateral from the map alone is not evidence
    map_pose = (-0.15, 0.0, math.pi)
    dock = SimpleNamespace(x=0.0, y=0.0, yaw=0.0)
    verdict = classify(map_pose, dock, 0.45, _obs(0.0, measured=False), CFG)
    assert verdict.kind == "manual" and "no measured lateral" in verdict.reason
    assert classify(map_pose, dock, 0.45, _obs(0.0), CFG).kind in ("acquire", "exit")           # measured: as before
    assert classify(map_pose, dock, 0.45, _obs(0.0, measured=False), CFG, (0.15, 0.0, 0.0)).kind in ("acquire", "exit")


def test_the_entrance_is_measured_again_after_the_creep_and_every_source_must_be_centred():
    # R1/R2: the fresh scan pose is taken while stopped after the creep (a new request id); the camera line's measured
    # lateral and the scan's must both be inside bay_entrance_lateral_m
    for start_y, entry_y, ok in ((0.004, -0.003, True), (0.004, -0.020, False), (0.020, -0.003, False)):
        p, row = a_row(start=(-0.15, start_y, math.pi), others=())
        with_reference(p)
        log = []
        p.manager.dock()
        run_row(p, row, until=answer_kinds(zone=good(x=0.15, y=-start_y), entry=good(x=0.15, y=entry_y), log=log))
        log = [e for e in log if e[0] != "rowpose"]
        kinds = [k for k, _ in log]
        assert kinds[:2] == ["zone", "entry"] and log[0][1] != log[1][1], log
        if ok:
            assert p.manager.state is DockState.DOCKED, p.manager._error
        else:
            assert p.manager.state is DockState.DOCK_FAILED and "bay entrance lateral" in p.manager._error
            assert not [c for ph, c in p.world.commands if ph is DockPhase.ALIGNING]


def test_without_a_fresh_scan_pose_the_measured_line_alone_decides_the_entrance():
    p, row = a_row(start=(-0.15, 0.004, math.pi), others=())
    with_reference(p)
    p.manager.dock()
    run_row(p, row, until=answer_kinds(zone=good(x=0.15, y=-0.004), entry=None))   # the entry answer is "no fit"
    assert p.manager.state is DockState.DOCKED, p.manager._error


def test_a_late_answer_to_an_old_request_is_dropped():
    p = with_reference(a_bay())
    p.world.pose = (-0.15, 0.0, math.pi)
    p.manager.dock()
    p.manager.tick()
    first = p.manager.bay_scan_request()
    assert first is not None and p.manager.bay_scan_request() is None          # once per check
    phases = p.manager._bay_phases
    p.manager.note_bay_scan_match(good(), request_id=first[0] + 1)             # not the open request
    p.manager.note_bay_scan_match(good())                                      # no id at all
    assert phases._scan_match is None
    phases._zone = None                                                        # the check ended; a retry opens a new one
    phases.zone_entry()
    p.manager.note_bay_scan_match(good(), request_id=first[0])                 # the first run's answer arrives late
    assert phases._scan_match is None
    p.manager.tick()
    second = p.manager.bay_scan_request()
    assert second is not None and second[0] != first[0]
    p.manager.note_bay_scan_match(good(), request_id=second[0])
    assert phases._scan_match is not None


def test_off_centre_with_little_runway_stops_first_and_a_centred_start_docks():
    # y8xs 2026-11-20: 22 mm off at the entrance (9.45 mm a side) stopped 7.5 cm short; the zone check allows 50 mm
    p, row = a_row(start=(-0.15, 0.02, math.pi), others=())
    p.manager.dock()
    run_row(p, row)
    assert p.manager.state is DockState.DOCK_FAILED and "bay entrance lateral 0.020 m (limit 0.008 m)" in p.manager._error
    assert not [c for ph, c in p.world.commands if ph is DockPhase.ALIGNING]    # nothing reversed into the rails
    q, qrow = a_row(start=(-0.15, 0.005, math.pi), others=())
    q.manager.dock()
    run_row(q, qrow)
    assert q.manager.state is DockState.DOCKED, q.manager._error


def stale_map(p, dx=-0.40, dyaw=0.07):
    x, y, yaw = p.world.pose
    p.manager._pose_provider = lambda: (p.world.pose[0] + dx, p.world.pose[1], p.world.pose[2] + dyaw)


def test_a_stale_map_does_not_block_a_start_the_scan_places_in_the_bay():
    p, row = a_row(start=(-0.15, 0.0, math.pi), others=())
    with_reference(p)
    stale_map(p)                                     # 0.30 m and 4 deg off, as on 2026-11-20
    p.manager.dock()
    run_row(p, row, until=answer(good(x=0.15)))
    assert p.manager.state is DockState.DOCKED, p.manager._error
    assert p.world.goals == []


def test_without_a_reference_scan_the_stale_map_path_is_unchanged():
    p, row = a_row(start=(-0.15, 0.0, math.pi), others=())
    stale_map(p)
    p.manager.dock()
    run_row(p, row)
    assert p.manager.bay_scan_request() is None
    assert p.manager.state is not DockState.DOCKED or p.world.goals       # the map said "out": Nav2, as before


@pytest.mark.parametrize("weak", [good(inliers=0.5), good(margin=0.1), None])
def test_a_weak_or_missing_match_keeps_the_map_path(weak):
    p, row = a_row(start=(-0.15, 0.0, math.pi), others=())
    with_reference(p, verified=True)             # accepted site_pose_evidence: the map path (Nav2) is allowed
    stale_map(p)
    p.manager.dock()
    run_row(p, row, until=answer(weak))
    assert len(p.world.goals) >= 1                    # the stale map's "out", not the scan's "in the row"


def test_a_refusal_says_why_the_scan_pose_was_not_used():
    # y8xs 2026-11-20: the map path refused and nothing said whether the scan pose was asked for, late, or too weak
    for match, words in ((good(inliers=0.5), "not used: inliers 0.50 < 0.70 (inliers 0.50 min 0.70"), (None, "no fit")):
        p, row = a_row(start=(-0.15, 0.0, math.pi), others=())
        with_reference(p)
        p.detector.glitch_frames = 10_000
        p.manager.dock()
        run_row(p, row, until=answer(match))
        assert p.manager.state is DockState.DOCK_FAILED and "[scan pose" in p.manager._error and words in p.manager._error
    p, row = a_row(start=(-0.15, 0.0, math.pi), others=())
    with_reference(p)
    p.detector.glitch_frames = 10_000
    p.manager.dock()
    run_row(p, row, until=lambda m: (m.bay_scan_request(), done(m))[1])    # asked, nobody answers
    assert "no answer in" in p.manager._error
    q, qrow = a_row(start=(-0.15, 0.0, math.pi), others=())
    with_reference(q)
    q.detector.glitch_frames = 10_000
    q.manager.dock()
    run_row(q, qrow)                                  # the bridge never asks
    assert "never requested" in q.manager._error


def test_no_answer_in_time_refuses_with_a_person_call_and_never_stages_on_the_map_and_waits_no_longer_than_the_limit():
    p, row = a_row(start=(-0.15, 0.0, math.pi), others=())
    with_reference(p)
    t0 = p.clock.now
    p.manager.dock()
    run_row(p, row)                                   # nobody answers
    # a reference-scan dock never decides on the map alone (b8xy nosein-4: Nav2 staging with the map pose unverified): no verdict, no Nav2 goal, a person is called
    assert p.manager.state is DockState.DOCK_FAILED and "no LiDAR bay pose answer" in p.manager._error and "map pose is unverified" in p.manager._error, p.manager._error
    assert p.world.goals == [] and any(k == "docking.person_call" for k, d in p.events)
    assert p.clock.now - t0 >= CFG.bay_scan_pose_wait_s


def test_the_wrong_bay_is_refused_even_with_a_good_scan_match():
    # a good scan fit but the camera line (measured) lies 0.10 m to the side: another line, stay still
    p, row = a_row(start=(-0.15, 0.0, math.pi), others=())
    with_reference(p)
    p.detector.glitch_frames = 10_000
    p.manager.dock()
    run_row(p, row, until=answer(good(x=0.15)))
    assert p.manager.state is DockState.DOCK_FAILED and "disagree (lateral scan" in p.manager._error
    assert moved(p) == []


def test_the_bridge_matches_the_live_scan_against_the_stored_one_off_the_scan_thread():
    p = with_reference(a_bay())
    p.world.pose = (-0.15, 0.0, math.pi)
    p.manager.dock()
    p.manager.tick()                                  # the zone check starts and asks
    cfg = SimpleNamespace(body_front_x_m=PINKY_PRO.front_x_m, body_rear_x_m=PINKY_PRO.rear_x_m,
                          body_half_width_m=PINKY_PRO.half_width_m, body_rotation_radius_m=PINKY_PRO.rotation_radius_m,
                          body_lidar_x_m=PINKY_PRO.lidar_x_m, lidar_forward_deg=180.0,
                          obstacle_body_margin_m=0.0, lidar_self_mask=())
    services = SimpleNamespace(docking=p.manager, line_follow=SimpleNamespace(config=cfg))
    before = threading.active_count()
    bay_body_scan(services, dict(SCANS["near"]), received_at=p.clock.now)
    deadline = time.time() + 20.0
    while p.manager._bay_phases._scan_match is None and time.time() < deadline:
        time.sleep(0.05)
    match = p.manager._bay_phases._scan_match
    assert match is not None and match[0] is not None
    assert match[0].x == pytest.approx(0.084, abs=0.02) and match[0].inliers >= 0.8
    bay_body_scan(services, dict(SCANS["near"]), received_at=p.clock.now)      # asked once per check
    assert p.manager.bay_scan_request() is None


def test_a_docked_without_charge_pack_that_stays_down_warns_once_and_a_blip_does_not():
    # panel B R4/R5: the full-battery seat is DOCKED with no charge evidence; a pack that FALLS (filtered voltage, held 5 s) warns
    from types import SimpleNamespace  # noqa: PLC0415
    p, row = a_row(start=(-0.15, 0.0, math.pi), others=(), charges=False)
    with_reference(p)
    p.battery.percent = 100.0
    p.manager.dock()
    run_row(p, row, until=answer_kinds(zone=good(x=0.15), entry=good(x=0.15), seat=good(x=0.01)))
    assert p.manager.state is DockState.DOCKED and p.manager._uncharged_v0 is not None
    v0 = p.manager._uncharged_v0

    def pack(filtered, raw):
        return SimpleNamespace(voltage=raw, percent=100.0, set_charging=lambda flag: None,
                               status=lambda: SimpleNamespace(filtered_voltage=filtered))
    p.manager._battery = pack(v0 - 0.2, v0 - 0.2)
    for _ in range(3):                                   # 3 s down: not yet
        p.clock.now += 1.0
        p.manager.tick()
    assert not [1 for kind, d in p.events if kind == "docking.uncharged_voltage_drop"]
    p.manager._battery = pack(v0, v0 - 0.2)              # a raw dip while the filtered voltage is fine: the watch resets
    p.clock.now += 1.0
    p.manager.tick()
    p.manager._battery = pack(v0 - 0.2, v0 - 0.2)
    for _ in range(7):
        p.clock.now += 1.0
        p.manager.tick()
    warnings = [d for kind, d in p.events if kind == "docking.uncharged_voltage_drop"]
    assert len(warnings) == 1 and warnings[0]["to_v"] == pytest.approx(v0 - 0.2) and "pack fell" in p.manager.status().last_event

def test_a_reference_dock_docks_end_to_end_when_every_ask_is_answered():
    # R4: the positive case (the no-answer test above is the fail-closed one)
    p, row = a_row(start=(-0.15, 0.0, math.pi), others=())
    with_reference(p)
    p.manager.dock()
    run_row(p, row, until=answer_kinds(zone=good(x=0.15), entry=good(x=0.15)))
    assert p.manager.state is DockState.DOCKED, p.manager._error
    assert abs(p.world.pose[0] + 0.05) < 1e-6

def test_the_entry_lateral_of_a_reference_dock_comes_from_the_lidar_not_the_drifting_map():
    # round 21: after staging + turn the camera saw only the crossbar and the lateral was filled from the map: 143 mm -> a retry through another turn
    p, row = a_row(start=None, others=())
    with_reference(p)
    p.manager._pose_provider = lambda: (p.world.pose[0], p.world.pose[1] + 0.143, p.world.pose[2])      # the map is 143 mm off
    capture = p.detector.capture

    def corridor_only():
        capture()
        if p.detector.latest is not None and p.manager.phase is DockPhase.ACQUIRING:
            p.detector.latest = p.detector.latest.model_copy(update={"lateral_measured": False})
    p.detector.capture = corridor_only
    p.manager.dock()
    run_row(p, row, until=answer_kinds(zone=good(x=1.0), entry="true"))
    assert not [r for kind, d in p.events if kind == "docking.retry" for r in [d["reason"]] if "entry error" in r], p.events
    assert p.manager.state is DockState.DOCKED, p.manager._error

def _entry_setup(lateral_measured):
    p, row = a_row(start=None, others=())
    with_reference(p)
    capture = p.detector.capture

    def cam():
        capture()
        if p.detector.latest is not None and p.manager.phase is DockPhase.ACQUIRING:
            p.detector.latest = p.detector.latest.model_copy(update={"lateral_measured": lateral_measured})
    p.detector.capture = cam
    return p, row


def test_no_good_lidar_pose_at_the_entry_window_and_a_map_filled_lateral_retries_once_then_stops():
    p, row = _entry_setup(False)
    p.manager.dock()
    run_row(p, row, until=answer_kinds(zone=good(x=1.0), entry=None))               # the entry pose never fits
    retries = [d["reason"] for kind, d in p.events if kind == "docking.retry"]
    assert any("no LiDAR pose at the entry window" in r for r in retries), retries   # one retry first (its back-off then stops: no sim gap feed)
    assert p.manager.state is DockState.DOCK_FAILED
    assert not [c for ph, c in p.world.commands if ph is DockPhase.ALIGNING]


def test_no_good_lidar_pose_with_a_measured_camera_lateral_keeps_the_camera():
    p, row = _entry_setup(True)
    p.manager.dock()
    run_row(p, row, until=answer_kinds(zone=good(x=1.0), entry=None))
    assert "no LiDAR pose at the entry window" not in (p.manager._error or "")


def test_a_weak_lidar_heading_that_disagrees_with_the_camera_crossbar_stops():
    p, row = _entry_setup(True)
    p.manager.dock()
    run_row(p, row, until=answer_kinds(zone=good(x=1.0), entry=good(x=0.4, heading=math.radians(15.0), inliers=0.78, margin=0.45)))
    assert p.manager.state is DockState.DOCK_FAILED and "disagree (false fit?)" in p.manager._error, p.manager._error


def test_a_strong_lidar_fit_outweighs_a_camera_heading_that_is_wrong_at_this_site():
    # round 22: the camera crossbar heading read -20..-25 deg on a straight body; the camera jump check and the cross-check must not stop it
    p, row = a_row(start=None, others=())
    with_reference(p)
    capture = p.detector.capture
    n = {"acq": 0}

    def lying():
        capture()
        if p.detector.latest is not None and p.manager.phase is DockPhase.ACQUIRING:
            n["acq"] += 1
            lie = math.radians(-12.0 if n["acq"] < 6 else -25.0)               # a different wrong heading before and after the creep
            p.detector.latest = p.detector.latest.model_copy(update={"yaw": p.detector.latest.yaw - lie})
    p.detector.capture = lying
    seen = []
    p.manager.dock()
    until = answer_kinds(zone=good(x=1.0), entry="true")

    def watch(m):
        if m.status().last_event not in seen:
            seen.append(m.status().last_event)
        return until(m)
    run_row(p, row, until=watch)
    retries = [d["reason"] for kind, d in p.events if kind == "docking.retry"]
    assert not any("jumped" in r for r in retries), retries
    assert p.manager.state is DockState.DOCKED, p.manager._error
    assert any(e and e.startswith("entry: camera heading") for e in seen), seen


def test_the_lidar_steer_state_of_an_earlier_attempt_does_not_outlive_its_aligning():
    p = a_bay()
    with_reference(p)
    p.manager.dock()
    bp = p.manager._bay_phases
    bp._lp, bp._lp_lost_since, bp._lp_start, bp._ls_cap = (0.1, 0.0, 0.0, 0.0, 0.0), 5.0, 5.0, 0.3
    bp._reset_line_state()
    assert bp._lp is None and bp._lp_lost_since is None and bp._lp_start is None and bp._ls_cap is None
    p.manager.tick()
    assert bp._lidar_steer(p.clock.now) is None                # not ALIGNING: no in-the-rails rule at all

def test_the_entry_heading_align_of_a_reference_dock_closes_on_the_lidar_not_the_camera_heading():
    # R4: the body is 20 deg off after the turn but the camera claims straight: closing on the camera would stop the align at once
    p, row = a_row(start=None, others=())
    with_reference(p)
    p.world.arrival_error = (0.0, math.radians(20.0))
    capture = p.detector.capture

    def camera_says_straight():
        capture()
        if p.detector.latest is not None and p.manager.phase is DockPhase.ACQUIRING:
            x, y, yaw = p.world.pose
            p.detector.latest = p.detector.latest.model_copy(update={"yaw": p.detector.latest.yaw + math.remainder(yaw - math.pi, math.tau)})
    p.detector.capture = camera_says_straight
    p.manager.dock()
    run_row(p, row, until=answer_kinds(zone=good(x=1.0), entry="true"))
    assert p.manager.state is DockState.DOCKED, p.manager._error
    spins = [c for ph, c in p.world.commands if ph is DockPhase.ACQUIRING and c[0] == 0.0 and abs(c[1]) > 1e-6]
    assert spins, "the align never turned"


def test_the_first_aligning_pose_must_agree_with_the_entry_window_pose():
    p = a_bay()
    with_reference(p)
    p.manager.dock()
    bp = p.manager._bay_phases
    bp._entry_match = (good(x=0.4, y=0.0, heading=0.0), p.clock.now)
    bp.ls_note(good(x=0.36, y=-0.08, heading=0.0), p.clock.now)             # 8 cm sideways of the entry values
    bp.ls_note(good(x=0.36, y=0.0, heading=math.radians(9.0)), p.clock.now)     # 9 deg apart
    assert bp._lp is None
    bp.ls_note(good(x=0.36, y=-0.01, heading=math.radians(1.0)), p.clock.now)
    assert bp._lp is not None


def test_a_lidar_heading_over_40_deg_from_the_camera_stops_even_a_strong_fit():
    p, row = _entry_setup(True)
    p.manager.dock()
    run_row(p, row, until=answer_kinds(zone=good(x=1.0), entry=good(x=0.4, heading=math.radians(43.0), inliers=0.95, margin=0.6)))
    assert p.manager.state is DockState.DOCK_FAILED and "apart: stopped" in p.manager._error, p.manager._error

def test_an_entry_pose_one_bay_pitch_off_is_an_alias_not_a_pose():
    # round 23: lateral 191 mm / heading 23 deg right after a good turn on the axis = the neighbouring bay
    p = a_bay()
    with_reference(p)
    p.manager.dock()
    bp = p.manager._bay_phases
    bp._entry_since = p.clock.now
    bp._entry_match = (good(x=0.4, y=-0.191, heading=math.radians(23.0)), p.clock.now)
    assert bp._entry_lidar(p.clock.now) is None
    assert "alias of a neighbour bay" in p.manager.status().last_event
    bp._entry_match = (good(x=0.4, y=-0.03, heading=math.radians(3.0)), p.clock.now)
    assert bp._entry_lidar(p.clock.now) is not None


def test_the_rail_entrance_judges_the_mean_of_several_lidar_poses_and_the_reverse_corrects_the_lateral_first():
    # a 25 mm lateral at the staging point is centred by the LiDAR-steered reverse before the entrance; noisy single poses do not decide
    import random  # noqa: PLC0415
    rng = random.Random(3)
    p, row = a_row(start=None, others=())
    with_reference(p)
    p.world.arrival_error = (0.025, 0.0)
    until = answer_kinds(zone=good(x=1.0), entry="true")

    def noisy(m):
        request = m.bay_scan_request()
        if request is not None and m._bay_phases._req_kind in ("align", "rowpose"):
            pose = true_bay_pose(m.executor)
            m.note_bay_scan_match(BayScanPose(x=pose.x, y=pose.y + rng.uniform(-0.004, 0.004), heading=pose.heading, inliers=0.95,
                                              margin=0.6, median_m=0.003), request_id=request[0])
            return done(m)
        return until(m) if request is None else _with(until, m, request)

    def _with(u, m, request):
        # hand the request back to answer_kinds' logic by asking again is not possible: answer here by kind
        kind = m._bay_phases._req_kind
        ans = true_bay_pose(m.executor) if kind in ("entry", "seat", "alignpose") else good(x=1.0) if kind == "zone" else None
        m.note_bay_scan_match(ans, request_id=request[0])
        return done(m)
    p.manager.dock()
    run_row(p, row, until=noisy)
    assert p.manager.state is DockState.DOCKED, p.manager._error


def test_a_rail_entrance_whose_mean_lateral_is_off_stops_before_the_rails():
    p = a_bay()
    with_reference(p)
    p.manager.dock()
    bp = p.manager._bay_phases
    bp._lp_hist, bp._x_now, bp._rail_judged = [0.02, 0.018, 0.022], 0.11, False
    assert bp._rail_judge(p.clock.now) is True
    assert p.manager.state is DockState.DOCKING and "bay rail entrance lateral 0.020 m (mean of 3" in p.manager.status().last_event       # a reseat in the lane, not a fail
    q = a_bay()
    with_reference(q)
    q.manager.dock()
    qb = q.manager._bay_phases
    qb._lp_hist, qb._x_now, qb._rail_judged = [0.012, -0.010, 0.001], 0.11, False
    assert qb._rail_judge(q.clock.now) is False and qb._rail_judged         # +-10 mm single poses, mean 1 mm: judged on the mean


def test_consecutive_align_poses_may_not_jump_by_more_than_5_deg_plus_the_turn_rate():
    p = a_bay()
    with_reference(p)
    p.manager.dock()
    bp = p.manager._bay_phases
    bp._align_lp = (0.0, 0.0, 10.0)
    t0 = 10.2
    bp.note_scan_match = bp.note_scan_match
    bp._req_open, bp._req_kind = 1, "alignpose"
    bp.note_scan_match(good(x=0.4, heading=math.radians(12.0)), t0, None, 1)       # +12 deg in 0.2 s: a jump
    assert bp._align_lp[0] == 0.0
    bp._req_open, bp._req_kind = 2, "alignpose"
    bp.note_scan_match(good(x=0.4, heading=math.radians(4.0)), t0, None, 2)
    assert abs(bp._align_lp[0] - math.radians(4.0)) < 1e-9
