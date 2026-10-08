"""D-507 items 3-4: the junction instruction's expected window and the approach to the pivot,
in the real line-follow manager (no ROS, no physical motion)."""
import math
from types import SimpleNamespace

import pytest

from core_features.line_follow.recovery.junction import JunctionRefused
from core_features.line_follow.recovery.junction_approach import cross_line_band
from test_junction_turn_site_basis import SITE, site_rig, site_step
from core_features.line_follow.model import LineFollowMode
from test_line_junction import BODY, Rig

WINDOW = dict(expect_in_m=.5, expect_tol_m=.1)
CLEAR = [(1.5, 1.5)]


def send(rig, action='left', turn_deg=90., **expect):
    return rig.m.set_junction(action, 'J1', 10., None, turn_deg if action in ('left', 'right') else None,
                              None, expect=expect or None)


def sight(rig, ahead=.2, reason='junction_transverse', step=None, **kwargs):
    """One tick with a keep_debug sighting carrying junction_ahead_m (None: field absent)."""
    rig.m.observe_junction(reason, round(rig.now + .05, 6), ahead_m=ahead)
    return (step or Rig.step)(rig, **kwargs)


def drive_to(rig, x, **kwargs):
    while rig.x < x - 1e-9:
        rig.step(dx=.01, **kwargs)


# --- item 3: the expected window --------------------------------------------------------

@pytest.mark.parametrize('ahead, inside', [(.2, True), (.29, True), (.05, False), (.32, False)])
def test_window_takes_only_a_sighting_near_the_expected_cross_line(ahead, inside):
    rig = Rig()
    rig.step()
    assert send(rig, map_id='site', pivot_past_line_m=.1, **WINDOW) == (True, 1, 'armed')  # line at x .4
    drive_to(rig, .2)
    decision, status = sight(rig, ahead=ahead, seen=False)                 # measured .2 + ahead
    if inside:
        assert status.junction.state == 'turning'
    else:
        assert (decision.linear, decision.angular) == (0., 0.)
        assert (status.state, status.reason, status.junction.state) == ('HOLD', 'junction_unexpected',
                                                                        'unexpected')
        assert rig.m._junction['state'] == 'armed' and status.junction.pending_action == 'left'


def test_outside_sighting_keeps_the_instruction_for_the_real_junction():
    rig = Rig()
    rig.step()
    send(rig, pivot_past_line_m=.1, **WINDOW)
    drive_to(rig, .05)
    assert sight(rig, ahead=.1, seen=False)[1].junction.state == 'unexpected'  # a bend at .15
    for _ in range(8):                                                          # sighting ends
        decision, status = rig.step()
    assert status.junction.state == 'armed' and decision.linear > 0
    drive_to(rig, .2)
    assert sight(rig, ahead=.2, seen=False)[1].junction.state == 'turning'


def test_fork_window_has_no_pivot_offset():
    rig = Rig()
    rig.step()
    send(rig, pivot_past_line_m=.1, **WINDOW)
    drive_to(rig, .2)
    assert sight(rig, ahead=.35, reason='junction_fork', seen=False)[1].junction.state == 'turning'
    rig = Rig()
    rig.step()
    send(rig, pivot_past_line_m=.1, **WINDOW)
    drive_to(rig, .2)
    assert sight(rig, ahead=.35, seen=False)[1].junction.state == 'unexpected'  # transverse: .4


@pytest.mark.parametrize('ahead', [None, 'odom_restart'])
def test_unmeasurable_sighting_is_outside(ahead):
    rig = Rig()
    rig.step()
    send(rig, action='straight', **WINDOW)
    drive_to(rig, .2)
    if ahead == 'odom_restart':
        rig.m._return_evidence.epoch += 1  # the window's odom frame is no longer comparable
        ahead = .3
    decision, status = sight(rig, ahead=ahead)
    assert decision.linear == 0. and status.junction.state == 'unexpected'


def test_straight_inside_the_window_executes():
    rig = Rig()
    rig.step()
    send(rig, action='straight', **WINDOW)
    drive_to(rig, .2)
    decision, status = sight(rig, ahead=.3)
    assert decision.linear > 0 and status.junction.state == 'executing'


def test_no_instruction_still_waits():
    rig = Rig()
    decision, status = sight(rig, ahead=.2)
    assert decision.linear == 0. and status.junction.state == 'waiting'


def test_old_client_without_fields_turns_at_any_sighting_from_the_stop_point():
    rig = Rig()
    rig.step()
    send(rig)
    drive_to(rig, .2)
    assert sight(rig, ahead=1.5, seen=False)[1].junction.state == 'turning'
    status = _until(rig, lambda s: s.junction.state != 'turning', ahead=1.5)
    assert status.junction.state == 'advancing' and status.junction.pivot_basis == 'stop_point'
    assert rig.x == pytest.approx(.2, abs=1e-6)  # no approach


@pytest.mark.parametrize('action', ['left', 'straight'])
def test_map_junction_without_a_window_holds_an_early_sighting(action):
    rig = Rig()
    rig.step()
    assert send(rig, action=action, map_id='site', pivot_past_line_m=.1) == (True, 1, 'armed')
    drive_to(rig, .2)
    decision, status = sight(rig, ahead=.1, seen=False)
    assert (decision.linear, decision.angular) == (0., 0.)
    assert (status.state, status.reason, status.junction.state) == (
        'HOLD', 'junction_unexpected', 'unexpected')
    assert rig.m._junction['state'] == 'armed' and status.junction.pending_action == action


def test_window_needs_fresh_odom_when_it_arrives():
    rig = Rig()
    with pytest.raises(JunctionRefused) as refused:
        send(rig, **WINDOW)
    assert refused.value.code == 'JUNCTION_ODOM_STALE' and rig.m.status().junction.state == 'idle'


@pytest.mark.parametrize('expect', [dict(expect_in_m=.5), dict(expect_tol_m=.1),
                                    dict(expect_in_m=2.1, expect_tol_m=.1),
                                    dict(expect_in_m=.5, expect_tol_m=.31),
                                    dict(pivot_past_line_m=.31), dict(pivot_past_line_m=-.31)])
def test_invalid_window_fields_raise(expect):
    rig = Rig()
    rig.step()
    with pytest.raises(ValueError):
        send(rig, **expect)
    with pytest.raises(ValueError):
        rig.m.set_junction('stop', 'J1', 10., expect=dict(pivot_past_line_m=.1))
    with pytest.raises(ValueError):
        rig.m.set_junction('left', 'J1', 10., expect=dict(pivot_past_line_m=.1))  # no turn_deg


# --- item 4: approach to the pivot ------------------------------------------------------

def _until(rig, done, limit=400, step=None, ahead=.2, reason='junction_transverse', sighting=True,
           **kwargs):
    for _ in range(limit):
        if sighting:
            decision, status = sight(rig, ahead=ahead, reason=reason, step=step, seen=False,
                                     move=True, **kwargs)
        else:
            decision, status = (step or Rig.step)(rig, seen=False, move=True, **kwargs)
        if done(status):
            return status
    raise AssertionError(status.junction)


def _approaching(rig, pivot=.1, reason='junction_transverse', step=None, **kwargs):
    (step or Rig.step)(rig, **kwargs)
    send(rig, pivot_past_line_m=pivot)
    drive_to(rig, .2, **kwargs)
    status = _until(rig, lambda s: s.junction.state != 'armed' and s.reason != 'junction_stopping',
                    reason=reason, step=step, **kwargs)
    return status


@pytest.mark.parametrize('pivot, reason, distance, basis', [
    (.1, 'junction_transverse', .3, 'map'),   # cross line .2 ahead + half lane width
    (.1, 'junction_fork', .2, 'map'),         # a fork turns at the measured branch end
    (-.1, 'junction_transverse', .1, 'map'),  # 2026-10-08: the far edge, the place .1 before it
    (-.25, 'junction_transverse', 0., 'map'),  # goal .15 is behind the robot at .2: turn here
    (None, 'junction_transverse', 0., 'stop_point')])  # no field: today's stop point
def test_approach_distance(pivot, reason, distance, basis):
    rig = Rig()
    status = _approaching(rig, pivot, reason)
    start = rig.x
    if distance:
        assert (status.junction.state, status.reason) == ('approaching', 'junction_approaching')
        assert rig.v == pytest.approx(.05)  # half of min(max_linear .10, manual ceiling .1)
        status = _until(rig, lambda s: s.junction.state != 'approaching', sighting=False)
        assert status.junction.state == 'turning'
    assert status.junction.pivot_basis == basis
    status = _until(rig, lambda s: s.junction.state != 'turning', sighting=False)
    assert status.junction.state == 'advancing'
    assert rig.x - start == pytest.approx(distance, abs=.006)


def test_pivot_without_junction_ahead_turns_at_the_stop_point():
    rig = Rig()
    rig.step()
    send(rig, pivot_past_line_m=.1)
    drive_to(rig, .2)
    status = _until(rig, lambda s: s.junction.state != 'turning', ahead=None)
    assert status.junction.state == 'advancing' and status.junction.pivot_basis == 'stop_point'


def _assert_aborted(rig, status, reason):
    assert (status.junction.state, status.junction.reason) == ('aborted', reason)
    assert rig.m._junction['state'] == 'aborted' and (rig.v, rig.w) == (0., 0.)


def test_approach_aborts_on_stale_odom():
    rig = Rig()
    _approaching(rig)
    rig.now += .4
    _assert_aborted(rig, rig.step(pose=False, seen=False)[1], 'odom')


def test_approach_aborts_on_mode_change():
    rig = Rig()
    _approaching(rig)
    rig.m.stop('estop')
    status = rig.m.status()
    assert (status.junction.state, status.junction.reason) == ('aborted', 'mode_change')


def test_approach_aborts_when_the_enforce_basis_is_lost():
    rig = Rig()
    _approaching(rig)
    rig.m.bind_return_motion(lambda now, v, w: True, proof_configured=lambda: False)
    _assert_aborted(rig, rig.step(seen=False, move=True)[1], 'motion_unconfirmed')


@pytest.mark.parametrize('ir', ['stale', 'centre'])
def test_approach_on_the_site_basis_aborts_when_it_is_lost(ir):
    rig = site_rig(**SITE)
    assert _approaching(rig, step=site_step).junction.state == 'approaching'
    rig.now += .3 if ir == 'stale' else 0.
    _assert_aborted(rig, site_step(rig, ir=ir, seen=False, move=True)[1], 'turn_basis_lost')


def test_approach_aborts_on_d422_near_stop():
    rig = Rig(**BODY)
    _approaching(rig, points=CLEAR)
    _assert_aborted(rig, rig.step(seen=False, move=True, points=[(.1, 0.)])[1], 'near_stop')


def test_approach_aborts_on_timeout():
    rig = Rig()
    _approaching(rig)
    rig.m._junction['speed'] = 1e-3  # odom shows no progress: distance / speed + 2 s runs out
    status = _until(rig, lambda s: s.junction.state != 'approaching', limit=200, sighting=False)
    assert (status.junction.state, status.junction.reason) == ('aborted', 'timeout')


def test_approach_aborts_on_a_new_instruction():
    rig = Rig()
    _approaching(rig)
    assert send(rig, action='straight') == (False, 1, 'aborted')
    _assert_aborted(rig, rig.step(seen=False, move=True)[1], 'new_instruction')


# --- review fixes (2026-10-08) ----------------------------------------------------------

@pytest.mark.parametrize('action', ['straight', 'left'])
def test_unexpected_clears_when_a_later_sighting_matches_while_still_seen(action):
    rig = Rig()
    rig.step()
    send(rig, action=action, **WINDOW)
    drive_to(rig, .2)
    assert sight(rig, ahead=.05, seen=False)[1].junction.state == 'unexpected'
    decision, status = sight(rig, ahead=.3, seen=False)                     # measured .5: inside
    assert status.junction.state == ('executing' if action == 'straight' else 'turning')
    for _ in range(3):
        assert sight(rig, ahead=.3, seen=False, move=True)[1].junction.state != 'unexpected'
    assert rig.m._junction['outside'] is False


def test_a_negative_pivot_expects_the_line_past_the_place():
    """2026-10-08: the far edge (roundabout entry, T) is .1 past the place at .5: line at .6."""
    for ahead, state in ((.4, 'turning'), (.2, 'unexpected')):
        rig = Rig()
        rig.step()
        send(rig, pivot_past_line_m=-.1, **WINDOW)
        drive_to(rig, .2)
        assert sight(rig, ahead=ahead, seen=False)[1].junction.state == state


def test_straight_pivot_biases_only_the_window():
    for ahead, state in ((.2, 'executing'), (.32, 'unexpected')):
        rig = Rig()
        rig.step()
        assert send(rig, action='straight', pivot_past_line_m=.1, **WINDOW)[2] == 'armed'
        drive_to(rig, .2)
        decision, status = sight(rig, ahead=ahead)                     # expected line .5 - .1
        assert status.junction.state == state
    assert status.junction.pivot_basis is None


def test_window_at_a_non_zero_yaw():
    for ahead, state in ((0., 'turning'), (.15, 'unexpected')):
        rig = Rig()
        rig.yaw = math.pi/2
        rig.step()
        send(rig, pivot_past_line_m=.1, **WINDOW)            # cross line at y .4, x 0
        while rig.y < .2:
            rig.step(move=True)
        ahead_m = .4-rig.y+ahead
        assert sight(rig, ahead=ahead_m, seen=False)[1].junction.state == state


def test_old_sighting_still_places_the_approach():
    """Review 4: the latest odom-anchored sighting counts at any age (no stop_point fallback)."""
    rig = Rig()
    rig.step()
    send(rig, pivot_past_line_m=.1)
    drive_to(rig, .2)
    assert sight(rig, ahead=.2, seen=False)[1].junction.state == 'turning'
    for _ in range(10):                                     # creeping: not still, sighting ages
        rig.step(seen=False, dx=.001)
    assert rig.now-rig.m._junction_seen_at > rig.m.config.stale_after_s
    status = _until(rig, lambda s: s.junction.state != 'turning', sighting=False)
    assert (status.junction.state, status.junction.pivot_basis) == ('approaching', 'map')
    status = _until(rig, lambda s: s.junction.state != 'approaching', sighting=False)
    assert rig.x == pytest.approx(.5, abs=.006)                # .2 + .2 + .1 from the anchor


def test_entry_yaw_steers_the_approach_and_its_goal():
    rig = Rig()
    rig.step()
    send(rig, pivot_past_line_m=.1)
    drive_to(rig, .2)
    sight(rig, ahead=.2, seen=False)
    rig.m._junction_entry = (.1, rig.m._junction_entry[1])   # entered at .1 rad, now at 0
    status = _until(rig, lambda s: s.junction.state != 'turning', ahead=.2)
    j = rig.m._junction
    assert status.junction.state == 'approaching' and j['yaw'] == .1
    assert j['goal'] == pytest.approx((.4+.1*math.cos(.1), .1*math.sin(.1)))
    decision, status = rig.step(seen=False, move=True)
    assert decision.angular == pytest.approx(2*(.1-rig.m._return_evidence.trail.samples[-1].yaw), abs=1e-9)


def test_heading_hold_gain_and_angular_cap():
    rig = Rig()
    _approaching(rig)
    j, cap = rig.m._junction, rig.m._angular_cap()
    pose = lambda yaw: SimpleNamespace(x=rig.x, y=rig.y, yaw=yaw)
    assert rig.m._approach_twist(j, pose(.1)) == (j['speed'], pytest.approx(-.2))
    assert rig.m._approach_twist(j, pose(-1.2)) == (j['speed'], pytest.approx(cap))
    assert rig.m._approach_twist(j, pose(1.2)) == (j['speed'], pytest.approx(-cap))


def test_approach_aborts_on_an_odom_epoch_change():
    rig = Rig()
    _approaching(rig)
    rig.m._return_evidence.epoch += 1
    _assert_aborted(rig, rig.step(seen=False, move=True)[1], 'odom')


# --- review 2: IR centre on the measured cross line (D-507 6, 2026-10-08) -------------------

def test_cross_line_band_edges():
    line = (.4, 0.)                                                      # the tape centre
    assert cross_line_band((.3776, 0.), line, 0., .025, .01, .1)         # .4 - .0125 - .01
    assert not cross_line_band((.3774, 0.), line, 0., .025, .01, .1)
    assert cross_line_band((.4224, 0.), line, 0., .025, .01, .1)         # .4 + .0125 + .01
    assert not cross_line_band((.4226, 0.), line, 0., .025, .01, .1)
    assert cross_line_band((.41, .1099), line, 0., .025, .01, .1)       # lateral: half + error
    assert not cross_line_band((.41, -.1101), line, 0., .025, .01, .1)
    assert cross_line_band((.05, .41), (0., .4), math.pi/2, .025, 0., .1)  # at yaw pi/2
    assert not cross_line_band((.15, .41), (0., .4), math.pi/2, .025, 0., .1)
    assert cross_line_band((0., .39), (0., .4), math.pi/2, .025, 0., .1)   # inside the tape half
    assert not cross_line_band((0., .385), (0., .4), math.pi/2, .025, 0., .1)


IR_ROW = dict(SITE, ir_row_x_m=.05)


def _band_straight(rig):
    site_step(rig)
    send(rig, action='straight')
    while rig.x < .2 - 1e-9:
        site_step(rig, dx=.01)
    sight(rig, ahead=.2, step=site_step)                      # line .4, anchor .2, error .01+.05*travel
    assert rig.m._cross_band['kind'] == 'straight'


@pytest.mark.parametrize('x, inside', [(.316, False), (.326, True), (.378, True), (.386, False)])
def test_band_edges_carry_range_and_odom_error(x, inside):
    # tape centre .4 +/- .0125, error .01 + .05 (x - .2):
    # lower edge: x + .05 = .3775 - .05 (x - .2) -> x = .3214; upper: x + .05 = .4225 + .05 (x - .2) -> .3816
    rig = site_rig(**IR_ROW)
    _band_straight(rig)
    while rig.x < x - .01:
        site_step(rig, dx=.01)
    site_step(rig, dx=x-rig.x)
    assert rig.m._centre_on_cross_line(rig.now) is inside


def test_straight_crossing_follows_over_the_line_only_inside_the_band():
    rig = site_rig(**IR_ROW)
    _band_straight(rig)
    decision, status = site_step(rig, ir='centre')            # IR row .25: before the band
    assert (status.state, status.reason) == ('HOLD', 'lane_departure')
    while rig.x < .35:
        site_step(rig, dx=.01)
    decision, status = site_step(rig, ir='centre')            # IR row on the measured line
    assert decision.linear > 0 and status.reason == 'tracking'


def test_band_dies_on_an_odom_epoch_change():
    rig = site_rig(**IR_ROW)
    _band_straight(rig)
    while rig.x < .35:
        site_step(rig, dx=.01)
    assert rig.m._centre_on_cross_line(rig.now) is True
    rig.m._return_evidence.epoch += 1
    assert rig.m._centre_on_cross_line(rig.now) is False and rig.m._cross_band is None


def test_approach_admits_centre_inside_the_band_and_aborts_outside():
    rig = site_rig(**IR_ROW)
    assert _approaching(rig, step=site_step).junction.state == 'approaching'
    while rig.x < .36:                                         # IR row onto the line at .4
        decision, status = site_step(rig, seen=False, move=True)
    decision, status = site_step(rig, ir='centre', seen=False, move=True)
    assert status.junction.state == 'approaching' and decision.linear > 0
    rig = site_rig(**IR_ROW)
    _approaching(rig, step=site_step)                          # IR row .25: outside the band
    _assert_aborted(rig, site_step(rig, ir='centre', seen=False, move=True)[1], 'turn_basis_lost')


def test_turning_never_takes_centre():
    rig = site_rig(**IR_ROW)
    _approaching(rig, step=site_step)
    _until(rig, lambda s: s.junction.state != 'approaching', step=site_step, sighting=False)
    assert rig.m._cross_band is None
    _assert_aborted(rig, site_step(rig, ir='centre', seen=False, move=True)[1], 'turn_basis_lost')


# --- re-review 1: the straight band is bounded (2026-10-08) -------------------------------

def _drive_site(rig, x):
    while rig.x < x - 1e-9:
        site_step(rig, dx=min(.01, x-rig.x))


def test_straight_band_is_spent_once_the_row_passes_the_far_edge():
    rig = site_rig(**IR_ROW)
    _band_straight(rig)
    _drive_site(rig, .35)
    assert rig.m._centre_on_cross_line(rig.now) is True
    _drive_site(rig, .40)                                      # row .45 > .425 + error
    assert rig.m._centre_on_cross_line(rig.now) is False and rig.m._cross_band is None


def test_a_side_line_a_metre_later_is_lane_departure():
    rig = site_rig(**IR_ROW)
    _band_straight(rig)
    _drive_site(rig, 1.2)
    decision, status = site_step(rig, ir='centre')
    assert (status.state, status.reason) == ('HOLD', 'lane_departure') and decision.linear == 0.


@pytest.mark.parametrize('pivot, lateral, inside', [
    (None, .10, True), (None, .125, False),      # D-491 corridor half-width .10 + error
    (.05, .06, True), (.05, .08, False),         # Fleet's lane half-width (pivot_past_line_m)
    (-.05, .10, True), (-.05, .125, False)])     # a negative pivot is no width: the corridor
def test_band_lateral_bound(pivot, lateral, inside):
    rig = site_rig(**IR_ROW)
    site_step(rig)
    expect = None if pivot is None else dict(pivot_past_line_m=pivot)
    rig.m.set_junction('straight', 'J1', 10., expect=expect)
    _drive_site(rig, .2)
    sight(rig, ahead=.2, step=site_step)
    _drive_site(rig, .35)
    while rig.y < lateral - 1e-9:                             # sidestep under the band
        rig.y = min(lateral, rig.y+.01)
        site_step(rig)
    assert rig.m._centre_on_cross_line(rig.now) is inside


@pytest.mark.parametrize('how', ['stop', 'mode_change'])
def test_band_cleared_by_stop_and_mode_change(how):
    rig = site_rig(**IR_ROW)
    _band_straight(rig)
    if how == 'stop':
        rig.m.stop('estop')
    else:
        rig.m.set_mode(LineFollowMode.IR_LINE)
    assert rig.m._cross_band is None


# --- 2026-10-08 user decision: the window compares travelled distance -------------------

def drive_arc(rig, radius, length, ds=.01):
    """Drive an arc to the left, odom only (x, y, yaw), ``ds`` per tick."""
    for _ in range(round(length / ds)):
        rig.yaw += ds / (2 * radius)
        rig.x += ds * math.cos(rig.yaw)
        rig.y += ds * math.sin(rig.yaw)
        rig.yaw += ds / (2 * radius)
        rig.step()


ARC_R, ARC_L = .25, math.pi * .25                      # a half circle: path .785 m, chord .50 m


@pytest.mark.parametrize('expect_in, inside', [(ARC_L + .2, True),            # the arc length
                                               (2 * ARC_R + .2, False)])      # the straight line
def test_curved_approach_compares_the_arc_length_not_the_straight_line(expect_in, inside):
    rig = Rig()
    rig.step()
    send(rig, map_id='site', expect_in_m=round(expect_in, 3), expect_tol_m=.1)
    drive_arc(rig, ARC_R, ARC_L)
    assert math.dist((rig.x, rig.y), (0., 0.)) == pytest.approx(2 * ARC_R, abs=.01)
    state = sight(rig, ahead=.2, seen=False)[1].junction.state
    assert state == ('turning' if inside else 'unexpected')


def test_a_bend_misread_0_3_m_before_the_place_is_outside():
    """The SIM lap (R3-4): place 0.6 m on, its far line 0.1 m past it, a bend 0.3 m before it."""
    rig = Rig()
    rig.step()
    send(rig, map_id='site', pivot_past_line_m=-.1, expect_in_m=.6, expect_tol_m=.12)
    drive_to(rig, .1)
    decision, status = sight(rig, ahead=.2, seen=False)                    # the bend at .3
    assert decision.linear == 0. and status.junction.state == 'unexpected'
    for _ in range(8):
        rig.step(seen=False)
    drive_to(rig, .3, seen=False)
    assert sight(rig, ahead=.4, seen=False)[1].junction.state == 'turning'  # the far line at .7


def test_an_odom_break_between_receipt_and_sighting_is_outside():
    rig = Rig()
    rig.step()
    send(rig, map_id='site', expect_in_m=.5, expect_tol_m=.1)
    drive_to(rig, .2)
    rig.x += .2                                         # a jump: the trail restarts, a new epoch
    rig.step(seen=False)
    assert sight(rig, ahead=.1, seen=False)[1].junction.state == 'unexpected'
