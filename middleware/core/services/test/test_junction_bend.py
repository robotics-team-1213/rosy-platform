"""D-507 addendum (2026-10-08): the map-based bend pass on odometry in the real line-follow
manager (no ROS, no physical motion). Fleet's 'bend' instruction only; nothing else changes."""
import math

import pytest

from core_features.line_follow.recovery.junction import JunctionRefused
from test_junction_turn_site_basis import SITE, site_rig, site_step

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
    assert armed.m._bridge_hint == 'left'  # no straight D-476 bridge into the bend


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


def test_loss_before_the_lead_window_is_ordinary_loss():
    rig = armed_rig(bend_in_m=1.)
    decision, status = site_step(rig, move=True, seen=False)
    assert decision.linear == 0. and status.reason == 'camera_line_not_visible'
    assert status.junction.state == 'armed'


def test_no_straight_tick_since_receipt_aborts_without_moving():
    rig = site_rig(**SITE)
    site_step(rig)
    send(rig, bend_in_m=.1)
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


def test_d422_body_sweep_stops_the_arc():
    rig = armed_rig()
    until(rig, 'bending')
    site_step(rig, move=True)
    decision, status = site_step(rig, move=True, points=[(.13, .02)])  # on the arc, inside the stop gap
    assert (decision.linear, decision.angular) == (0., 0.)
    assert (status.junction.state, status.junction.reason) == ('aborted', 'near_stop')


def test_arc_distance_bound():
    rig = armed_rig()
    until(rig, 'bending')
    for _ in range(100):                                  # odom travels, the path does not advance
        decision, status = site_step(rig, move=True, dx=-.008)
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
