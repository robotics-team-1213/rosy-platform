"""D-507 items 3-4: the junction instruction's expected window and the approach to the pivot,
in the real line-follow manager (no ROS, no physical motion)."""
import pytest

from core_features.line_follow.recovery.junction import JunctionRefused
from test_junction_turn_site_basis import SITE, site_step
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
    assert send(rig, pivot_past_line_m=.1, **WINDOW) == (True, 1, 'armed')  # cross line at x .4
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


def test_window_needs_fresh_odom_when_it_arrives():
    rig = Rig()
    with pytest.raises(JunctionRefused) as refused:
        send(rig, **WINDOW)
    assert refused.value.code == 'JUNCTION_ODOM_STALE' and rig.m.status().junction.state == 'idle'


@pytest.mark.parametrize('expect', [dict(expect_in_m=.5), dict(expect_tol_m=.1),
                                    dict(expect_in_m=2.1, expect_tol_m=.1),
                                    dict(expect_in_m=.5, expect_tol_m=.31),
                                    dict(pivot_past_line_m=.31)])
def test_invalid_window_fields_raise(expect):
    rig = Rig()
    rig.step()
    with pytest.raises(ValueError):
        send(rig, **expect)
    with pytest.raises(ValueError):
        send(rig, action='straight', pivot_past_line_m=.1)


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
    rig = Rig(proof=False, **SITE)
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
