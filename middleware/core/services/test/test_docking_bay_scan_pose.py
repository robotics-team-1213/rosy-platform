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


def with_reference(p):
    p.manager._db.get("bay1").metadata["reference_scan"] = SCANS["seated"]
    return p


def answer(match):
    """What the bridge does once per zone check: take the request, hand back the match."""
    def until(m):
        request = m.bay_scan_request()
        if request is not None:
            m.note_bay_scan_match(good(x=0.0) if m.phase is DockPhase.SETTLING else match, request_id=request[0])
        return done(m)
    return until


def answer_both(zone_match, seated_match):
    """The bridge for both asks: the zone check's, then the seated check's in SETTLING."""
    def until(m):
        request = m.bay_scan_request()
        if request is not None:
            m.note_bay_scan_match(seated_match if m.phase is DockPhase.SETTLING else zone_match, request_id=request[0])
        return done(m)
    return until


def test_stopped_well_short_of_the_stop_face_is_a_blocked_failure_not_a_40_s_wait():
    # y8xs 2026-11-20: the body was held 7.5 cm out; CORE waited 40 s for a charge that could not come
    p, row = a_row(start=(-0.15, 0.0, math.pi), others=(), charges=False)
    with_reference(p)
    p.manager.dock()
    run_row(p, row, until=answer_both(good(x=0.15), good(x=0.078)))
    assert p.manager.state is DockState.DOCK_FAILED
    assert "blocked short of the stop face (0.078 m out" in p.manager._error


def test_seated_by_the_scan_keeps_waiting_for_the_charge_and_a_weak_check_changes_nothing():
    for seated in (good(x=0.01), good(x=0.078, margin=0.1), None):
        p, row = a_row(start=(-0.15, 0.0, math.pi), others=(), charges=False)
        with_reference(p)
        p.manager.dock()
        run_row(p, row, until=answer_both(good(x=0.15), seated))
        assert p.manager.state is DockState.DOCK_FAILED and "no charge after bay contact" in p.manager._error


def answer_kinds(zone=None, entry=None, seat=None, log=None):
    """The bridge for every ask, by what the phases are asking for."""
    answers = {"zone": zone or good(x=0.15), "entry": entry, "seat": seat or good(x=0.0)}

    def until(m):
        request = m.bay_scan_request()
        if request is not None:
            kind = m._bay_phases._req_kind
            if log is not None:
                log.append((kind, request[0]))
            m.note_bay_scan_match(answers[kind], request_id=request[0])
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
    with_reference(p)
    stale_map(p)
    p.manager.dock()
    run_row(p, row, until=answer(weak))
    assert len(p.world.goals) >= 1                    # the stale map's "out", not the scan's "in the row"


def test_a_refusal_says_why_the_scan_pose_was_not_used():
    # y8xs 2026-11-20: the map path refused and nothing said whether the scan pose was asked for, late, or too weak
    for match, words in ((good(inliers=0.5), "rejected: inliers 0.50 (min 0.70)"), (None, "no fit")):
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


def test_no_answer_in_time_keeps_the_map_path_and_waits_no_longer_than_the_limit():
    p, row = a_row(start=(-0.15, 0.0, math.pi), others=())
    with_reference(p)
    t0 = p.clock.now
    p.manager.dock()
    run_row(p, row)                                   # nobody answers
    assert p.manager.state is DockState.DOCKED, p.manager._error     # the consistent map docks it
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
