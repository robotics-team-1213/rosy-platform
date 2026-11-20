"""User rule 2026-11-21: bay docking exists to KEEP THE PARKING LINES (case I: re-dock from inside the lane never leaves it; case II: return from outside
enters along the line)."""

from __future__ import annotations

import math

from core_common.protocol.schemas import DockState
from core_features.docking.manager import DockPhase
from test_docking_bay import a_bay
from test_docking_bay_scan_pose import answer_kinds, good, true_bay_pose, with_reference
from test_docking_bay_zone import a_row, run_row


def test_a_reference_dock_skewed_in_its_lane_never_goes_out_to_staging():
    # case I: the old "exit" verdict drove to staging 0.34 (past the bay line) and turned 180 there; now it stops and says so
    p, row = a_row(start=(-0.12, 0.0, math.pi - math.radians(10.0)), others=())
    with_reference(p)
    p.manager.dock()
    run_row(p, row, until=answer_kinds(zone=good(x=0.07, heading=math.radians(-10.0))))
    assert p.manager.state is DockState.DOCK_FAILED and "leaving the lane to stage is not allowed" in p.manager._error, p.manager._error
    assert "leaving the lane to stage" in p.manager.status().last_event
    assert not p.world.goals and not [c for ph, c in p.world.commands if c[0] > 0.0]


def test_a_straight_centred_robot_in_its_lane_still_docks_by_the_lidar_reverse():
    p, row = a_row(start=(-0.12, 0.0, math.pi), others=())
    with_reference(p)
    p.manager.dock()
    run_row(p, row, until=answer_kinds(zone=good(x=0.07)))
    assert p.manager.state is DockState.DOCKED, p.manager._error
    assert not p.world.goals


def test_a_forward_move_past_the_bay_line_or_out_of_the_lane_is_blocked():
    p = a_bay()
    with_reference(p)
    p.manager.dock()
    bp = p.manager._bay_phases
    bp._in_row = True
    bp._row_pose = (0.30, 0.0, 0.0, 1.0)                 # 0.30 + the 0.15 back-off would reach the 0.40 line
    assert "pass the bay line" in bp._row_forward_reason()
    bp._row_pose = (0.10, 0.06, 0.0, 1.0)                # 60 mm off the lane centre
    assert "left the lane" in bp._row_forward_reason()
    bp._row_pose = (0.10, 0.01, 0.0, 1.0)
    assert bp._row_forward_reason() is None
    bp._in_row = False                                   # case II: not in the row yet, the guard does not apply
    bp._row_pose = (0.30, 0.0, 0.0, 1.0)
    assert bp._row_forward_reason() is None


def test_the_reverse_stops_when_the_lidar_lateral_leaves_the_lane_inside_the_lines():
    p = a_bay()
    with_reference(p)
    p.manager.dock()
    bp = p.manager._bay_phases
    p.manager._cfg.bay_lidar_steer_along_m = 9.0
    # drive until ALIGNING with a pose, then hand it a 60 mm lateral inside the line
    until = answer_kinds(zone=good(x=1.0), entry="true")
    from test_docking_bay import DT, done  # noqa: PLC0415
    for k in range(4000):
        if k % 2 == 0:
            p.detector.capture()
            p.manager.note_body_scan(None, None, None, p.clock.now)
        p.manager.tick()
        until(p.manager)
        if p.manager.phase is DockPhase.ALIGNING and bp._lp is not None:
            break
        p.world.step()
        p.clock.now += DT
    t = p.clock.now
    bp._lp = (0.20, 0.06, 0.0, t, 0.0)
    bp._lidar_steer(t)
    assert p.manager.state is DockState.DOCK_FAILED and "bay left the lane" in p.manager._error, p.manager._error
    assert "bay left the lane" in p.manager.status().last_event

def test_the_lane_footprint_sign_is_asymmetric_a_ccw_heading_swings_the_tray_to_the_right():
    # panel B R1: lateral = -y (left +y), heading ccw+ (spin test w>0 = LiDAR +). Real corner lateral = lateral - fx*sin(h) -+ hy*cos(h)
    from core_features.docking.bay_zone import lane_extent  # noqa: PLC0415
    from core_features.docking.model import DockingConfig  # noqa: PLC0415
    cfg = DockingConfig()
    h = math.radians(10.0)
    assert lane_extent(cfg, 0.030, h) > cfg.bay_lane_edge_m          # +30 mm (right) and a ccw 10 deg: the tray corner reaches 0.109
    assert lane_extent(cfg, -0.030, h) <= cfg.bay_lane_edge_m        # -30 mm (left) with the same heading: 0.093
    assert lane_extent(cfg, -0.030, -h) > cfg.bay_lane_edge_m        # mirrored
    assert lane_extent(cfg, 0.030, -h) <= cfg.bay_lane_edge_m
    # the grid survey (loop/scans manifest, hp10 rows: th +10 deg, y -0.006 = lateral +6 mm): the corners as the pose convention puts them
    # span y -0.085..+0.058 (tray to the right), the mirrored footprint would put them at -0.069..+0.074
    assert round(lane_extent(cfg, 0.0056, math.radians(10.13)), 3) == 0.085


def test_the_lane_check_allowed_offset_shrinks_with_heading():
    from core_features.docking.bay_zone import lane_extent  # noqa: PLC0415
    from core_features.docking.model import DockingConfig  # noqa: PLC0415
    cfg = DockingConfig()

    def worst(lat, deg):
        return max(lane_extent(cfg, lat, math.radians(deg)), lane_extent(cfg, lat, math.radians(-deg)))
    assert worst(0.047, 0.0) <= cfg.bay_lane_edge_m < worst(0.05, 0.0)
    assert worst(0.035, 10.0) > cfg.bay_lane_edge_m >= worst(0.025, 10.0)
    assert worst(0.03, 15.0) > cfg.bay_lane_edge_m >= worst(0.012, 15.0)


def test_a_forward_move_in_the_row_needs_a_fresh_lidar_bay_pose():
    # panel B R2: a map/camera "acquire" leaves no LiDAR pose; the creep waits for one (asked before the creep), then fails if none comes
    p = a_bay()
    with_reference(p)
    p.manager.dock()
    bp = p.manager._bay_phases
    bp._in_row = True
    bp._row_pose = None
    assert bp._row_forward_reason(0.04, 10.0, 9.0) == "wait"
    assert "no fresh LiDAR bay pose" in bp._row_forward_reason(0.04, 60.0, 9.0)
    bp._row_pose = (0.1, 0.0, 0.0, 9.5)                  # 0.5 s old
    assert bp._row_forward_reason(0.04, 10.0, 9.0) is None
    bp._row_pose = (0.1, 0.0, 0.0, 8.0)                  # 2 s old
    assert bp._row_forward_reason(0.04, 10.0, 9.0) == "wait"


def test_no_in_place_heading_align_inside_the_row():
    # the tray corner turning circle (0.29 m) exceeds the lane (0.21 m): case I never turns in place
    p = a_bay()
    with_reference(p)
    p.manager.dock()
    bp = p.manager._bay_phases
    bp._in_row = True
    assert bp._try_heading_align(p.clock.now, 0.0, math.radians(20.0)) is False
    assert bp._align is None

def test_a_back_off_in_the_row_keeps_asking_for_a_fresh_bay_pose():
    # panel B P2: a legitimate in-row back-off must not fail on a stale pose
    from core_features.docking.model import DockPhase as Ph  # noqa: PLC0415
    p = a_bay()
    with_reference(p)
    p.manager.dock()
    bp = p.manager._bay_phases
    p.world.pose = (-0.15, 0.0, math.pi)
    bp._in_row, bp._row_pose = True, (0.1, 0.0, 0.0, p.clock.now - 5.0)
    p.manager._enter(Ph.BACKOFF)
    request = p.manager.bay_scan_request()
    assert request is not None and bp._req_kind == "rowpose"
    p.manager.note_bay_scan_match(true_bay_pose(p.world), at=p.clock.now, request_id=request[0])
    assert bp._row_pose[3] == p.clock.now