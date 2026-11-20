"""Inside the rails ALIGNING steers on the LiDAR scan pose; the camera heading lies there (y8xs survey: -11..-19 deg)."""

from __future__ import annotations

import math

from core_common.protocol.schemas import DockState
from core_features.docking.manager import DockPhase
from test_docking_bay import DT, a_bay, done
from test_docking_bay_scan_pose import true_bay_pose, with_reference


def run(p, gap_of=None, lie_deg=-15.0, lidar=True, lidar_after=None, limit_s=240.0, along_lie=0.0, stop_when=None, unmeasured=False, seat=True):
    """The sim camera heading lies by lie_deg once the robot is within 0.21 m of the seat; the LiDAR pose answers are the truth."""
    capture = p.detector.capture
    lie = math.radians(lie_deg)

    def lying():
        capture()
        if p.detector.latest is not None and -p.world.pose[0] - 0.05 <= 0.21:
            p.detector.latest = p.detector.latest.model_copy(update={"yaw": p.detector.latest.yaw - lie})
        if p.detector.latest is not None and (along_lie or unmeasured) and -p.world.pose[0] - 0.05 <= 0.21:
            p.detector.latest = p.detector.latest.model_copy(update={"x": p.detector.latest.x - along_lie, "along_measured": not unmeasured})
    p.detector.capture = lying
    if seat:
        p.manager.note_bay_seat_gap("bay1", 0.01)
    yaws, t0, k = [], p.clock.now, 0
    while p.clock.now - t0 < limit_s:
        if k % 2 == 0:
            p.detector.capture()
            gap = gap_of(p) if gap_of else max(0.0, -p.world.pose[0] - 0.05) + 0.01
            p.manager.note_body_scan(None, None, gap, p.clock.now)
        p.manager.tick()
        request = p.manager.bay_scan_request()
        on = lidar and (lidar_after is None or -p.world.pose[0] - 0.05 > lidar_after)
        if request is not None and (on or p.manager._bay_phases._req_kind == "zone"):      # the zone check must be answered (a reference dock never decides on the map alone)
            p.manager.note_bay_scan_match(true_bay_pose(p.world), request_id=request[0])
        if p.manager.phase is DockPhase.ALIGNING:
            yaws.append(p.world.pose[2])
        if done(p.manager) or (stop_when and stop_when(p)):
            break
        p.world.step()
        p.clock.now += DT
        k += 1
    return yaws


def test_the_robot_seats_straight_although_the_camera_heading_lies_by_15_deg_near_the_seat():
    p = a_bay()
    with_reference(p, verified=True)
    p.world.arrival_error = (0.0, 0.0)
    p.manager.dock()
    yaws = run(p)
    assert p.manager.state is DockState.DOCKED, p.manager._error
    assert max(abs(math.remainder(y - math.pi, math.tau)) for y in yaws) < math.radians(4.0)
    assert abs(math.remainder(p.world.pose[2] - math.pi, math.tau)) < math.radians(2.0)


def test_without_a_fresh_lidar_pose_inside_the_rails_it_stops_and_fails_never_steering_on_the_camera():
    p = a_bay()
    with_reference(p, verified=True)
    p.manager.dock()
    run(p, lidar_after=0.20)                              # the LiDAR pose stops being answered inside x <= 0.20
    assert p.manager.state is DockState.DOCK_FAILED and "no fresh LiDAR pose" in p.manager._error, p.manager._error
    assert -p.world.pose[0] - 0.05 > 0.0


def test_the_angular_rate_inside_the_rails_is_bounded_small():
    p = a_bay()
    with_reference(p, verified=True)
    p.manager.dock()
    run(p)
    inside = [c for ph, c in p.world.commands if ph is DockPhase.ALIGNING and c[0] < 0.0]
    assert inside and max(abs(c[1]) for c in inside[-40:]) <= p.manager._cfg.bay_rail_max_angular + 1e-9

def _in_rails(p):
    lp = p.manager._bay_phases._lp
    return p.manager.phase is DockPhase.ALIGNING and lp is not None and lp[0] <= 0.2


def test_a_lidar_pose_that_jumps_from_the_predicted_one_or_disagrees_with_the_rear_gap_is_not_evidence():
    from core_features.docking.bay_scan_pose import BayScanPose  # noqa: PLC0415
    p = a_bay()
    with_reference(p, verified=True)
    p.manager.dock()
    run(p, stop_when=_in_rails)
    bp = p.manager._bay_phases
    before = bp._lp
    est = bp._est
    now = p.clock.now
    jump = BayScanPose(x=before[0], y=-(est[0] + 0.05), heading=est[1], inliers=0.95, margin=0.6, median_m=0.003)       # 5 cm sideways
    bp.ls_note(jump, now)
    assert bp._lp == before
    p.manager.note_body_scan(None, None, 0.5, now)                                                                     # rear gap says x ~ 0.49
    bp.ls_note(BayScanPose(x=before[0], y=-est[0], heading=est[1], inliers=0.95, margin=0.6, median_m=0.003), now)
    assert bp._lp == before


def test_the_travel_cap_and_the_stop_come_from_the_lidar_x_when_the_camera_along_drifts():
    # no seated gap (no LiDAR seat end) and the camera along 0.2 m too long: the LiDAR x still bounds the reverse at the stop face
    p = a_bay()
    with_reference(p, verified=True)
    p.manager.dock()
    run(p, along_lie=0.2, seat=False, gap_of=lambda p: None)         # no rear-band point either: only the LiDAR x bounds it
    assert p.manager.state is DockState.DOCKED, p.manager._error
    assert abs(p.world.pose[0] + 0.05) < 1e-6


def test_no_lidar_pose_and_no_measured_along_stops_instead_of_steering_on_the_camera():
    p = a_bay()
    with_reference(p, verified=True)
    p.manager.dock()
    run(p, lidar=False, unmeasured=True)
    assert p.manager.state is DockState.DOCK_FAILED and ("no LiDAR pose and no measured along" in p.manager._error or "no fresh LiDAR pose" in p.manager._error), p.manager._error
    assert -p.world.pose[0] - 0.05 > 0.0                 # it stopped before the seat
    assert p.world.command[0] == 0.0

def test_a_reverse_the_lidar_sees_held_in_the_rails_stops_and_fails():
    # R5: the wheels turn, the body (so the rear gap and the scan pose) does not change: the slip rule is off in the rails, this is its LiDAR form
    p = a_bay()
    with_reference(p, verified=True)
    p.manager.dock()
    held = {}
    step = p.world.step

    def stuck():
        step()
        if p.manager.phase is DockPhase.ALIGNING and -p.world.pose[0] - 0.05 <= 0.15:
            held.setdefault("pose", p.world.pose)
            p.world.pose = held["pose"]                   # wheels turn (odometry counts), the body stays
    p.world.step = stuck
    run(p, lie_deg=0.0)
    assert p.manager.state is DockState.DOCK_FAILED and ("reverse stalled in the rails" in p.manager._error or "no fresh LiDAR pose" in p.manager._error), p.manager._error      # reseats first, then stopped (the body stays held)


def test_without_a_seated_gap_the_camera_along_feeds_the_rear_guard_in_the_rails():
    p = a_bay()
    with_reference(p, verified=True)
    p.manager.dock()
    run(p, seat=False, lie_deg=0.0, stop_when=_in_rails)
    for _ in range(4):
        p.manager.tick()
        p.clock.now += DT
    bp = p.manager._bay_phases
    bp._lidar_steer(p.clock.now)
    assert bp._seat_gap is None and bp._rear_along == bp._along_m
