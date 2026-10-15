"""D-507 addendum (2026-10-08): the map-based bend pass on odometry in the real line-follow
manager (no ROS, no physical motion). Fleet's 'bend' instruction only; nothing else changes."""
import dataclasses
import math

import pytest

from core_features.line_follow import authority
from core_features.line_follow.recovery.junction import bend
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


def _seconds_until_timeout(look, leased=False):
    """A bend commanded but not moving: seconds until 'timeout', with the crosswalk state `look`
    (leased: under a trip lease with no authority, NONE, D-760 2)."""
    rig = armed_rig()
    until(rig, 'bending')
    rig.m.authority_leased = lambda: leased
    rig.m._xwalk.status = lambda now: {'state': look} if look else None
    start = rig.now
    for _ in range(3000):
        decision, status = site_step(rig)
        if status.junction.state != 'bending':
            assert (status.junction.state, status.junction.reason) == ('aborted', 'timeout')
            assert (decision.linear, decision.angular, status.state, status.reason) == (0., 0., 'HOLD', 'junction_aborted')
            return rig.now-start
    raise AssertionError('never timed out')


def test_a_30_s_holding_authority_stands_the_bend_clock_and_the_bend_goes_on():
    """Gazebo m33c: rosy_02 stood mid B_W2 bend behind a parked robot and the bend ended 'timeout' after
    the 15 s credit. D-760 개정 4: a HOLDING authority (Fleet alive, saying wait) stands the phase clock
    for as long as it lasts; once FREE the bend goes on and reacquires."""
    rig = armed_rig()
    until(rig, 'bending')
    rig.m._authority_on = lambda: True
    rig.m._authority_state = lambda now: ('HOLDING', 0., 'authority_end')
    for _ in range(600):                                                         # 30 s
        decision, status = site_step(rig)
        assert status.junction.state == 'bending'
        assert (decision.linear, decision.angular) == (0., 0.)
    assert status.regulation_wait == 'authority'
    del rig.m._authority_on, rig.m._authority_state                              # FREE
    decision, status = site_step(rig, move=True)
    assert status.junction.state == 'bending' and decision.linear > 0
    until(rig, 'reacquiring')


def test_a_missing_authority_keeps_the_cap_then_the_bend_aborts():
    """No authority under a trip lease (NONE; EXPIRED alike): the phase clock stands 15 s at most,
    then 'timeout' and HOLD junction_aborted, so a stale maneuver never resumes later."""
    assert _seconds_until_timeout(None, leased=True) == pytest.approx(_seconds_until_timeout(None)+15., abs=.3)


def test_time_under_a_crosswalk_look_is_not_the_bends():
    """Gazebo lap m4: a bend pass that took over before a crosswalk stood through the 6 s look and
    ended 'timeout'. Looking or waiting stops the phase clock, at most crosswalk_report_s +
    crosswalk_clear_s (15 s) in all; a crossing takes only its slower share (review)."""
    plain = _seconds_until_timeout(None)
    assert _seconds_until_timeout('looking') == pytest.approx(plain+15., abs=.3)
    assert _seconds_until_timeout('waiting') == pytest.approx(plain+15., abs=.3)
    crossing = _seconds_until_timeout('crossing')         # 0.04 against the bend's speed
    assert plain <= crossing < plain+15.
    assert _seconds_until_timeout('armed') == pytest.approx(plain, abs=.01)


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


def sight(rig, ahead, reason='junction_transverse'):
    """The keeper's junction HOLD with its measured cross line, in the next rig tick's frame."""
    rig.m.observe_junction(reason, round(rig.now+.05, 6), ahead_m=ahead, ahead_v=1)


def bend_sighting_line_ahead(rig, ahead=.4, **kind):
    """Drive into the arc, sight the next junction's line once mid-arc (lap SIM A: 0.39-0.45 m
    ahead, inside the pass), then let the keeper stop reporting it (it reads a corner)."""
    until(rig, 'bending')
    entry = rig.m._junction['anchor'][2]
    for _ in range(400):                                  # turned: the line is along the exit
        if abs(math.remainder(rig.yaw-entry, math.tau)) > math.radians(35.):
            break
        site_step(rig, move=True)
    sight(rig, ahead, **kind)
    site_step(rig, move=True)
    trail = rig.m._return_evidence.trail
    return trail.odometer + ahead  # the line, on the odometer


def test_a_line_sighted_during_the_pass_is_handed_to_the_junction_and_waits():
    """Lap SIM A (11/20): the sighting must outlive the arc end; the pass ends in 'waiting' (HOLD)."""
    rig = armed_rig()
    bend_sighting_line_ahead(rig)
    for _ in range(200):
        decision, status = site_step(rig, move=True)
        if status.junction.state not in ('bending', 'reacquiring'):
            break
    assert (status.junction.state, status.junction.seq) == ('waiting', 1)
    assert (decision.linear, decision.angular) == (0., 0.) and status.reason == 'junction_waiting'


def _sight_past_the_vertex(rig, past):
    """On the lead-in straight, sight a line `past` m beyond the bend's vertex on the entry axis."""
    until(rig, 'bending')
    j = rig.m._junction
    x, y, _, travel = j['anchor']
    vertex = j['bend_in']-travel+j['radius']*math.tan(math.radians(abs(j['turn_deg']))/2)
    sight(rig, vertex-math.hypot(rig.x-x, rig.y-y)+past)


def test_a_line_just_past_the_bends_vertex_is_the_bends_own_outer_line():
    """Gazebo lap run53: the keeper read the corner's outer line as a cross line 0.097 m past the
    vertex before the arc; the map's lane turns at the vertex, so the pass ends in 'idle'."""
    for turn in (60., 90.):                               # 90: the measured corner
        rig = armed_rig(turn=turn)
        _sight_past_the_vertex(rig, .1)
        decision, status = until(rig, 'idle')
        assert decision.linear > 0 and rig.m._junction_held is False, turn


def test_a_line_far_along_the_exit_or_on_a_shallow_bend_is_still_handed_over():
    """Review: beyond the outer line's reach along the exit (60 deg: 0.158 m), and on any bend
    under 60 deg, the sighting may be the next junction's, so the pass ends in 'waiting'."""
    for fields, past in (({}, .4), ({}, .34), ({'turn': 40.}, .1)):  # 0.34 cos 60 = 0.17: just beyond
        rig = armed_rig(**fields)
        _sight_past_the_vertex(rig, past)
        until(rig, 'waiting')


def _line_out(rig, ahead, turn=60.):
    """Where the line `ahead` of the rig lies along the exit line from the bend's vertex."""
    exit_yaw = math.radians(turn)
    vertex = BEND['bend_in_m']+BEND['bend_radius_m']*math.tan(exit_yaw/2)
    px, py = rig.x+ahead*math.cos(rig.yaw)-vertex, rig.y+ahead*math.sin(rig.yaw)
    return px*math.cos(exit_yaw)+py*math.sin(exit_yaw)


def test_the_map_drops_a_mid_arc_line_where_it_has_no_junction():
    """D-754, Gazebo lap run55: W3 (90 deg) read its own line mid-arc 0.17 m ahead, beyond the
    note 9 reach, so it was handed over; the map's next junction is over 1 m on, so it is not."""
    rig = armed_rig(turn=90.)
    bend_sighting_line_ahead(rig, ahead=.17)
    assert _line_out(rig, .17, 90.) > .10                 # beyond the own line's reach at 90 deg
    until(rig, 'waiting')                                 # without the field: as before
    for fields, ahead in ((dict(turn=90.), .17), ({}, .4)):
        rig = armed_rig(next_line_in_m=1., **fields)
        bend_sighting_line_ahead(rig, ahead=ahead)
        decision, status = until(rig, 'idle')
        assert decision.linear > 0 and rig.m._junction_held is False, fields
        assert rig.m._junction_anchor is None, fields    # the sighting is cleared


def test_the_map_keeps_a_mid_arc_line_where_its_next_junction_is():
    """D-754: W1's next junction shortly after it; within the tolerance (0.05 placement +
    0.05 x 0.4 range + 0.10 half lane = 0.17 m) either side, and not beyond it."""
    probe = armed_rig()
    bend_sighting_line_ahead(probe)
    out = _line_out(probe, .4)
    assert .25 < out < .5
    for off, state in ((0., 'waiting'), (-.12, 'waiting'), (.12, 'waiting'), (.22, 'idle'), (-.22, 'idle')):
        rig = armed_rig(next_line_in_m=out+off)
        bend_sighting_line_ahead(rig)
        until(rig, state)


def test_a_fork_sighting_measures_the_place_short_of_the_maps_line():
    """Review: junction_fork measures the place point, up to 0.30 m before the painted line; a
    transverse sighting that far short is not that line. A refresh carries the map's new distance."""
    probe = armed_rig()
    bend_sighting_line_ahead(probe)
    out = _line_out(probe, .4)
    for kind, state in ((dict(reason='junction_fork'), 'waiting'), ({}, 'idle')):
        rig = armed_rig(next_line_in_m=out+.25)
        bend_sighting_line_ahead(rig, **kind)
        until(rig, state)
    rig = armed_rig(next_line_in_m=1.)
    assert send(rig, next_line_in_m=.5) == (True, 1, 'armed') and rig.m._junction['next_line'] == .5


def test_the_map_judges_a_line_read_on_the_entry_heading_too():
    """D-754: a line read before the arc goes by the map's distance as well: dropped when the next
    junction is far (a shallow bend too), handed over where the map has a line, inside note 9's reach."""
    for fields, past, state in ((dict(next_line_in_m=1.), .1, 'idle'),
                                # review: note 9's shape still drops it under a wide placement tolerance
                                (dict(next_line_in_m=.35, bend_tol_m=.2), .1, 'idle'),
                                (dict(next_line_in_m=1., turn=40.), .1, 'idle'),
                                ({}, .2, 'idle'),         # 0.2 cos 60 = 0.10 along the exit: note 9
                                (dict(next_line_in_m=.1), .2, 'waiting')):
        rig = armed_rig(**fields)
        _sight_past_the_vertex(rig, past)
        until(rig, state)


def test_the_next_turn_takes_the_handed_over_sighting_without_a_new_one():
    """No fresh sighting after the pass (the keeper reads the line as a corner): the instruction
    still finds its junction in the window and stops to turn instead of following the keeper."""
    rig = armed_rig()
    line = bend_sighting_line_ahead(rig)
    until(rig, 'waiting')
    pivot = .1
    expect_in = line-rig.m._return_evidence.trail.odometer+pivot
    assert rig.m.set_junction('right', 'J1', 10., None, -90., None, expect=dict(
        map_id='lab-a', expect_in_m=expect_in, expect_tol_m=.1, pivot_past_line_m=pivot))[2] == 'armed'
    decision, status = site_step(rig, move=True)
    assert status.junction.state in ('turning', 'approaching') and decision.angular == 0.
    assert status.reason in ('junction_stopping', 'junction_approaching')


def test_a_handed_over_line_outside_the_window_holds_unexpected():
    rig = armed_rig()
    line = bend_sighting_line_ahead(rig)
    until(rig, 'waiting')
    rig.m.set_junction('right', 'J1', 10., None, -90., None, expect=dict(
        map_id='lab-a', expect_in_m=line-rig.m._return_evidence.trail.odometer+.5, expect_tol_m=.1,
        pivot_past_line_m=.1))
    decision, status = site_step(rig, move=True)
    assert (decision.linear, status.junction.state) == (0., 'unexpected')


def test_a_straight_through_a_handed_over_line_ends_once_odom_passes_it():
    rig = armed_rig()
    line = bend_sighting_line_ahead(rig, ahead=.3)
    until(rig, 'waiting')
    rig.m.set_junction('straight', 'J1', 10., None, None, None, expect=dict(
        map_id='lab-a', expect_in_m=line-rig.m._return_evidence.trail.odometer, expect_tol_m=.1))
    decision, status = site_step(rig, move=True)
    assert status.junction.state == 'executing' and decision.linear > 0
    while rig.m._return_evidence.trail.odometer < line-.005:
        assert site_step(rig, move=True)[1].junction.state == 'executing'
    while rig.m._return_evidence.trail.odometer < line+.005:
        decision, status = site_step(rig, move=True)
    assert status.junction.state == 'idle' and decision.linear > 0


def test_a_sighting_run_begun_before_the_take_over_is_not_handed_over():
    """Review: the keeper's junction reason on the bend's own corner can start the pass and stay
    fresh into it; only a run of sightings that begins inside the pass is the next junction."""
    rig = armed_rig()
    while rig.x < .2:
        site_step(rig, move=True)
    for _ in range(8):                                    # one run: before the take-over and on
        sight(rig, .4)
        decision, status = site_step(rig, move=True)
    assert status.junction.state == 'bending'
    decision, status = until(rig, 'idle')
    assert decision.linear > 0


def test_the_handed_over_line_survives_a_stale_odom_tick_and_ends_on_a_new_epoch():
    rig = armed_rig()
    bend_sighting_line_ahead(rig)
    until(rig, 'waiting')
    rig.now += .3
    site_step(rig, pose=False)                            # a tick with odom 0.35 s old: not fresh
    assert rig.m._junction_held is True
    site_step(rig)                                        # odom back, same continuous run
    assert rig.m._junction_held is True
    rig.m._return_evidence.epoch += 1                    # odom restarted: the line is unplaced
    site_step(rig)
    assert rig.m._junction_held is False


def test_a_sighting_without_a_measured_line_is_not_handed_over():
    """No junction_ahead_m (old keeper): nothing places the line, so the pass ends as before."""
    rig = armed_rig()
    until(rig, 'bending')
    site_step(rig, move=True, junction=True)
    decision, status = until(rig, 'idle')
    assert decision.linear > 0


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
    (60., {'pivot_past_line_m': .1}), (60., {'next_line_in_m': -.01}), (60., {'next_line_in_m': 2.01}),
    (60., {'next_line_in_m': math.nan})])
def test_bend_needs_its_fields(turn, fields):
    rig = site_rig(**SITE)
    site_step(rig)
    expect = {k: v for k, v in {**BEND, **fields}.items() if v is not None}
    with pytest.raises(ValueError):
        rig.m.set_junction('bend', 'B1', 10., None, turn, None, expect=expect)


def test_bend_fields_belong_to_bend():
    rig = site_rig(**SITE)
    site_step(rig)
    for expect in (BEND, dict(map_id='lab-a', next_line_in_m=.5)):  # D-754: the next line too
        with pytest.raises(ValueError):
            rig.m.set_junction('left', 'J1', 10., None, 60., None, expect=expect)


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


def test_a_short_odom_gap_while_bending_holds_and_the_bend_goes_on():
    """Gazebo m27: a 0.6 s odom gap mid-bend aborted the bend ('odom') and ended the trip. Within the
    phase limit a missing pose holds the maneuver; a new odom run still aborts (below)."""
    rig = armed_rig()
    until(rig, 'bending')
    for _ in range(12):                                   # 0.6 s without a pose
        decision, status = site_step(rig, pose=False)
        assert status.junction.state == 'bending'
    assert status.reason == 'junction_pose_gap' and decision.linear == 0.
    until(rig, 'reacquiring')


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


def _bending_under_the_proof():
    rig = Rig(**BODY, obstacle_mode='path')               # D-400 enforce proof bound and configured
    rig.step(points=[(1.5, 1.5)])
    rig.m.set_junction('bend', 'B1', 10., None, 60., None, expect=BEND)
    for _ in range(200):
        decision, status = rig.step(move=True, points=[(1.5, 1.5)])
        if status.junction.state == 'bending':
            return rig
    raise AssertionError('never bending')


def test_enforce_basis_refusing_the_twist_holds_then_aborts():
    """Gazebo lap run56/58: one refused tick is not a lost basis. The pass stands still and is
    kept; a proof that stays refused past UNCONFIRMED_HOLD_S aborts it as before."""
    rig = _bending_under_the_proof()
    allowed = rig.m._return_motion
    rig.m.bind_return_motion(lambda now, v, w: False, proof_configured=lambda: True)  # proof refuses
    decision, status = rig.step(move=True, points=[(1.5, 1.5)])
    assert (status.junction.state, status.reason) == ('bending', 'junction_motion_unconfirmed')
    assert (decision.linear, decision.angular) == (0., 0.)
    rig.m.bind_return_motion(allowed, proof_configured=lambda: True)                  # one tick only
    decision, status = rig.step(move=True, points=[(1.5, 1.5)])
    assert status.junction.state == 'bending' and decision.linear > 0
    rig.m.bind_return_motion(lambda now, v, w: False, proof_configured=lambda: True)
    start = rig.now
    for _ in range(40):
        decision, status = rig.step(move=True, points=[(1.5, 1.5)])
        assert (decision.linear, decision.angular) == (0., 0.)
        if status.junction.state == 'aborted':
            break
    assert (status.junction.state, status.junction.reason) == ('aborted', 'motion_unconfirmed')
    assert .5 < rig.now-start <= .75


def test_a_refusal_whose_second_ask_passes_still_aborts_in_time_and_a_blocked_hold_does_not_count():
    """Review: the bend asks the proof twice a tick; refused then allowed is still a refused tick.
    A long D-422 blocked hold before the first refusal does not use up the hold."""
    rig = _bending_under_the_proof()
    allowed, asks = rig.m._return_motion, []
    rig.m.bind_return_motion(lambda now, v, w: asks.append(now) is not None and asks.count(now) > 1,
                             proof_configured=lambda: True)
    start = rig.now
    for _ in range(40):
        decision, status = rig.step(move=True, points=[(1.5, 1.5)])
        assert (decision.linear, decision.angular) == (0., 0.)
        if status.junction.state == 'aborted':
            break
    assert status.junction.reason == 'motion_unconfirmed' and .5 < rig.now-start <= .75
    rig = _bending_under_the_proof()
    rig.m._junction['phase_at'] -= 1.                      # as after a blocked hold over 0.5 s
    rig.m.bind_return_motion(lambda now, v, w: False, proof_configured=lambda: True)
    decision, status = rig.step(move=True, points=[(1.5, 1.5)])
    assert (status.junction.state, status.reason) == ('bending', 'junction_motion_unconfirmed')


def test_lane_bend_capability_needs_a_basis():
    """Review M1: announced only when a bend could be admitted at all (enforce or the site parts)."""
    assert site_rig().m.supports_lane_bend is False        # no floor declaration, proof not live
    assert site_rig(**SITE).m.supports_lane_bend is True
    assert Rig().m.supports_lane_bend is True             # enforce proof configured
    assert site_rig().m.supports_lane_bend_next_line is False  # D-754: with lane_bend
    assert site_rig(**SITE).m.supports_lane_bend_next_line is True


def test_a_pending_instruction_under_the_live_proof_asks_for_the_return_scan_view():
    """Gazebo lap 2026-10-13: under the D-400 proof CORE's probe also needs return_body_clear's
    scan view, fed only while wants_return_scan. Unfed, every bend twist was motion_unconfirmed.
    The site basis sweeps the D-422 scan points instead and does not ask for the view."""
    rig = Rig(**BODY)                                      # proof bound, liveness unknown = live
    rig.step()
    assert rig.m.wants_return_scan is False
    assert send(rig) == (True, 1, 'armed')
    assert rig.m.wants_return_scan is True
    assert armed_rig().m.wants_return_scan is False


# --- D-759: the lane's map heading for the anchor line -------------------------------------------

WALL = 1_790_000_000.            # CORE wall clock at rig time 0 (snapshot odom_pose.stamp is on it)
MAP_TURN = .4                    # the map frame: odom turned by this
OFF_DEG = 21.6                   # Gazebo 2026-10-14, W3: the body's yaw off the lane at the take-over


def _wall_rig(enabled=True, y=0.):
    """line_follow.bend_map_entry_enabled on (the default is off); the body starts `y` left of the lane."""
    rig = site_rig(**SITE, bend_map_entry_enabled=enabled)
    rig.m._wall, rig.y = (lambda: WALL + rig.now), y
    site_step(rig)
    return rig


def _entry(rig, lane_yaw=0., **over):
    """Fleet's map_entry for a lane running `lane_yaw` in the rig's odom frame, with the yaw pair
    of the rig's newest odom sample."""
    return dict(dict(yaw_rad=lane_yaw+MAP_TURN, pose_yaw_rad=rig.yaw+MAP_TURN,
                     odom_stamp_s=WALL+rig.now), **over)


def _steered_take_over(rig, off_deg=OFF_DEG):
    """The keeper steers the body `off_deg` to the right (away from the left bend) on the last
    centimetres before the earliest arc start while the camera still reads the lane straight."""
    while rig.x < .15:
        site_step(rig, move=True)
    for _ in range(5):                                    # under the odom trail's yaw-jump bound
        rig.yaw -= math.radians(off_deg)/5
        site_step(rig, move=True)
    return until(rig, 'bending')


def _pass_end(rig):
    """Drive the arc and the bounded search to their end: (how far left of the lane's exit line
    the body stands (the wall is on the right of a left bend), its yaw in deg). The lane is the one
    Fleet sent: along +x from the odom origin, arc start at 0.3 m, 60 deg left, radius 0.1 m."""
    until(rig, 'reacquiring')
    until(rig, 'unresolved', seen=False)
    exit_yaw, vertex = math.radians(60.), .3+.1*math.tan(math.radians(30.))
    return -(rig.x-vertex)*math.sin(exit_yaw)+rig.y*math.cos(exit_yaw), math.degrees(rig.yaw)


def test_the_measured_take_over_runs_the_anchor_line_on_the_lanes_map_heading():
    """Gazebo 2026-10-14 (W3): the body was 21.6 deg off the lane, pointing at the wall, when the
    pass took over. With Fleet's map_entry the lead-in, the arc and the exit follow the lane."""
    rig = _wall_rig()
    assert send(rig, map_entry=_entry(rig)) == (True, 1, 'armed')
    assert rig.m.status().junction.map_entry_used is False    # placed, not used before the take-over
    assert rig.m.status().junction.map_entry_reason is None
    _, status = _steered_take_over(rig)
    j = rig.m._junction
    assert math.degrees(rig.yaw) == pytest.approx(-OFF_DEG, abs=3.)  # the pursuit has had one tick
    assert j['anchor'][2] == pytest.approx(0., abs=1e-9)
    assert j['target'] == pytest.approx(math.radians(60.), abs=1e-9)
    assert (status.junction.map_entry_used, status.junction.map_entry_reason) == (True, None)
    (x0, y0), (x1, y1) = j['path'][0], j['path'][6]
    assert (x1-x0, y1-y0) == pytest.approx((.03, 0.), abs=1e-9)  # the lead-in runs along the lane
    offset, yaw = _pass_end(rig)
    assert abs(offset) < .02 and yaw == pytest.approx(60., abs=3.), (offset, yaw)


def test_without_a_map_entry_the_anchor_line_follows_the_bodys_yaw_as_before():
    rig = _wall_rig()
    assert send(rig) == (True, 1, 'armed')
    assert rig.m.status().junction.map_entry_reason == 'none_sent'
    _, status = _steered_take_over(rig)
    j = rig.m._junction
    assert j['anchor'][2] == pytest.approx(-math.radians(OFF_DEG), abs=1e-9)
    assert j['target'] == pytest.approx(math.radians(60.-OFF_DEG), abs=1e-9)
    assert (status.junction.map_entry_used, status.junction.map_entry_reason) == (False, 'none_sent')
    offset, yaw = _pass_end(rig)                           # out of the lane on the wall's side
    assert offset < -.06 and yaw == pytest.approx(60.-OFF_DEG, abs=3.), (offset, yaw)


def test_the_map_heading_is_placed_at_receipt_through_the_yaw_pair():
    """Fleet's map pose yaw may be anything against odom: only its difference to the lane counts."""
    rig = _wall_rig()
    send(rig, map_entry=_entry(rig, lane_yaw=.1))          # the lane runs 0.1 rad left of the body
    assert rig.m._junction['map_entry']['yaw'] == pytest.approx(.1, abs=1e-9)
    until(rig, 'bending')
    assert rig.m._junction['anchor'][2] == pytest.approx(.1, abs=1e-9)
    assert rig.m._junction['target'] == pytest.approx(.1+math.radians(60.), abs=1e-9)


@pytest.mark.parametrize('off_deg, used, reason', [(29., True, None), (31., False, 'heading')])
def test_a_body_yaw_past_the_bound_keeps_its_own_anchor_line(off_deg, used, reason):
    assert bend.MAP_ENTRY_MAX_HEADING_RAD == pytest.approx(math.radians(30.))
    rig = _wall_rig()
    send(rig, map_entry=_entry(rig))
    _, status = _steered_take_over(rig, off_deg)
    assert (status.junction.map_entry_used, status.junction.map_entry_reason) == (used, reason)
    assert rig.m._junction['anchor'][2] == pytest.approx(0. if used else -math.radians(off_deg), abs=1e-9)


def _todays(rig, reason):
    """Armed with today's anchor rule and the reason on the record, through the take-over."""
    assert rig.m._junction['map_entry'] == dict(reason=reason)
    assert rig.m.status().junction.map_entry_reason == reason
    _, status = _steered_take_over(rig)
    assert rig.m._junction['anchor'][2] == pytest.approx(-math.radians(OFF_DEG), abs=1e-9)
    assert (status.junction.map_entry_used, status.junction.map_entry_reason) == (False, reason)


def test_a_map_entry_older_than_the_bound_keeps_todays_anchor():
    rig = _wall_rig()
    old = _entry(rig)
    for _ in range(round(authority.ARC_ANCHOR_MAX_AGE_S/.05)+1):
        site_step(rig)
    send(rig, map_entry=old)
    _todays(rig, 'stale')


@pytest.mark.parametrize('offset, reason', [(.5, 'future'), (-.9, 'no_sample')])
def test_a_stamp_outside_cores_odom_history_keeps_todays_anchor(offset, reason):
    rig = _wall_rig()
    site_step(rig)
    send(rig, map_entry=_entry(rig, odom_stamp_s=WALL+rig.now+offset))
    _todays(rig, reason)


def test_an_odom_reset_before_receipt_keeps_todays_anchor():
    rig = _wall_rig()
    entry = _entry(rig)
    rig.m.invalidate_return_pose()                         # a new odom epoch: the pair's sample is gone
    site_step(rig)
    send(rig, map_entry=entry)
    _todays(rig, 'no_sample')


def test_more_odom_travel_than_the_carry_bound_keeps_todays_anchor():
    rig = _wall_rig()
    assert rig.m.set_junction('bend', 'B1', 30., None, 60., None, expect={
        **BEND, 'bend_in_m': authority.ARC_ANCHOR_MAX_CARRY_M+.3, 'map_entry': _entry(rig)})[2] == 'armed'
    for _ in range(200):
        _, status = site_step(rig, dx=.02)
        if status.junction.state != 'armed':
            break
    assert status.junction.state == 'bending' and rig.x > authority.ARC_ANCHOR_MAX_CARRY_M
    assert (status.junction.map_entry_used, status.junction.map_entry_reason) == (False, 'carry')


@pytest.mark.parametrize('bad', [
    {}, 'x', [0., 0., 1.], dict(yaw_rad=0., pose_yaw_rad=0.), dict(yaw_rad=math.nan),
    dict(pose_yaw_rad=math.inf), dict(odom_stamp_s=math.nan), dict(odom_stamp_s=0.),
    dict(odom_stamp_s=None), dict(yaw_rad='0'), dict(pose_yaw_rad=True)])
def test_a_malformed_map_entry_is_refused(bad):
    rig = _wall_rig()
    entry = dict(_entry(rig), **bad) if isinstance(bad, dict) and len(bad) == 1 else bad
    with pytest.raises(ValueError):
        send(rig, map_entry=entry)
    assert rig.m.status().junction.state == 'idle'


def test_map_entry_belongs_to_bend():
    rig = _wall_rig()
    with pytest.raises(ValueError):
        # D-759 rev 1: a left/right turn takes one too (test_junction_turn_map_entry.py)
        rig.m.set_junction('straight', 'J1', 10., None, None, None, expect=dict(map_entry=_entry(rig)))


def test_the_own_line_rule_reads_the_map_entry_axis():
    """D-507 note 9 on the lane's axis: a line 0.1 m past the vertex of the measured 90 deg corner
    is the bend's own outer line although the body came in 21.6 deg off."""
    rig = _wall_rig()
    send(rig, turn=90., map_entry=_entry(rig))
    _steered_take_over(rig)
    _sight_past_the_vertex(rig, .1)
    decision, status = until(rig, 'idle')
    assert decision.linear > 0 and rig.m._junction_held is False


def test_capability_needs_the_flag_and_lane_bend():
    assert site_rig(bend_map_entry_enabled=True).m.supports_lane_bend_map_entry is False
    assert site_rig(**SITE).m.supports_lane_bend_map_entry is False     # the flag is off by default
    assert site_rig(**SITE).m.supports_lane_bend is True
    assert site_rig(**SITE, bend_map_entry_enabled=True).m.supports_lane_bend_map_entry is True
    with pytest.raises(ValueError):
        site_rig(bend_map_entry_enabled=1)


def test_with_the_flag_off_a_map_entry_is_ignored_and_the_pass_is_todays():
    """Review 1: nothing changes on a robot until line_follow.bend_map_entry_enabled is set."""
    off, plain = _wall_rig(enabled=False), _wall_rig(enabled=False)
    assert send(off, map_entry=_entry(off)) == (True, 1, 'armed') and send(plain) == (True, 1, 'armed')
    assert off.m._junction['map_entry'] == dict(reason='disabled')
    (_, s1), (_, s2) = _steered_take_over(off), _steered_take_over(plain)
    assert (s1.junction.map_entry_used, s1.junction.map_entry_reason) == (False, 'disabled')
    assert s2.junction.map_entry_reason == 'none_sent'
    assert off.m._junction['anchor'] == plain.m._junction['anchor']
    assert off.m._junction['path'] == plain.m._junction['path']
    for _ in range(60):
        (d1, s1), (d2, s2) = site_step(off, move=True), site_step(plain, move=True)
        assert (d1.linear, d1.angular, s1.junction.state) == (d2.linear, d2.angular, s2.junction.state)


def _camera_reads(rig, error):
    """From now on the camera sees the lane `error` off centre: tracking, but not straight."""
    observe = rig.m.observe
    rig.m.observe = lambda obs, **kw: observe(
        dataclasses.replace(obs, error=error) if obs.visible and obs.error == 0. else obs, **kw)


def test_a_stale_anchor_is_rebased_to_the_body_when_the_map_heading_is_used():
    """Review 2: the last straight tick is 0.22 m back and the body drove on 21.6 deg off the lane,
    7 cm beside a line from that point on the lane's heading (past OFF_PATH_M). The entry line
    starts at the body instead, and the arc start stays bend_in of travel from the receipt."""
    rig = _wall_rig()
    assert send(rig, bend_in_m=.6, map_entry=_entry(rig)) == (True, 1, 'armed')
    while rig.x < .08:                                     # straight ticks, before the lead window
        site_step(rig, dx=.01)
    _camera_reads(rig, .2)
    for k in range(400):
        if k < 5:
            rig.yaw -= math.radians(OFF_DEG)/5
        rig.y += .01*math.sin(rig.yaw)
        _, status = site_step(rig, dx=.01*math.cos(rig.yaw))
        if status.junction.state != 'armed':
            break
    j = rig.m._junction
    assert status.junction.state == 'bending' and status.junction.map_entry_used is True
    assert j['bend_in']-j['anchor'][3] == pytest.approx(.3, abs=.011)  # taken over at the lead window's edge
    assert rig.y < -.065                                   # the old anchor's line (y = 0) is past OFF_PATH_M
    assert j['anchor'][:3] == pytest.approx((rig.x, rig.y, 0.), abs=1e-9)
    until(rig, 'reacquiring')                              # no off_path: the pass drives its arc
    assert math.degrees(rig.yaw) > 20.


@pytest.mark.parametrize('wrong_deg', [15., 25.])
def test_a_wrong_fleet_yaw_turns_the_entry_line_of_an_aligned_body(wrong_deg):
    """Review 1 / D-759 limit 8, pinned: the body follows the lane exactly and Fleet's map yaw of
    it is wrong. The entry line follows the map entry, so here it is worse than the body's own yaw."""
    rig, wrong = _wall_rig(), math.radians(wrong_deg)
    send(rig, map_entry=_entry(rig, pose_yaw_rad=rig.yaw+MAP_TURN+wrong))
    _, status = until(rig, 'bending')
    j = rig.m._junction
    assert (status.junction.map_entry_used, status.junction.map_entry_reason) == (True, None)
    assert j['anchor'][2] == pytest.approx(-wrong, abs=1e-9)
    (x0, y0), (x1, y1) = j['path'][0], j['path'][6]
    assert y1-y0 == pytest.approx(-.03*math.sin(wrong), abs=1e-9)   # toward the wall of a left bend
    assert j['target'] == pytest.approx(math.radians(60.)-wrong, abs=1e-9)


def test_a_lateral_offset_is_kept_through_the_pass_not_closed():
    """D-759 limit 1: heading only. A body 5 cm inside the lane at the take-over (Gazebo W3) stays
    beside the lane's exit line by that offset seen along the exit (cos 60): the path is parallel
    to the lane, through the body."""
    rig = _wall_rig(y=.085)                                # the steering drifts it 3.4 cm back toward the centre
    send(rig, map_entry=_entry(rig))
    _steered_take_over(rig)
    beside = rig.m._junction['anchor'][1]                  # the body's offset at the take-over
    offset, yaw = _pass_end(rig)
    assert beside == pytest.approx(.05, abs=.01) and yaw == pytest.approx(60., abs=3.)
    assert offset == pytest.approx(beside*math.cos(math.radians(60.)), abs=.02), (offset, beside)
    assert offset > 0.


def test_a_resend_places_a_heading_the_first_receipt_could_not():
    """Review 3: the first map_entry was stale; the refresh brings a fresh pose pair."""
    rig = _wall_rig()
    old = _entry(rig)
    for _ in range(round(authority.ARC_ANCHOR_MAX_AGE_S/.05)+1):
        site_step(rig)
    send(rig, map_entry=old)
    assert rig.m._junction['map_entry'] == dict(reason='stale')
    assert send(rig, map_entry=_entry(rig, lane_yaw=.1)) == (True, 1, 'armed')
    assert rig.m._junction['map_entry']['yaw'] == pytest.approx(.1, abs=1e-9)
    assert rig.m.status().junction.map_entry_reason is None
    assert send(rig, map_entry=_entry(rig, lane_yaw=.2)) == (True, 1, 'armed')   # a placed one stays
    assert rig.m._junction['map_entry']['yaw'] == pytest.approx(.1, abs=1e-9)
    assert send(rig) == (True, 1, 'armed') and 'yaw' in rig.m._junction['map_entry']
