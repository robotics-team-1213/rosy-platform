"""Pit-in (case II arrival at the junction, facing the bay), real b8xy C2 scans 2026-11-21: the LiDAR pose is right (x 0.40, lateral 14 mm) but below the row gates
(inliers 0.66-0.68 < 0.70, margin 0.17-0.19 < 0.40: the bays are self-similar and the 180 flip scores 0.50), and the map pose is unusable after a CORE restart."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from core_common.robot_body import PINKY_PRO
from core_common.protocol.schemas import DockState
from core_features.docking.bay_scan_pose import BayScanPose, locate
from core_features.docking.bay_zone import backout_geometry, expected_front_gap, junction_candidate, junction_geometry, scan_fit_pose, scan_geometry
from core_features.docking.detector import DockObservation
from core_features.docking.model import DockingConfig, DockPhase
from test_docking_bay import DT, a_bay, done
from test_docking_bay_scan_pose import with_reference

DATA = json.loads((Path(__file__).parent / "data_b8xy_c2_pitin.json").read_text())
CFG = DockingConfig()
STAGING = 0.35


def _pose():
    ref = PINKY_PRO.scan_view(DATA["seat_reference"], forward_deg=180.0).points
    return locate(ref, PINKY_PRO.scan_view(DATA["live"], forward_deg=180.0).points)


def _camera(lateral):
    """A measured camera line lateral (dock frame) with a heading that lies by 17 deg, as at this site."""
    yaw = math.pi + 0.3
    ax, ay = math.cos(yaw), math.sin(yaw)
    along = 0.40
    return DockObservation(x=along * ax + lateral * ay, y=along * ay - lateral * ax, yaw=yaw, confidence=1.0, at=0.0)


def test_the_real_pitin_pose_is_right_but_below_the_row_gates_and_junction_geometry_accepts_it_with_the_camera_lateral():
    m = _pose()
    assert m.x == pytest.approx(0.403, abs=0.01) and abs(m.y) < 0.02 and abs(math.degrees(abs(m.heading)) - 167.0) < 4.0
    assert m.inliers < CFG.bay_scan_inlier_min and m.margin < CFG.bay_scan_margin_min          # the row gates refuse it, unchanged
    assert scan_geometry(m, STAGING, CFG) is None
    jn = junction_geometry(m, _camera(-m.y), CFG)
    assert jn is not None and jn[0] == pytest.approx(m.x) and abs(jn[1]) < 0.02


def test_a_neighbour_bay_a_flip_a_weak_fit_or_an_unmeasured_camera_is_refused():
    m = _pose()
    cam = _camera(-m.y)
    assert junction_geometry(m, _camera(-m.y + 0.21), CFG) is None                   # the camera lateral says the neighbour bay (a pitch away)
    assert junction_geometry(BayScanPose(x=m.x, y=m.y, heading=m.heading - math.pi, inliers=m.inliers, margin=m.margin, median_m=0.01), cam, CFG) is None   # nose out
    assert junction_geometry(BayScanPose(x=m.x, y=m.y, heading=m.heading, inliers=0.55, margin=m.margin, median_m=0.01), cam, CFG) is None
    assert junction_geometry(BayScanPose(x=m.x, y=m.y, heading=m.heading, inliers=m.inliers, margin=0.05, median_m=0.01), cam, CFG) is None
    assert junction_geometry(BayScanPose(x=0.20, y=m.y, heading=m.heading, inliers=m.inliers, margin=m.margin, median_m=0.01), cam, CFG) is None      # not at the junction
    assert junction_geometry(m, cam.model_copy(update={"lateral_measured": False}), CFG) is None
    assert junction_geometry(m, None, CFG) is None


def test_a_neighbours_scan_against_this_reference_never_reaches_the_junction_rule():
    scans = json.loads((Path(__file__).parent / "data_y8xs_bay_scans.json").read_text())
    ref = PINKY_PRO.scan_view(scans["seated"], forward_deg=180.0).points
    m = locate(ref, PINKY_PRO.scan_view(scans["neighbour_b8xy_c1"], forward_deg=180.0).points)
    assert m is not None and junction_geometry(m, _camera(-m.y), CFG) is None


def test_the_state_machine_turns_at_the_junction_without_nav2_and_the_turn_is_watched():
    p = a_bay()
    with_reference(p)
    p.world.pose = (-0.45, 0.0, 0.0)                                     # at the junction (staging offset 0.45), nose toward the bay
    p.manager.dock()
    phases, seen = [], []
    for k in range(4000):
        if k % 2 == 0:
            p.detector.capture()
            p.manager.note_body_scan(None, 0.45 + 0.112, None, p.clock.now)         # empty bay: front gap = x + 0.112
        p.manager.tick()
        ph = p.manager.phase
        if ph is not None and (not phases or phases[-1] is not ph):
            phases.append(ph)
        ev = p.manager.status().last_event
        if ev and ev not in seen:
            seen.append(ev)
        req = p.manager.bay_scan_request()
        if req is not None:
            kind = p.manager._bay_phases._req_kind
            if kind == "zone":
                p.manager.note_bay_scan_match(BayScanPose(x=0.45, y=0.0, heading=math.radians(168.0), inliers=0.66, margin=0.17, median_m=0.01), at=p.clock.now, request_id=req[0])
        if DockPhase.TURNING in phases or done(p.manager):
            break
        p.world.step()
        p.clock.now += DT
    assert p.world.goals == [], (phases, seen)                          # no Nav2 leg: the map pose is not used
    assert DockPhase.TURNING in phases, (phases, seen, p.manager._error)
    assert any(e and e.startswith("pit-in:") for e in seen), seen

def _at_the_junction(front, bay_heading=168.0):
    p = a_bay()
    with_reference(p)
    p.world.pose = (-0.45, 0.0, 0.0)
    p.manager.dock()
    phases, bp = [], p.manager._bay_phases
    for k in range(3000):
        if k % 2 == 0:
            p.detector.capture()
            p.manager.note_body_scan(None, front, None, p.clock.now)
        p.manager.tick()
        req = p.manager.bay_scan_request()
        if req is not None and bp._req_kind == "zone":
            p.manager.note_bay_scan_match(BayScanPose(x=0.45, y=0.0, heading=math.radians(bay_heading), inliers=0.66, margin=0.17, median_m=0.01), at=p.clock.now, request_id=req[0])
        if p.manager.phase is DockPhase.TURNING or done(p.manager):
            break
        p.world.step()
        p.clock.now += DT
    return p, bp


def test_it_turns_to_the_lidar_bay_heading_not_a_fixed_180():
    p, bp = _at_the_junction(0.562, bay_heading=166.5)
    yaw = p.world.pose[2]
    assert p.manager.phase is DockPhase.TURNING and bp._pitin
    assert abs(abs(math.remainder(bp._turn_target - yaw, math.tau)) - math.radians(166.5)) < math.radians(0.5)         # 166.5 deg, not 180


def test_an_occupied_or_unmeasured_bay_is_never_turned_in_to():
    for front in (0.562 - 0.15, 0.562 + 0.2, None):
        p, bp = _at_the_junction(front)
        assert p.manager.state is DockState.DOCK_FAILED, (front, p.manager._error)
        assert any(w in p.manager._error for w in ("front gap", "not measurable")), (front, p.manager._error)
        assert not bp._pitin and p.world.goals == []


def test_after_a_pit_in_turn_the_entry_needs_a_lidar_pose_and_a_5_deg_heading():
    p, bp = _at_the_junction(0.562)
    bp._entry_match, bp._entry_since = None, p.clock.now - 10.0
    assert bp._entry_values(p.clock.now, 0.0, 0.0) == "stop"
    assert p.manager.state is DockState.DOCK_FAILED and "pit-in: no LiDAR pose at the entry window" in p.manager._error
    assert p.manager._cfg.bay_pitin_entry_heading_rad < p.manager._cfg.bay_entry_heading_max_rad


def test_a_pit_in_stop_over_the_lane_edge_pulls_forward_to_the_junction_and_tries_again():
    # the real stop of 2026-11-21: x 0.269, lateral -41 mm, heading -12.3 deg: footprint 0.125 > 0.09. The over-edge allowance ships OFF (0.0): this test turns it on.
    p, bp = _at_the_junction(0.562)
    cfg = p.manager._cfg
    cfg.bay_reseat_over_edge_m = 0.04
    p.world.pose = (-0.319, 0.0, math.pi)                        # rear to the bay, at x 0.269 (the sim frame: stop face at 0.05 behind x = 0)
    t = p.clock.now
    p.manager._phase = DockPhase.ALIGNING
    bp._row_pose = (0.269, -0.0413, math.radians(-12.3), t, 0.0)
    bp._lp = (0.269, -0.0413, math.radians(-12.3), t, 0.0, 0.0)[:5]
    p.manager._retry("bay left the lane: test")
    assert p.manager.phase is DockPhase.BACKOFF and bp._reseat_active and p.manager._retries == 1
    assert bp._rs_target >= 0.269 + cfg.bay_reseat_min_arc_m - 1e-9 and bp._rs_ext0 > 0.12
    cmds = []
    for _ in range(40):
        bp._row_pose = (bp._row_pose[0], bp._row_pose[1], bp._row_pose[2], p.clock.now, abs(p.manager.executor.travelled_m()))
        p.manager.note_body_scan(None, 0.9, max(0.0, -p.world.pose[0] - 0.05) + 0.01, p.clock.now)
        p.manager.tick()
        cmds.append(p.world.command)
        if p.manager.state is DockState.DOCK_FAILED:
            break
        p.world.step()
        p.clock.now += DT
    assert p.manager.state is not DockState.DOCK_FAILED, p.manager._error                        # the over-edge start is allowed to move
    assert any(c[0] > 0.0 for c in cmds)                                                         # forward only
    assert not any(c[0] < 0.0 for c in cmds)
    # a footprint that GROWS during the reseat stops it
    bp._row_pose = (0.28, -0.07, math.radians(-12.3), p.clock.now, 0.0)
    p.manager.tick()
    assert p.manager.state is DockState.DOCK_FAILED and "past the lane edge" in p.manager._error
    assert any(k == "docking.person_call" for k, d in p.events)

def test_the_empty_bay_front_gap_is_modelled_from_the_reference_scan_not_a_constant():
    ref = PINKY_PRO.scan_view(DATA["seat_reference"], forward_deg=180.0).points
    diffs = []
    for key in ("live", "run5_end"):
        for sc in ([DATA["live"]] if key == "live" else DATA["run5_end"]):
            view = PINKY_PRO.scan_view(sc, forward_deg=180.0)
            m = locate(PINKY_PRO.scan_view(DATA["seat_reference"], forward_deg=180.0).points, view.points)
            meas = PINKY_PRO.translation_gap(view.points)
            model = expected_front_gap(ref, m.x, m.y, m.heading, CFG)
            diffs.append(abs(model - meas))
            assert abs(meas - (m.x + CFG.bay_empty_front_extra_m)) < 0.05                  # the constant is only the fallback
    assert sorted(diffs)[len(diffs) // 2] < 0.015 and max(diffs) < 0.07, diffs              # the model follows the heading (x 0.40 / 167 deg and x 0.26 / 179 deg)


def test_the_zone_waits_for_the_camera_lateral_and_never_falls_into_the_nav2_staging_on_the_map():
    # b8xy run 5: the same arrival as run 4 took the Nav2 staging leg (the camera line was not measured yet) and the back-off then drove at the bay
    p = a_bay()
    with_reference(p)
    p.world.pose = (-0.45, 0.0, 0.0)
    p.manager.dock()
    bp = p.manager._bay_phases
    bp._observation = lambda: None                                       # no camera line
    for k in range(400):
        if k % 2 == 0:
            p.detector.capture()
            p.manager.note_body_scan(None, 0.55, None, p.clock.now)
        p.manager.tick()
        req = p.manager.bay_scan_request()
        if req is not None and bp._req_kind == "zone":
            p.manager.note_bay_scan_match(BayScanPose(x=0.45, y=0.0, heading=math.radians(175.0), inliers=0.66, margin=0.17, median_m=0.01), at=p.clock.now, request_id=req[0])
        if done(p.manager):
            break
        p.world.step()
        p.clock.now += DT
    assert p.world.goals == []                                           # never the Nav2 leg
    assert p.manager.state is DockState.DOCK_FAILED and "no measured camera line lateral" in p.manager._error, p.manager._error


def test_a_back_off_facing_the_bay_does_not_move():
    p, bp = _at_the_junction(0.562)
    p.manager.__dict__.get("_x")                                         # (state set up by the junction helper: TURNING)
    bp._facing_bay = True
    bp._pitin = False
    p.manager._phase = DockPhase.STAGING
    p.manager._retry("staging failed: FAILED")
    cmds = []
    for _ in range(30):
        p.manager.note_body_scan(None, 0.9, 0.9, p.clock.now)
        p.manager.tick()
        if p.manager.phase is DockPhase.BACKOFF:
            cmds.append(p.world.command)
        p.world.step()
        p.clock.now += DT
    assert not any(c[0] > 0.0 for c in cmds)                             # BACKOFF drives forward = at the bay: it stays still


def test_the_separate_junction_entry_path_takes_a_weak_pose_and_the_row_gate_is_untouched():
    p, bp = _at_the_junction(0.562)
    weak = BayScanPose(x=0.40, y=0.01, heading=0.02, inliers=0.65, margin=0.17, median_m=0.01)
    assert scan_fit_pose(weak, CFG) is None                              # the row gate (0.70 / 0.40) is not relaxed
    p.manager._bay_phases._observation = lambda: _camera(-weak.y)
    bp._pitin, bp._entry_match, bp._entry_since = True, (weak, p.clock.now), p.clock.now
    got = bp._entry_lidar(p.clock.now)
    assert got is not None and abs(got[0] + 0.01) < 1e-6 and got[2] == 0.40
    bp._entry_match = (BayScanPose(x=0.40, y=0.01, heading=0.02, inliers=0.55, margin=0.17, median_m=0.01), p.clock.now)
    assert bp._entry_lidar(p.clock.now) is None


def test_the_over_edge_allowance_is_pit_in_only_from_x_018_with_a_clear_side_and_survives_a_pose_age():
    p, bp = _at_the_junction(0.562)
    cfg = p.manager._cfg
    assert cfg.bay_reseat_over_edge_m == 0.0 and not bp._over_edge_ok(0.126, 0.125, 0.27, p.clock.now)          # ships OFF
    cfg.bay_reseat_over_edge_m = 0.04
    p.manager.note_body_scan(None, 0.9, 0.9, p.clock.now)
    bp._reseat_active, bp._rs_ext0, bp._pitin = True, 0.125, False
    edge = 0.09
    assert not bp._over_edge_ok(0.126, 0.125, 0.27, p.clock.now)         # not pit-in
    bp._pitin = True
    assert bp._over_edge_ok(0.129, 0.125, 0.27, p.clock.now)             # worst case under the cap, nominal not worse: a 0.2 s old pose no longer switches it off
    assert not bp._over_edge_ok(0.126, 0.125, 0.15, p.clock.now)         # base x < 0.18: the tray corner would overlap the neighbour's tip
    assert not bp._over_edge_ok(0.131, 0.125, 0.27, p.clock.now)         # over the cap
    assert not bp._over_edge_ok(0.129, 0.130, 0.27, p.clock.now)         # growing
    p.manager.note_body_scan("near", 0.9, 0.9, p.clock.now)              # something beside it
    assert not bp._over_edge_ok(0.126, 0.125, 0.27, p.clock.now) and edge < cfg.bay_reseat_over_edge_m * 4


def test_an_arrival_5_cm_off_the_axis_centres_itself_forward_and_back_then_turns():
    from test_docking_bay_scan_pose import true_bay_pose  # noqa: PLC0415
    p = a_bay()
    with_reference(p)
    p.manager._cfg.bay_centre_tries, p.manager._cfg.bay_junction_lateral_m = 4, 0.06        # the centring shuttle ships OFF (0 tries, 0.03 window): this test turns it on
    p.world.pose = (-0.45, -0.06, 0.0)                                    # facing the bay, 6 cm to one side (the window)
    p.manager.dock()
    bp = p.manager._bay_phases
    bp._observation = lambda: _camera(true_bay_pose(p.world).y)
    seen, ys = [], []
    for k in range(6000):
        if k % 2 == 0:
            p.detector.capture()
            p.manager.note_body_scan(None, true_bay_pose(p.world).x + CFG.bay_empty_front_extra_m, 0.9, p.clock.now)       # an empty bay
        p.manager.tick()
        req = p.manager.bay_scan_request()
        if req is not None and bp._req_kind in ("zone", "centre"):
            t = true_bay_pose(p.world)
            p.manager.note_bay_scan_match(BayScanPose(x=t.x, y=t.y, heading=t.heading, inliers=0.66, margin=0.17, median_m=0.01), at=p.clock.now, request_id=req[0])
        ev = p.manager.status().last_event
        if ev and ev not in seen:
            seen.append(ev)
        ys.append(abs(true_bay_pose(p.world).y))
        if p.manager.phase is DockPhase.TURNING or done(p.manager):
            break
        p.world.step()
        p.clock.now += DT
    assert p.world.goals == [], seen
    assert any(e and e.startswith("pit-in: centring") for e in seen), (seen, p.manager._error)
    assert p.manager.phase is DockPhase.TURNING, (p.manager.state, p.manager._error, seen)
    assert ys[-1] <= CFG.bay_first_lateral_m + 0.005 and ys[0] > 0.04, (ys[0], ys[-1])

def test_the_saved_nose_in_pose_passes_the_row_gates_and_only_the_heading_window_differs():
    ref = PINKY_PRO.scan_view(DATA["seat_reference"], forward_deg=180.0).points
    m = locate(ref, PINKY_PRO.scan_view(DATA["run5_end"][0], forward_deg=180.0).points)
    assert m.inliers >= CFG.bay_scan_inlier_min and m.margin >= CFG.bay_scan_margin_min and abs(m.x - 0.257) < 0.01        # inliers 0.75, margin 0.46: the row gates hold
    assert scan_geometry(m, STAGING, CFG) is None                                                                          # pose_gate / scan_geometry: the 45 deg heading window only
    geo = backout_geometry(m, _camera(m.y), CFG)
    assert geo is None or geo[0] == m.x
    geo = backout_geometry(m, _camera(m.y), CFG)
    assert geo is not None and abs(geo[1]) < 0.02
    assert backout_geometry(BayScanPose(x=m.x, y=m.y, heading=m.heading, inliers=m.inliers, margin=0.30, median_m=0.01), None, CFG) is None      # margin below 0.40
    assert backout_geometry(BayScanPose(x=m.x, y=m.y, heading=m.heading, inliers=0.65, margin=m.margin, median_m=0.01), None, CFG) is None       # inliers below 0.70
    assert backout_geometry(BayScanPose(x=m.x, y=m.y, heading=m.heading - math.pi, inliers=m.inliers, margin=m.margin, median_m=0.01), None, CFG) is None   # nose out
    assert backout_geometry(m, _camera(m.y + 0.08), CFG) is None                                                    # the measured camera lateral disagrees


def _nose_in(front=1.0, rear=0.707, margin=0.46, staging=None, heading=None, start=-0.306, inliers=0.75, track_inliers=None, jump=None, y0=0.0, on_tick=None):
    from test_docking_bay_scan_pose import true_bay_pose  # noqa: PLC0415
    p = a_bay()
    with_reference(p)
    p.world.pose = (start, y0, 0.0)                                        # bay x 0.256 (the saved pose), nose toward the bay
    p.manager.dock()
    if staging is not None:
        p.manager._dock_type.staging_offset_m = staging
    bp = p.manager._bay_phases
    bp._observation = lambda: _camera(true_bay_pose(p.world).y)
    seen, cmds, phases = [], [], []
    for k in range(6000):
        t = true_bay_pose(p.world)
        if on_tick is not None:
            on_tick(p, bp, k)
        if k % 2 == 0:
            p.detector.capture()
            p.manager.note_body_scan(None, t.x + CFG.bay_empty_front_extra_m if front is None else front, rear, p.clock.now)
        p.manager.tick()
        req = p.manager.bay_scan_request()
        if req is not None and bp._req_kind in ("zone", "centre"):
            tracked = bp._req_track
            dx = 0.0 if jump is None else jump(t, k, tracked)
            p.manager.note_bay_scan_match(BayScanPose(x=t.x + dx, y=t.y, heading=t.heading if heading is None else heading,
                                                      inliers=(track_inliers or inliers) if tracked else inliers, margin=1.0 if tracked else margin, median_m=0.01),
                                          at=p.clock.now, request_id=req[0])
        ev = p.manager.status().last_event
        if ev and ev not in seen:
            seen.append(ev)
        if p.manager.phase is not None and (not phases or phases[-1] is not p.manager.phase):
            phases.append(p.manager.phase)
        cmds.append((p.manager.phase, p.world.command, t.x))
        if p.manager.phase is DockPhase.TURNING or done(p.manager):
            break
        p.world.step()
        p.clock.now += DT
    return p, bp, seen, cmds


def test_from_nose_in_inside_the_lane_it_backs_straight_out_to_the_junction_then_turns_and_never_moves_toward_the_bay():
    p, bp, seen, cmds = _nose_in(front=None)
    assert p.world.goals == [], seen
    assert p.manager.phase is DockPhase.TURNING, (p.manager.state, p.manager._error, seen)
    assert not [c for ph, c, x in cmds if c[0] > 0.0], "it moved toward the bay"                         # no forward command at all
    assert any(c[0] < 0.0 for ph, c, x in cmds) and cmds[-1][2] >= CFG.bay_turn_x_min_m                    # reversed out to the turn point (0.38-0.45)
    assert any(e and e.startswith("pit-in: nose toward the bay inside the lane") for e in seen), seen
    assert any(e and e.startswith("pit-in: backed out to x") for e in seen), seen
    assert any(e and e.startswith("pit-in: at the staging junction") for e in seen), seen


def test_nose_in_with_something_behind_stops_with_a_person_call_and_a_weak_pose_is_refused_not_moved():
    p, bp, seen, cmds = _nose_in(front=None, rear=0.05)
    assert p.manager.state is DockState.DOCK_FAILED and "something behind the tray" in p.manager._error, p.manager._error
    assert any(k == "docking.person_call" for k, d in p.events)
    q, qb, seen, cmds = _nose_in(front=None, margin=0.30)
    assert q.manager.state is DockState.DOCK_FAILED and not [c for ph, c, x in cmds if c != (0.0, 0.0)], q.manager._error      # refused, no motion
    assert any(k == "docking.person_call" for k, d in q.events)

def test_where_a_turn_is_allowed_is_absolute_not_the_dock_types_staging_offset():
    # the live dock type bay_line_c has staging_offset_m 0.32 (band 0.20..0.44 turned a robot at x 0.257 INSIDE the row): the floor/ceiling are config, 0.38 / 0.45
    ref = PINKY_PRO.scan_view(DATA["seat_reference"], forward_deg=180.0).points
    m = locate(ref, PINKY_PRO.scan_view(DATA["run5_end"][0], forward_deg=180.0).points)       # x 0.257, nose in, inliers 0.75, margin 0.46
    cam = _camera(m.y)
    assert junction_geometry(m, cam, CFG) is None and junction_candidate(m, CFG) is False     # not a turn point
    assert backout_geometry(m, cam, CFG) is not None                                          # it backs out instead
    at41 = BayScanPose(x=0.41, y=m.y, heading=m.heading, inliers=0.68, margin=0.16, median_m=0.01)
    assert junction_geometry(at41, _camera(m.y), CFG) is not None and backout_geometry(at41, _camera(m.y), CFG) is None
    assert CFG.bay_turn_x_min_m > CFG.bay_line_x_m and CFG.bay_turn_x_min_m <= CFG.bay_turn_x_target_m <= CFG.bay_turn_x_max_m


def test_with_the_live_staging_offset_032_the_saved_nose_in_pose_backs_out_and_does_not_turn():
    p, bp, seen, cmds = _nose_in(front=None, staging=0.32)
    assert not any(ph is DockPhase.TURNING and x < CFG.bay_turn_x_min_m - 0.005 for ph, c, x in cmds), "it turned inside the row"
    assert p.manager.phase is DockPhase.TURNING and cmds[-1][2] >= CFG.bay_turn_x_min_m, (p.manager._error, seen)
    assert not [c for ph, c, x in cmds if c[0] > 0.0]


def test_a_skewed_nose_in_pose_after_a_cancelled_turn_is_refused_with_a_person_call_and_no_motion():
    # the bench: a cancelled in-place turn left it at heading 136 deg at x 0.257
    p, bp, seen, cmds = _nose_in(front=None, staging=0.32, heading=math.radians(136.0))
    assert p.manager.state is DockState.DOCK_FAILED and "not moving, not turning in the row" in p.manager._error, p.manager._error
    assert not [c for ph, c, x in cmds if c != (0.0, 0.0)]
    assert any(k == "docking.person_call" for k, d in p.events)


def test_the_saved_x_0316_nose_in_pose_is_below_the_row_gates_and_backs_out_on_the_weak_tier_with_the_modelled_depth():
    ref = PINKY_PRO.scan_view(DATA["seat_reference"], forward_deg=180.0).points
    for sc in DATA["nosein2_end"]:
        view = PINKY_PRO.scan_view(sc, forward_deg=180.0)
        m = locate(ref, view.points)
        assert abs(m.x - 0.316) < 0.01 and m.inliers < CFG.bay_scan_inlier_min                                        # the row gate (0.70) is not met
        assert backout_geometry(m, _camera(m.y), CFG) is None                                                       # row tier: no
        assert backout_geometry(m, _camera(m.y), CFG, weak=True) is not None                                        # junction-level fit + camera lateral
        assert backout_geometry(m, None, CFG, weak=True) is None                                                     # needs the measured camera lateral
        assert backout_geometry(m, _camera(m.y + 0.06), CFG, weak=True) is None
        assert abs(PINKY_PRO.translation_gap(view.points) - expected_front_gap(ref, m.x, m.y, m.heading, CFG)) < 0.02   # the depth evidence: 0.398 vs 0.404


def test_from_x_0316_with_a_weak_pose_it_backs_out_tracked_to_the_turn_point_without_a_forward_move():
    # the start (zone answer) is weak (inliers 0.67), the tracked poses above the line 0.62 (< the 0.70 row gate): it must keep the track to the junction
    p, bp, seen, cmds = _nose_in(front=None, staging=0.32, start=-0.366, inliers=0.67, margin=0.25, track_inliers=0.62)
    assert p.manager.phase is DockPhase.TURNING and cmds[-1][2] >= CFG.bay_turn_x_min_m, (p.manager._error, seen)
    assert not [c for ph, c, x in cmds if c[0] > 0.0] and not any(ph is DockPhase.TURNING and x < CFG.bay_turn_x_min_m for ph, c, x in cmds)
    assert any(e and e.startswith("pit-in: nose toward the bay inside the lane (LiDAR x 0.31") for e in seen), seen


def test_a_weak_nose_in_pose_with_an_occupied_depth_is_refused_with_a_person_call_never_the_map():
    p, bp, seen, cmds = _nose_in(front=0.30, staging=0.32, start=-0.366, inliers=0.67, margin=0.25)
    assert p.manager.state is DockState.DOCK_FAILED and "not moving, not turning in the row" in p.manager._error, p.manager._error
    assert "occupied or not measurable" in p.manager._error and p.world.goals == []
    assert not [c for ph, c, x in cmds if c != (0.0, 0.0)] and any(k == "docking.person_call" for k, d in p.events)


def test_the_back_out_track_is_bounded_a_jump_is_dropped_the_pose_ages_and_the_failure_names_the_leg():
    p, bp, seen, cmds = _nose_in(front=None, staging=0.32, jump=lambda t, k, tracked: 0.08 if tracked and t.x > 0.30 else 0.0)
    assert p.manager.state is DockState.DOCK_FAILED and "bay pit-in back-out: no fresh LiDAR bay pose" in p.manager._error, p.manager._error
    assert any(e and "jumped from the carried pose" in e for e in seen), seen
    assert cmds[-1][1] == (0.0, 0.0) and any(k == "docking.person_call" for k, d in p.events)


def test_no_rear_gap_measured_behind_the_tray_stops_the_back_out():
    p, bp, seen, cmds = _nose_in(front=None, rear=None)
    assert p.manager.state is DockState.DOCK_FAILED and "no rear gap measured" in p.manager._error, p.manager._error


def test_a_pit_in_dock_never_retries_through_nav2_staging():
    p, bp = _at_the_junction(0.562)
    p.manager._phase = DockPhase.ACQUIRING
    p.manager._retry("bay line lost")
    assert p.manager.state is DockState.DOCK_FAILED and "no retry through Nav2 staging" in p.manager._error
    assert p.world.goals == []


def test_the_nose_in_footprint_guard_holds_above_the_bay_line_up_to_the_turn_floor():
    # x 0.31-0.37 is above the 0.30 line but below the 0.38 floor: a skewed body there still stops the back-out
    p, bp, seen, cmds = _nose_in(front=None, staging=0.32, start=-0.366, inliers=0.75, y0=0.05, heading=math.radians(168.0))
    assert p.manager.state is DockState.DOCK_FAILED, (p.manager.state, seen)
    assert "footprint would leave the lane" in p.manager._error or "not moving" in p.manager._error, p.manager._error

def test_a_stale_zone_checked_flag_from_the_last_dock_cannot_skip_the_zone_check_into_nav2_staging():
    # b8xy nosein-4: the previous pit-in dock left _zone_checked True; the next dock's first _begin_staging consumed it and went straight to a Nav2 goal, no verdict, no journal
    p, bp = _at_the_junction(0.562)
    assert bp._zone_checked is False                                     # a pit-in turn no longer leaves it set
    q = a_bay()
    with_reference(q)
    q.world.pose = (-0.306, 0.0, 0.0)
    q.manager._bay_phases._zone_checked = True                           # the stale state
    q.manager.dock()
    for k in range(6):                                                   # the first ticks, before any LiDAR bay pose or camera observation exists
        q.manager.tick()
        q.world.step()
        q.clock.now += DT
    assert q.world.goals == [] and q.manager._bay_phases._zone == "check"


def test_the_first_ticks_with_no_scan_pose_yet_never_send_a_goal_and_the_refusal_calls_a_person():
    p = a_bay()
    with_reference(p)
    p.world.pose = (-0.306, 0.0, 0.0)
    p.manager.dock()
    for _ in range(int(CFG.bay_scan_pose_wait_s / DT) + 40):             # nobody answers the zone request
        p.manager.tick()
        assert p.world.goals == []
        if done(p.manager):
            break
        p.world.step()
        p.clock.now += DT
    assert p.manager.state is DockState.DOCK_FAILED and "no LiDAR bay pose answer" in p.manager._error
    assert any(k == "docking.person_call" for k, d in p.events)


def test_the_back_out_track_is_bounded_cumulatively_against_the_start_pose():
    n = {"k": 0}

    def creeping(t, k, tracked):
        if not tracked:
            return 0.0
        n["k"] += 1
        return 0.012 * n["k"]                                              # each step within 2.5 cm of the last accepted pose, the sum far beyond 5 cm
    p, bp, seen, cmds = _nose_in(front=None, jump=creeping)
    assert p.manager.state is DockState.DOCK_FAILED and any(e and "jumped from the carried pose" in e for e in seen), (p.manager._error, seen)
    assert p.manager.phase is not DockPhase.TURNING


def test_a_failing_pit_in_turn_calls_a_person():
    p, bp = _at_the_junction(0.562)
    assert p.manager.phase is DockPhase.TURNING
    p.manager._fail("bay turn not clear")
    assert any(k == "docking.person_call" for k, d in p.events)


def test_the_in_place_heading_align_of_a_pit_in_dock_needs_the_turn_floor():
    p, bp = _at_the_junction(0.562)
    bp._pitin, bp._in_row = True, False
    bp._entry_match = (BayScanPose(x=0.30, y=0.0, heading=0.0, inliers=0.8, margin=0.6, median_m=0.01), p.clock.now)
    assert bp._try_heading_align(p.clock.now, 0.0, 0.35) is False         # below 0.38: no in-place turn
    bp._entry_match = (BayScanPose(x=0.40, y=0.0, heading=0.0, inliers=0.8, margin=0.6, median_m=0.01), p.clock.now)
    bp._align_n = 0
    assert bp._try_heading_align(p.clock.now, 0.0, 0.35) is True


def test_the_back_out_footprint_guard_takes_the_worst_heading_over_the_pose_age():
    p, bp = _at_the_junction(0.562)
    t = p.clock.now
    for age, stops in ((0.0, False), (0.6, True)):
        q, qb = _at_the_junction(0.562)
        qb._cen = {"since": q.clock.now, "lost": None, "leg": "backout", "x0": 0.33, "mark": 0.0, "start": (0.33, 0.01, math.pi)}
        m = BayScanPose(x=0.33, y=0.01, heading=math.pi + 0.12, inliers=0.8, margin=1.0, median_m=0.01)      # lateral +10 mm in the dock frame
        qb._cen_pose = (m, q.clock.now - age, 0.0)
        q.manager._state = DockState.DOCKING
        q.manager._phase = DockPhase.STAGING
        q.manager.note_body_scan(None, 0.9, 0.7, q.clock.now)
        qb._tick_backout(q.clock.now, qb._cen, m, 0.33, 0.0)
        assert (q.manager.state is DockState.DOCK_FAILED and "footprint would leave the lane" in q.manager._error) == stops, (age, q.manager._error)


def test_a_late_tracked_answer_at_the_end_of_the_back_out_does_not_end_the_zone_wait_nosein_5():
    # b8xy nosein-5: the back-out reached x 0.396 with a tracked request still open; its answer (0.67 < 0.70, dropped) fell into the zone branch, ended the wait with no match
    # and the zone verdict said "acquire" on the camera: ACQUIRING + a settle creep toward the bay. It must run the junction verdict instead.
    state = {"done": False}

    def stray(p, bp, k):
        if not state["done"] and bp._zone == "check" and bp._cen is None and p.manager.phase is not None and bp._last_lidar is not None and k > 20:
            state["done"] = True
            bp._req_open, bp._req_kind, bp._req_track, bp._req_t = 999, "centre", True, p.clock.now
            p.manager.note_bay_scan_match(BayScanPose(x=0.396, y=0.003, heading=math.radians(178.0), inliers=0.67, margin=1.0, median_m=0.01), at=p.clock.now, request_id=999)
    p, bp, seen, cmds = _nose_in(front=None, staging=0.32, on_tick=stray, inliers=0.75)
    assert state["done"]
    assert p.manager.phase is DockPhase.TURNING, (p.manager.state, p.manager._error, seen)
    assert not any(ph is DockPhase.ACQUIRING for ph, c, x in cmds) and not [c for ph, c, x in cmds if c[0] > 0.0] and p.world.goals == []
    assert not any(e and "bay zone verdict acquire" in e for e in seen) and any(e and e.startswith("pit-in: at the staging junction") for e in seen), seen


def test_no_zone_verdict_of_a_reference_dock_before_the_scan_pose_was_asked_for_and_never_acquire_facing_the_bay():
    p = a_bay()
    with_reference(p)
    p.world.pose = (-0.45, 0.0, 0.0)
    p.manager.dock()
    bp = p.manager._bay_phases
    bp._scan_asked = False
    bp._last_lidar = (math.pi, p.clock.now)                              # the last LiDAR bay pose faced the bay
    assert bp._facing_recent(p.clock.now) and bp._forward_block(p.clock.now, p.clock.now - 1.0).startswith("the last LiDAR bay pose has the nose toward the bay")
    assert bp._forward_block(p.clock.now, p.clock.now - 1.0, facing_ok=True) != bp._forward_block(p.clock.now, p.clock.now - 1.0)
    bp._last_lidar = None
    for _ in range(5):
        p.manager.tick()                                                 # the bridge has not called bay_scan_request yet: the check waits, no verdict
        assert bp._zone == "check" and p.world.goals == []
        p.clock.now += DT


def test_a_stray_non_zone_answer_never_becomes_the_zone_answer():
    p = a_bay()
    with_reference(p)
    p.manager.dock()
    bp = p.manager._bay_phases
    bp._req_open, bp._req_kind = 5, "rowpose"
    p.manager.note_bay_scan_match(None, at=p.clock.now, request_id=5)
    assert bp._scan_match is None


def test_nav2_staging_by_the_map_needs_a_verified_map_otherwise_refuse_and_call_a_person():
    # b8xy: a "no fit" or weak answer at the junction went to Nav2 staging on the map (1 goal); a reference-scan dock stages by the map only with the caller's verified
    # site pose (dock(site_pose_verified=True)) or a good LiDAR fit that agrees with the map pose
    for answer in (None, BayScanPose(x=0.40, y=0.0, heading=0.0, inliers=0.68, margin=0.17, median_m=0.01)):
        p = a_bay()
        with_reference(p)
        p.world.pose = (-0.45, 0.0, math.pi)
        p.manager.dock()
        bp = p.manager._bay_phases
        for k in range(400):
            if k % 2 == 0:
                p.detector.capture()
                p.manager.note_body_scan(None, 0.9, 0.9, p.clock.now)
            p.manager.tick()
            req = p.manager.bay_scan_request()
            if req is not None and bp._req_kind == "zone":
                p.manager.note_bay_scan_match(answer, at=p.clock.now, request_id=req[0])
            if done(p.manager):
                break
            p.world.step()
            p.clock.now += DT
        assert p.world.goals == [], answer
        assert p.manager.state is DockState.DOCK_FAILED and "not staging by the map" in p.manager._error, (answer, p.manager._error)
        assert any(k == "docking.person_call" for k, d in p.events)
    q = a_bay()
    with_reference(q, verified=True)                                     # accepted site_pose_evidence: Nav2 staging is allowed
    q.world.pose = (-0.45, 0.0, math.pi)
    q.manager.dock()
    for k in range(400):
        if k % 2 == 0:
            q.detector.capture()
            q.manager.note_body_scan(None, 0.9, 0.9, q.clock.now)
        q.manager.tick()
        r = q.manager.bay_scan_request()
        if r is not None and q.manager._bay_phases._req_kind == "zone":
            q.manager.note_bay_scan_match(None, at=q.clock.now, request_id=r[0])
        if q.world.goals:
            break
        q.world.step()
        q.clock.now += DT
    assert q.world.goals


def test_cancel_fail_and_docked_clear_the_bay_state_and_a_new_reference_scan_invalidates_the_cached_depth():
    p, bp = _at_the_junction(0.562)
    assert bp._pitin
    p.manager.cancel()
    assert not bp._pitin and bp._zone is None and bp._scan_match is None and bp._cen is None and bp._last_lidar is None
    q, qb = _at_the_junction(0.562)
    qb._ref_points = (q.manager._dock.id, [(0.1, 0.0)])
    qb.note_seat_gap(q.manager._dock.id, 0.09, [(0.1, 0.0)])
    key0 = qb._seat_key
    q.manager._dock.metadata["reference_scan"] = {**q.manager._dock.metadata["reference_scan"], "ranges": [1.0] * 700}     # re-taught
    qb.new_dock()
    assert qb._ref_points is None and qb._seat_gap is None and qb._seat_key is None and key0 is not None
    assert qb.bay_identity == "unknown"


def test_the_centring_shuttle_and_the_over_edge_allowance_ship_off_and_a_6_cm_arrival_is_refused_not_moved():
    # off until 3 bench runs (reviewer B, 2026-11-21)
    assert CFG.bay_centre_tries == 0 and CFG.bay_junction_lateral_m == CFG.bay_first_lateral_m == 0.03 and CFG.bay_reseat_over_edge_m == 0.0
    p = a_bay()
    with_reference(p)                                                  # no accepted site_pose_evidence: the map path is not open either
    p.world.pose = (-0.45, -0.06, 0.0)
    p.manager.dock()
    bp = p.manager._bay_phases
    from test_docking_bay_scan_pose import true_bay_pose  # noqa: PLC0415
    bp._observation = lambda: _camera(true_bay_pose(p.world).y)
    cmds = []
    for k in range(2000):
        if k % 2 == 0:
            p.detector.capture()
            p.manager.note_body_scan(None, true_bay_pose(p.world).x + CFG.bay_empty_front_extra_m, 0.9, p.clock.now)
        p.manager.tick()
        req = p.manager.bay_scan_request()
        if req is not None and bp._req_kind in ("zone", "centre"):
            t = true_bay_pose(p.world)
            p.manager.note_bay_scan_match(BayScanPose(x=t.x, y=t.y, heading=t.heading, inliers=0.66, margin=0.17, median_m=0.01), at=p.clock.now, request_id=req[0])
        cmds.append(p.world.command)
        if done(p.manager):
            break
        p.world.step()
        p.clock.now += DT
    assert p.manager.state is DockState.DOCK_FAILED and p.world.goals == []
    assert not [c for c in cmds if c != (0.0, 0.0)], "it moved"                                  # refused, no motion (not even a turn)
    assert any(k == "docking.person_call" for k, d in p.events), p.manager._error


def test_nose_in_camera_lateral_sign_and_map_verified_localization_gate():
    from core_features.docking import bay_zone

    obs_nose = _camera(0.02)
    assert bay_zone._camera_dock_lateral(obs_nose, math.pi) == pytest.approx(-0.02)
    assert bay_zone._camera_dock_lateral(obs_nose, 0.0) == pytest.approx(0.02)

    p = a_bay()
    with_reference(p, verified=True)
    p.world.pose = (-0.45, 0.0, math.pi)
    p.manager.dock()
    p.manager.localization_ok = lambda: False
    assert p.manager._bay_phases._map_verified(p.world.pose) == "localization is not LOCALIZED before Nav2 staging"


def test_classify_allows_entry_heading_after_past_first_x_and_clamps_creep():
    from core_features.docking import bay_zone

    p = a_bay()
    with_reference(p)
    yaw = math.pi - math.radians(10.0)
    obs = DockObservation(x=0.40 * math.cos(yaw), y=0.40 * math.sin(yaw), yaw=yaw, confidence=1.0, at=0.0)
    assert bay_zone.classify((0.0, 0.0, 0.0), p.manager._dock, 0.45, obs, CFG, scan=(0.25, 0.0, math.radians(10.0))).kind == "acquire"
    p.manager.dock()
    bp = p.manager._bay_phases
    p.manager._phase = DockPhase.ACQUIRING
    bp._in_row, bp._crept = True, False
    bp._row_pose = (0.295, 0.0, 0.0, p.clock.now, 0.0)
    bp._observation = lambda: _camera(0.0)
    bp._tick_acquiring(p.clock.now)
    assert bp._crept is True and p.world.command == (0.0, 0.0)
