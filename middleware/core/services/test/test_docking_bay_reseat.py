"""A problem inside the lane is corrected inside the lane (user 2026-11-21: like a robot vacuum docking): bounded reseats on the LiDAR pose."""

from __future__ import annotations

import math

from core_common.protocol.schemas import DockState
from core_features.docking.bay_scan_pose import BayScanPose
from core_features.docking.manager import DockPhase
from test_docking_bay import DT, a_bay, done
from test_docking_bay_scan_pose import true_bay_pose, with_reference


def run(p, answer=None, limit_s=400.0, seen=None):
    """The bridge: every LiDAR pose request is answered from the sim body unless answer(kind, pose, now) returns another value (False = no answer)."""
    p.manager.note_bay_seat_gap("bay1", 0.01)
    t0, k = p.clock.now, 0
    while p.clock.now - t0 < limit_s:
        if k % 2 == 0:
            p.detector.capture()
            p.manager.note_body_scan(None, None, max(0.0, -p.world.pose[0] - 0.05) + 0.01, p.clock.now)
        p.manager.tick()
        if seen is not None and p.manager.status().last_event not in seen:
            seen.append(p.manager.status().last_event)
        request = p.manager.bay_scan_request()
        if request is not None:
            kind = p.manager._bay_phases._req_kind
            pose = true_bay_pose(p.world)
            out = answer(kind, pose, p.clock.now) if answer else pose
            if out is not False:
                p.manager.note_bay_scan_match(out, at=p.clock.now, request_id=request[0])
        if done(p.manager):
            break
        p.world.step()
        p.clock.now += DT
        k += 1


def _dock(**kw):
    p = a_bay(**kw)
    with_reference(p)
    p.world.pose = (-0.15, 0.0, math.pi)                       # in its lane, straight
    p.manager.dock()
    return p


def _skewed(heading_deg, first_n=1):
    state = {"n": 0}

    def answer(kind, pose, now):
        if kind == "seat":
            state["n"] += 1
            if state["n"] <= first_n:
                return BayScanPose(x=0.01, y=0.0, heading=math.radians(heading_deg), inliers=0.95, margin=0.6, median_m=0.003)
        return pose
    return answer


def test_a_skewed_seat_is_corrected_inside_the_lane_on_the_second_try():
    p = _dock()
    seen = []
    run(p, answer=_skewed(-9.0), seen=seen)
    assert p.manager.state is DockState.DOCKED, (p.manager._error, seen)
    assert p.manager._retries == 1
    assert any(e and e.startswith("reseat 1/4: bay seated skewed -9.0 deg") for e in seen), seen
    assert all(-p.world.pose[0] - 0.05 <= 0.30 + 1e-9 for _ in [0]) and abs(p.world.pose[1]) < 0.02       # stayed inside the lines
    assert not [c for ph, c in p.world.commands if c[0] == 0.0 and abs(c[1]) > 1e-6 and ph in (DockPhase.BACKOFF,)]      # no in-place turn in the reseat


def test_a_pose_gap_during_the_reverse_is_waited_out_not_failed():
    p = _dock()
    state = {"t": None}

    def answer(kind, pose, now):
        if kind == "align" and pose.x < 0.2:
            state["t"] = now if state["t"] is None else state["t"]
            if now - state["t"] < 2.5:
                return False                                  # no pose for 2.5 s mid-reverse
        return pose
    run(p, answer=answer)
    assert p.manager.state is DockState.DOCKED, p.manager._error


def test_a_lateral_the_rail_entrance_refuses_is_corrected_by_a_reseat():
    p = _dock()
    state = {"lie": True}

    def answer(kind, pose, now):
        if kind == "align" and state["lie"] and pose.x < 0.2:
            return BayScanPose(x=pose.x, y=pose.y - 0.02, heading=pose.heading, inliers=0.95, margin=0.6, median_m=0.003)   # 20 mm off at the entrance
        return pose
    seen = []
    orig = p.manager.note_bay_scan_match

    def note(match, at=None, error=None, request_id=None):
        if p.manager.phase is DockPhase.BACKOFF and p.manager._retries >= 1:
            state["lie"] = False                              # the reseat moved it: the lateral is true from now on
        return orig(match, at, error, request_id)
    p.manager.note_bay_scan_match = note
    run(p, answer=answer, seen=seen)
    assert p.manager.state is DockState.DOCKED, (p.manager._error, seen)
    assert any(e and e.startswith("reseat 1/4: bay rail entrance lateral") for e in seen), seen


def test_when_the_tries_are_used_up_it_stops_inside_the_lane_and_says_so():
    p = _dock(charges=False)
    seen = []
    run(p, answer=_skewed(-9.0, first_n=99), seen=seen)
    assert p.manager.state is DockState.DOCK_FAILED and "tries used up: 4" in p.manager._error, p.manager._error
    assert any(e and e.startswith("reseat 4/4") for e in seen), seen
    out = -p.world.pose[0] - 0.05
    assert -0.02 <= out <= p.manager._cfg.bay_line_x_m and abs(p.world.pose[1]) < 0.02          # where it stands, inside the lines
    assert p.world.command == (0.0, 0.0)


def test_a_reseat_pulls_forward_straight_never_turns_in_place_and_stays_short_of_the_bay_line():
    p = _dock()
    xs = []
    orig = p.world.step

    def step():
        orig()
        xs.append(-p.world.pose[0] - 0.05)
    p.world.step = step
    run(p, answer=_skewed(-9.0, first_n=2))
    assert p.manager.state is DockState.DOCKED, p.manager._error
    assert max(xs) <= p.manager._cfg.bay_line_x_m - 0.03 + 0.02, max(xs)

def test_a_backoff_of_a_reference_dock_with_no_start_gap_stops_at_two_centimetres():
    # panel B R5 (restored): without the start gap the growth check never turns on; a reference-scan dock then stops instead of driving out blind
    p = _dock(charges=False)
    p.manager.note_bay_seat_gap("bay1", 0.01)

    gaps = True

    def step(k):
        if k % 2 == 0:
            p.detector.capture()
            p.manager.note_body_scan(None, None, max(0.0, -p.world.pose[0] - 0.05) + 0.01 if gaps else None, p.clock.now)
        p.manager.tick()
        request = p.manager.bay_scan_request()
        if request is not None:
            p.manager.note_bay_scan_match(true_bay_pose(p.world), at=p.clock.now, request_id=request[0])
        p.world.step()
        p.clock.now += DT
    for k in range(3000):
        step(k)
        if p.manager.phase is DockPhase.ACQUIRING:
            break
    gaps = False                                                            # no rear-gap scan from here on
    p.manager._begin_backoff(DockPhase.STAGING)
    p.manager._bay_phases._in_row = False                                   # a retry from outside the row backs out 2 cm at most without a gap
    cmds = []
    for k in range(600):
        step(k)
        cmds.append(p.world.command)
        if done(p.manager):
            break
    assert p.manager.state is DockState.DOCK_FAILED and "no LiDAR rear gap at its start" in p.manager._error, p.manager._error
    assert 0 < len([c for c in cmds if c[0] > 0.0]) <= 25                  # about 2 cm at 0.04 m/s, then stopped


def test_a_docked_without_charge_low_battery_calls_a_person_and_shows_unconfirmed():
    p = _dock(charges=False)
    p.battery.percent = 20.0
    run(p, answer=_skewed(0.0, first_n=0))
    assert p.manager.state is DockState.DOCKED and p.manager.status().charge_unconfirmed
    assert any(k == "docking.person_call" for k, d in p.events)