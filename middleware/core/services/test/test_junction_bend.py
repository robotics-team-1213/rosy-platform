"""D-507 addendum (2026-10-08): the map-based bend pass on odometry in the real line-follow
manager (no ROS, no physical motion). Fleet's 'bend' instruction only; nothing else changes."""
import math

import pytest

from core_features.line_follow.recovery.junction.gate import JunctionRefused
from test_junction_turn_site_basis import SITE, site_rig, site_step
from test_line_junction import BODY, Rig

BEND = dict(map_id='lab-a', bend_in_m=.3, bend_tol_m=.05, bend_radius_m=.1)


def send(rig, turn=60., **fields):
    return rig.m.set_junction('bend', 'B1', 10., None, turn, None, expect={**BEND, **fields})


def until(rig, state, limit=400, **kwargs):
    """Move the rig (site basis) until the junction state is `state`."""
    for _ in range(limit):
        decision, status = site_step(rig, move=True, **kwargs)
        if status.junction.state == state:
            return decision, status
    raise AssertionError(f'never {state}: {status.junction}')


def armed_rig(**fields):
    rig = site_rig(**SITE)
    site_step(rig)
    assert send(rig, **fields) == (True, 1, 'armed')
    return rig


def test_without_a_bend_instruction_nothing_changes():
    """Default off: an armed bend outside its lead window drives exactly like no instruction."""
    plain, armed = site_rig(**SITE), armed_rig(bend_in_m=1.5)
    site_step(plain)
    for _ in range(20):
        (d1, s1), (d2, s2) = site_step(plain, move=True), site_step(armed, move=True)
        assert (d1.linear, d1.angular, s1.state, s1.reason) == (d2.linear, d2.angular, s2.state, s2.reason)
    assert s2.junction.state == 'armed' and plain.m.status().junction.state == 'idle'
    assert armed.m._bridge_hint is None  # the D-476 bridge runs as without an instruction


def test_bend_follows_the_camera_then_drives_the_arc_and_reacquires():
    rig = armed_rig()
    decision, status = until(rig, 'bending')
    assert rig.x == pytest.approx(.25, abs=.01)           # bend_in - tol: the earliest arc start
    assert status.state == 'RECOVERING' and status.reason == 'junction_bending'
    assert decision.linear > 0 and decision.angular >= 0
    until(rig, 'reacquiring')                              # on the path at the arc's end point
    assert (rig.x, rig.y) == pytest.approx((.30+.1*math.sin(math.pi/3), .05), abs=.005)
    assert 30. < math.degrees(rig.yaw) < 60.               # turned in early, still turning onto the exit
    decision, status = until(rig, 'idle')
    assert status.junction.seq == 1 and decision.linear > 0  # lane following again
    with pytest.raises(JunctionRefused):
        send(rig)                                          # R1: the same bend does not run twice


def test_camera_loss_inside_the_lead_window_starts_the_pass_from_the_last_straight_tick():
    rig = armed_rig()
    while rig.x < .1:
        site_step(rig, move=True)
    decision, status = site_step(rig, move=True, seen=False)  # keeper HOLD 0.2 m before the arc
    assert status.junction.state == 'bending' and decision.linear > 0


def test_obstacle_hold_in_the_lead_window_waits_then_the_pass_starts():
    """A D-422 (or IR, limit) HOLD is not the camera losing the lane: CORE waits armed."""
    rig = armed_rig()
    while rig.x < .1:
        site_step(rig, move=True)
    for _ in range(5):
        decision, status = site_step(rig, move=True, points=[(.07, 0.)])
        assert decision.linear == 0. and status.reason == 'obstacle_ahead'
        assert status.junction.state == 'armed'
    decision, status = until(rig, 'bending')
    assert rig.x == pytest.approx(.25, abs=.01)


def test_loss_before_the_lead_window_is_ordinary_loss():
    rig = armed_rig(bend_in_m=1.)
    decision, status = site_step(rig, move=True, seen=False)
    assert decision.linear == 0. and status.reason == 'camera_line_not_visible'
    assert status.junction.state == 'armed'


def test_no_straight_tick_since_receipt_aborts_without_moving():
    rig = site_rig(**SITE)
    site_step(rig)
    send(rig, bend_in_m=.2)
    decision, status = site_step(rig, seen=False)             # in the lead window, no anchor yet:
    assert decision.linear == 0. and status.junction.state == 'armed'  # the ordinary loss HOLD
    assert status.reason == 'camera_line_not_visible'
    rig.m.set_junction('bend', 'B2', 10., None, 60., None, expect={**BEND, 'bend_in_m': .04})  # at the arc
    decision, status = site_step(rig, seen=False)
    assert (decision.linear, decision.angular) == (0., 0.)
    assert (status.state, status.junction.state, status.junction.reason) == ('HOLD', 'aborted', 'no_anchor')


def test_sighting_before_the_lead_window_holds_and_stays_armed():
    rig = armed_rig(bend_in_m=1.)
    decision, status = site_step(rig, junction=True)
    assert decision.linear == 0. and status.junction.state == 'unexpected'
    assert rig.m._junction['state'] == 'armed'


@pytest.mark.parametrize('lost', [dict(ir='stale'), dict(points=None)])
def test_lost_basis_mid_arc_aborts_and_holds(lost):
    rig = armed_rig()
    until(rig, 'bending')
    for _ in range(3):
        site_step(rig, move=True)
    x = rig.x
    for _ in range(20):                                    # the IR verdict or the scan goes stale
        decision, status = site_step(rig, move=True, **lost)
        if status.junction.state != 'bending':
            break
    assert status.junction.reason == 'bend_basis_lost' and rig.x - x < .03
    assert (decision.linear, decision.angular) == (0., 0.)
    assert (status.state, status.junction.state) == ('HOLD', 'aborted')


def test_floor_declared_for_another_map_never_starts_the_arc():
    rig = armed_rig(map_id='lab-b')
    decision, status = until(rig, 'aborted')
    assert status.junction.reason == 'motion_unconfirmed' and rig.y == 0.
    assert (decision.linear, decision.angular) == (0., 0.)
    assert (status.state, status.junction.state) == ('HOLD', 'aborted')


def test_ir_line_under_the_robot_during_the_arc_stops_it():
    rig = armed_rig()
    until(rig, 'bending')
    decision, status = site_step(rig, move=True, ir='centre')
    assert (decision.linear, decision.angular) == (0., 0.) and status.junction.state == 'aborted'


def test_d422_body_sweep_holds_the_arc_and_a_lasting_block_times_out():
    """D-422 on every tick: a blocked sweep of the pass's own twist is a zero command (HOLD),
    the pass resumes when the sweep clears, and a block that lasts ends it (its time bound, or
    the D-407 stuck episode the lasting obstacle HOLD opens)."""
    rig = armed_rig()
    until(rig, 'bending')
    site_step(rig, move=True)
    x = rig.x
    for _ in range(3):
        decision, status = site_step(rig, move=True, points=[(.11, .02)])  # on the arc, in the stop gap
        assert (decision.linear, decision.angular) == (0., 0.)
        assert (status.state, status.reason, status.junction.state) == ('HOLD', 'junction_bend_blocked',
                                                                         'bending')
    assert rig.x == pytest.approx(x, abs=.003)
    decision, status = site_step(rig, move=True)                            # cleared: on along the arc
    assert decision.linear > 0 and status.reason == 'junction_bending'
    for _ in range(200):
        decision, status = site_step(rig, move=True, points=[(.11, .02)])
        if status.junction.state != 'bending':
            break
    assert status.junction.state == 'aborted' and status.junction.reason in ('timeout', 'stuck')
    assert (decision.linear, decision.angular) == (0., 0.)  # D-407 stuck may open first


def test_arc_distance_bound():
    rig = armed_rig()
    until(rig, 'bending')
    for k in range(100):                                  # odom jitters: travel without progress
        decision, status = site_step(rig, move=True, dx=.012 if k % 2 else -.012)
        if status.junction.state != 'bending':
            break
    assert (status.junction.state, status.junction.reason) == ('aborted', 'distance')
    assert decision.linear == 0.


def test_arc_time_bound():
    rig = armed_rig()
    until(rig, 'bending')
    for _ in range(400):                                  # commanded but not moving
        decision, status = site_step(rig)
        if status.junction.state != 'bending':
            break
    assert (status.junction.state, status.junction.reason) == ('aborted', 'timeout')
    assert decision.linear == 0.


def test_lane_not_found_after_the_arc_is_unresolved_and_holds():
    rig = armed_rig()
    until(rig, 'reacquiring')
    x, y = rig.x, rig.y
    decision, status = until(rig, 'unresolved', seen=False)
    assert math.hypot(rig.x-x, rig.y-y) == pytest.approx(.2, abs=.02)  # the bounded search
    assert math.degrees(rig.yaw) == pytest.approx(60., abs=3.)          # along the exit line
    assert (decision.linear, decision.angular) == (0., 0.) and status.reason == 'junction_unresolved'


def test_next_junction_seen_after_the_arc_ends_the_pass():
    rig = armed_rig()
    until(rig, 'reacquiring')
    decision, status = site_step(rig, move=True, seen=False, junction=True)
    assert status.junction.state == 'idle' and status.junction.seq == 1


def test_resend_while_armed_keeps_the_measured_travel():
    rig = armed_rig()
    for _ in range(10):
        site_step(rig, move=True)
    travel = rig.m._junction['travel']
    assert travel > .02 and send(rig, bend_in_m=.5) == (True, 1, 'armed')
    assert rig.m._junction['travel'] == travel and rig.m._junction['bend_in'] == .3


@pytest.mark.parametrize('turn, fields', [
    (None, {}), (95., {}), (60., {'bend_in_m': None}), (60., {'bend_tol_m': .31}),
    (60., {'bend_radius_m': .6}), (60., {'map_id': None}), (60., {'expect_in_m': .5, 'expect_tol_m': .1}),
    (60., {'pivot_past_line_m': .1})])
def test_bend_needs_its_fields(turn, fields):
    rig = site_rig(**SITE)
    site_step(rig)
    expect = {k: v for k, v in {**BEND, **fields}.items() if v is not None}
    with pytest.raises(ValueError):
        rig.m.set_junction('bend', 'B1', 10., None, turn, None, expect=expect)


def test_bend_fields_belong_to_bend():
    rig = site_rig(**SITE)
    site_step(rig)
    with pytest.raises(ValueError):
        rig.m.set_junction('left', 'J1', 10., None, 60., None, expect=BEND)


def test_backward_travel_while_armed_does_not_bring_the_arc_closer():
    """Review H1: travel while armed is signed along the heading (a D-468 retrace counts back)."""
    rig = armed_rig()
    for _ in range(10):
        site_step(rig, move=True)
    travel = rig.m._junction['travel']
    for _ in range(5):
        site_step(rig, dx=-.004)                           # driven backwards 2 cm
    assert rig.m._junction['travel'] == pytest.approx(travel-.02, abs=.003)
    until(rig, 'bending')
    assert rig.x == pytest.approx(.25, abs=.01)           # the arc start did not move


def test_odom_restart_while_armed_aborts():
    rig = armed_rig()
    site_step(rig, move=True)
    rig.m._return_evidence.epoch += 1                    # the distance is no longer measurable
    decision, status = site_step(rig, move=True)
    assert (status.junction.state, status.junction.reason) == ('aborted', 'odom')
    assert decision.linear == 0.


def test_off_the_path_sideways_aborts():
    """Review M2: a cross-track error past the IR fence's 0.06 m ends the pass (enforce has no IR)."""
    rig = armed_rig()
    until(rig, 'bending')
    for _ in range(30):
        rig.y -= .01                                       # odom says the body slid sideways
        decision, status = site_step(rig, move=True)
        if status.junction.state != 'bending':
            break
    assert (status.junction.state, status.junction.reason) == ('aborted', 'off_path')
    assert decision.linear == 0.


def test_enforce_basis_refusing_the_twist_aborts():
    rig = Rig(**BODY, obstacle_mode='path')               # D-400 enforce proof bound and configured
    rig.step(points=[(1.5, 1.5)])
    rig.m.set_junction('bend', 'B1', 10., None, 60., None, expect=BEND)
    for _ in range(200):
        decision, status = rig.step(move=True, points=[(1.5, 1.5)])
        if status.junction.state == 'bending':
            break
    rig.m.bind_return_motion(lambda now, v, w: False, proof_configured=lambda: True)  # proof refuses
    decision, status = rig.step(move=True, points=[(1.5, 1.5)])
    assert status.junction.state == 'aborted' and decision.linear == 0.


def test_lane_bend_capability_needs_a_basis():
    """Review M1: announced only when a bend could be admitted at all (enforce or the site parts)."""
    assert site_rig().m.supports_lane_bend is False        # no floor declaration, proof not live
    assert site_rig(**SITE).m.supports_lane_bend is True
    assert Rig().m.supports_lane_bend is True             # enforce proof configured
