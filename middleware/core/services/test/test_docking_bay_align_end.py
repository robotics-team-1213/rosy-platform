"""ALIGNING ends by the LiDAR rear gap against the stored seated reference, and a stopped line or odometry does not end it
while a FRESH scan shows the body going back (y8xs 2026-11-20 rounds 11-12: stopped at x 0.078 twice while teleop reverses
passed it). Panel B S1: cutting the scan feed restores the stop."""

from __future__ import annotations

import pytest
from core_common.protocol.schemas import DockState
from core_features.docking.manager import DockPhase
from test_docking_bay import DT, a_bay, done

STOP_FACE_X = -0.05          # world x of base_link on the stop face (test_docking_bay.DOCKED_ALONG)
SEAT_GAP = 0.008             # the seated reference's rear gap: the sim's gap is (distance to the face) + 0.01, 2 mm tolerance


def run(p, *, feed=lambda p: True, gap_of=None, seat_gap=SEAT_GAP, until=None, limit_s=240.0):
    """Drive the sim; the body scan carries the LiDAR rear gap while feed(p) says the scan feed is on."""
    gap_of = gap_of or (lambda p: max(0.0, -p.world.pose[0] + STOP_FACE_X) + 0.01)
    if seat_gap is not None:
        p.manager.note_bay_seat_gap("bay1", seat_gap)
    t0, k = p.clock.now, 0
    while p.clock.now - t0 < limit_s:
        if k % 2 == 0:
            p.detector.capture()
            if feed(p):
                p.manager.note_body_scan(None, None, gap_of(p), p.clock.now)
            else:
                p.manager.note_body_scan(None, None, None, p.clock.now - 99.0)     # nothing fresh
        p.manager.tick()
        if done(p.manager) or (until and until(p)):
            break
        p.world.step()
        p.clock.now += DT
        k += 1


def lying_picture(p):
    p.detector.frozen_in_phase = DockPhase.ALIGNING        # the line stops changing: the slip rule would end the reverse
    p.manager._cfg.bay_rear_gap_margin_m = 9.0             # keep main's "something in the bay" guard out of this slip-rule test


def test_a_stopped_picture_does_not_end_the_reverse_while_a_fresh_scan_shows_the_body_move():
    p = a_bay()
    lying_picture(p)
    p.manager.dock()
    run(p, seat_gap=None)                                   # moving evidence alone, no seated reference
    # the lying picture also steers (main's reverse law follows it), so the contact may not charge: what matters is that the
    # reverse was not ended 7 cm short by the slip rule
    assert p.world.pose[0] > STOP_FACE_X - 0.01, p.world.pose


def test_cutting_the_scan_feed_restores_the_stop():
    p = a_bay()
    lying_picture(p)
    p.manager.dock()
    run(p, feed=lambda p: p.world.pose[0] < -0.30, seat_gap=None)           # the scan feed is on until x -0.30, then cut
    assert -0.30 < p.world.pose[0] < -0.07 and p.manager.state is not DockState.DOCKED   # stopped by the slip rule as before


def test_a_scan_without_a_point_in_the_strip_is_not_moving_evidence():
    p = a_bay()
    lying_picture(p)
    p.manager.dock()
    run(p, feed=lambda p: False, seat_gap=None)
    assert p.world.pose[0] < -0.07 and p.manager.state is not DockState.DOCKED


def test_the_reverse_ends_at_the_stored_seated_gap_not_at_the_odometry_distance():
    p = a_bay()
    p.manager.dock()
    seen = {}

    def until(p):
        if p.manager.phase is DockPhase.SETTLING:
            seen.setdefault("x", p.world.pose[0])
    run(p, until=lambda p: until(p))
    assert p.manager.state is DockState.DOCKED, p.manager._error
    assert seen["x"] == pytest.approx(STOP_FACE_X, abs=0.003)      # ended by the gap, at the stop face


def test_a_seated_gap_for_another_dock_is_ignored():
    p = a_bay()
    p.manager.dock()
    run(p, seat_gap=None, until=lambda p: p.manager.phase is DockPhase.ALIGNING and p.world.pose[0] > -0.2)
    p.manager.note_bay_seat_gap("other", 0.5)                # would read "seated" at once if it counted
    run(p, seat_gap=None)
    assert p.manager.state is DockState.DOCKED and abs(p.world.pose[0] - STOP_FACE_X) < 1e-6


def run_to(p, stop, limit_s=240.0):
    t0, k = p.clock.now, 0
    while p.clock.now - t0 < limit_s:
        if k % 4 == 0:
            p.detector.capture()
            p.manager.note_body_scan(None, None, None, p.clock.now)
        p.manager.tick()
        if done(p.manager) or stop(p):
            break
        p.world.step()
        p.clock.now += DT
        k += 1


def test_the_last_retry_or_failure_reason_is_in_the_status():
    p = a_bay()
    p.manager.dock()
    assert p.manager.status().last_event is None
    p.manager._retry("probe reason")
    assert p.manager.status().last_event == "retry 1: probe reason" and p.manager.status().error is None
    p.manager._fail("probe failure")
    assert p.manager.status().last_event == "failed: probe failure"
    p.manager.dock()
    assert p.manager.status().last_event is None


def test_a_retry_from_acquiring_that_began_in_the_row_does_not_drive_out():
    # y8xs 2026-11-20 round 15: a retry after the settle creep backed out 0.15 m to x 0.34, beyond where the line is visible
    import math  # noqa: PLC0415
    p = a_bay()
    p.world.pose = (-0.15, 0.0, math.pi)
    p.manager.dock()
    run_to(p, lambda p: p.manager.phase is DockPhase.ACQUIRING and p.manager._bay_phases._crept)
    p.manager._retry("probe")
    nearest = [p.world.pose[0]]
    run_to(p, lambda p: nearest.append(p.world.pose[0]) or False)
    # the retry creeps once more at most (2 x 0.04 m); the old back-off drove 0.15 m out (to 0.34 from the creep's 0.19)
    assert max(-x for x in nearest) <= 0.15 + 0.10, max(-x for x in nearest)


def test_a_few_frames_that_do_not_match_the_pre_creep_one_are_waited_out_not_retried():
    import math  # noqa: PLC0415
    p = a_bay()
    p.world.pose = (-0.15, 0.0, math.pi)
    p.manager.dock()
    run_to(p, lambda p: p.manager.phase is DockPhase.ACQUIRING and p.manager._bay_phases._crept)
    p.detector.glitch_frames = 3                      # 0.6 s of frames 0.10 m off: another line
    run_to(p, lambda p: False)
    assert p.manager.state is DockState.DOCKED and p.manager._retries == 0, (p.manager.status(), p.manager._error)


def test_a_seated_robot_the_lidar_keeps_finding_skewed_is_reseated_inside_the_lane_then_stops_there():
    # y8xs round 16: seated at -17 deg, a straight forward back-off pivoted the body 77 deg. Now a skewed seat is corrected by bounded lane reseats on the LiDAR
    # pose (bay_reseat.py); when the tries are used up it stops where it stands, inside the lane (the sim body here is straight, so the lie persists)
    import math  # noqa: PLC0415
    from test_docking_bay_scan_pose import answer_kinds, good, with_reference  # noqa: PLC0415
    from test_docking_bay_zone import a_row, run_row  # noqa: PLC0415
    p, row = a_row(start=(-0.15, 0.0, math.pi), others=(), charges=False)
    with_reference(p)
    p.manager.dock()
    run_row(p, row, until=answer_kinds(zone=good(x=0.15), entry=good(x=0.15), seat=good(x=0.0, heading=math.radians(-17.0))))
    # (this harness feeds no rear gap, so the reseat's blind-back-off rule may stop it first; the tries-used-up path is in test_docking_bay_reseat.py)
    assert p.manager.state is DockState.DOCK_FAILED
    assert "bay seated skewed -17.0 deg" in p.manager._error or "no LiDAR rear gap at its start" in p.manager._error or "past the lane edge" in p.manager._error, p.manager._error
    assert -0.02 <= -p.world.pose[0] - 0.05 <= p.manager._cfg.bay_line_x_m and abs(p.world.pose[1]) < 0.02



def test_a_back_off_whose_lidar_gap_does_not_grow_with_the_wheels_stops():
    p = a_bay(charges=False)                       # no charge: SETTLING times out into a retry and a forward back-off
    state = {}

    def gap_of(p):
        if p.manager.phase is DockPhase.BACKOFF:
            state.setdefault("frozen", max(0.0, -p.world.pose[0] + STOP_FACE_X) + 0.01)
            return state["frozen"]                  # the body is held: the wheels turn, the LiDAR gap stays
        return max(0.0, -p.world.pose[0] + STOP_FACE_X) + 0.01
    p.manager.dock()
    run(p, gap_of=gap_of, seat_gap=None)
    assert p.manager.state is DockState.DOCK_FAILED and "not following the wheels" in p.manager._error, p.manager._error


def test_a_back_off_that_moves_the_body_is_not_stopped_by_the_gap_check():
    p = a_bay(charges=False)
    p.manager.dock()
    run(p, seat_gap=None)                           # the sim gap grows with the world: a healthy back-off
    assert "not following the wheels" not in (p.manager._error or "") and "skewed" not in (p.manager._error or "")


def test_a_back_off_whose_gap_grows_much_faster_than_the_wheels_stops_too():
    # round 16: the body turned (rg 0.097 -> 0.39 at -59 deg): rotation inflates the rear gap, the lower check alone passes it
    p = a_bay(charges=False)
    base = {}

    def gap_of(p):
        real = max(0.0, -p.world.pose[0] + STOP_FACE_X) + 0.01
        if p.manager.phase is DockPhase.BACKOFF:
            base.setdefault("x", real)
            return real + 3.5 * (real - base["x"])        # the gap grows 4.5 x the real travel: a turning body
        return real
    p.manager.dock()
    run(p, gap_of=gap_of, seat_gap=None)
    assert p.manager.state is DockState.DOCK_FAILED and "not following the wheels" in p.manager._error, p.manager._error


def test_the_back_off_inside_the_bay_row_is_slow():
    p = a_bay(charges=False)
    p.manager.dock()
    run(p, seat_gap=None)
    speeds = [c[0] for ph, c in p.world.commands if ph is DockPhase.BACKOFF and c[0] > 0.0]
    assert speeds and max(speeds) <= p.manager._cfg.bay_backoff_speed + 1e-9


def test_a_full_battery_with_a_lidar_confirmed_straight_seat_is_docked_without_charge_evidence():
    import math  # noqa: PLC0415
    from test_docking_bay_scan_pose import answer_kinds, good, with_reference  # noqa: PLC0415
    from test_docking_bay_zone import a_row, run_row  # noqa: PLC0415
    for percent, docked in ((100.0, True), (90.0, False)):
        p, row = a_row(start=(-0.15, 0.0, math.pi), others=(), charges=False)
        with_reference(p)
        p.battery.percent = percent
        p.manager.dock()
        run_row(p, row, until=answer_kinds(zone=good(x=0.15), entry=good(x=0.15), seat=good(x=0.01, heading=math.radians(2.0))))
        if docked:
            assert p.manager.state is DockState.DOCKED and p.manager._retries == 0
            assert "docked without charge evidence" in p.manager.status().last_event and "battery 100 %" in p.manager.status().last_event
        else:
            assert p.manager.state is DockState.DOCKED                        # not full: docked, charge NOT confirmed (it stays in the lane)
            assert "charge NOT confirmed" in p.manager.status().last_event
    p, row = a_row(start=(-0.15, 0.0, math.pi), others=(), charges=False)     # full battery but skewed: never docked
    with_reference(p)
    p.battery.percent = 100.0
    p.manager.dock()
    run_row(p, row, until=answer_kinds(zone=good(x=0.15), entry=good(x=0.15), seat=good(x=0.01, heading=math.radians(-17.0))))
    assert p.manager.state is DockState.DOCK_FAILED                                              # never docked while skewed; stopped in the lane
    assert "skewed" in p.manager._error or "no LiDAR rear gap at its start" in p.manager._error or "past the lane edge" in p.manager._error


def test_a_lagging_scan_does_not_stop_a_healthy_back_off():
    # panel B R2: the body scan can be 0.5 s old (2 cm at 0.04 m/s): the gap lags the wheels, the lower bound has slack
    p = a_bay(charges=False)
    seen = []

    def gap_of(p):
        real = max(0.0, -p.world.pose[0] + STOP_FACE_X) + 0.01
        seen.append(real)
        return seen[max(0, len(seen) - 1 - 6)]          # the scan is 6 calls (0.6 s) old
    p.manager.dock()
    run(p, gap_of=gap_of, seat_gap=None)
    assert "not following the wheels" not in (p.manager._error or ""), p.manager._error


def test_a_lidar_confirmed_straight_seat_without_charge_evidence_stays_docked_and_never_backs_out():
    # b8xy in-bay round: seated straight, no charge evidence at 88 %: stay (user rule: keep the parking lines), report it, never drive out
    import math  # noqa: PLC0415
    from test_docking_bay_scan_pose import answer_kinds, good, with_reference  # noqa: PLC0415
    from test_docking_bay_zone import a_row, run_row  # noqa: PLC0415
    p, row = a_row(start=(-0.15, 0.0, math.pi), others=(), charges=False)
    with_reference(p)
    p.battery.percent = 88.0
    p.manager.dock()
    run_row(p, row, until=answer_kinds(zone=good(x=0.15), entry=good(x=0.15), seat=good(x=-0.013, heading=math.radians(-1.3))))
    assert p.manager.state is DockState.DOCKED, p.manager._error
    assert "charge NOT confirmed" in p.manager.status().last_event and "88 %" in p.manager.status().last_event
    assert p.manager._retries == 0 and not [c for ph, c in p.world.commands if ph is DockPhase.BACKOFF and c[0] > 0.0]



def test_a_retry_from_aligning_inside_the_rails_with_a_skewed_heading_does_not_drive_out():
    # panel B R1: ALIGNING has no seat check; its retries (cap overrun, line lost, rear guard) back out straight
    p = a_bay()
    p.manager.dock()
    run(p, seat_gap=None, until=lambda p: p.manager.phase is DockPhase.ALIGNING and p.world.pose[0] > -0.12)
    bp = p.manager._bay_phases
    bp._est, bp._along_m = (0.0, 0.30), 0.10                  # 17 deg line heading, 10 cm from the stop face
    p.manager._retry("probe")
    assert p.manager.state is DockState.DOCK_FAILED and "inside the rails with a 17 deg line heading" in p.manager._error
    assert not [c for ph, c in p.world.commands if ph is DockPhase.BACKOFF]


def test_a_retry_from_aligning_inside_the_rails_with_a_straight_line_still_backs_out():
    p = a_bay()
    p.manager.dock()
    run(p, seat_gap=None, until=lambda p: p.manager.phase is DockPhase.ALIGNING and p.world.pose[0] > -0.12)
    bp = p.manager._bay_phases
    bp._est, bp._along_m = (0.0, 0.02), 0.10
    p.manager._retry("probe")
    assert p.manager.state is DockState.DOCKING and p.manager.phase is DockPhase.BACKOFF


def test_the_in_the_rails_guard_also_covers_an_unmeasured_along_by_the_last_measured_one_minus_the_travel():
    # panel B R5: the deepest retry can come with the camera unable to measure the along
    p = a_bay()
    p.manager.dock()
    run(p, seat_gap=None, until=lambda p: p.manager.phase is DockPhase.ALIGNING and p.world.pose[0] > -0.12)
    bp = p.manager._bay_phases
    bp._est, bp._along_m = (0.0, 0.30), None                      # skewed, along unmeasured
    p.world.odo = 0.0
    bp._along_last = (0.14, 0.0)
    p.world.odo = 0.06                                            # 6 cm reversed since: 8 cm from the stop face
    p.manager._retry("probe")
    assert p.manager.state is DockState.DOCK_FAILED and "inside the rails" in p.manager._error


def test_an_unmeasured_along_far_from_the_stop_face_still_backs_out():
    p = a_bay()
    p.manager.dock()
    run(p, seat_gap=None, until=lambda p: p.manager.phase is DockPhase.ALIGNING and p.world.pose[0] > -0.12)
    bp = p.manager._bay_phases
    bp._est, bp._along_m, bp._along_last = (0.0, 0.30), None, (0.40, 0.0)
    p.world.odo = 0.06                                            # 0.34 m out: not in the rails
    p.manager._retry("probe")
    assert p.manager.state is DockState.DOCKING and p.manager.phase is DockPhase.BACKOFF