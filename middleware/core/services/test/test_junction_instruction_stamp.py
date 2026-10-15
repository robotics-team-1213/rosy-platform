"""D-767 A: a junction or bend instruction carrying ``pose_stamp`` (the odom stamp of the pose Fleet
measured from) has its expect_in_m / bend_in_m measured from that odom sample, not from receipt.
Without an exact usable sample CORE keeps today's receipt basis and says why (never refuses)."""
import pytest

from test_junction_turn_site_basis import SITE, site_rig, site_step
from test_line_junction import Rig

WALL = 1_790_000_000.            # CORE wall clock at rig time 0 (snapshot odom_pose.stamp is on it)
BEND = dict(map_id='lab-a', bend_in_m=.3, bend_tol_m=.05, bend_radius_m=.1)
WINDOW = dict(map_id='lab-a', expect_in_m=.5, expect_tol_m=.1, pivot_past_line_m=0.)
MOVED = .05                      # odom travel between Fleet's pose and receipt (5 ticks of 1 cm)


def _rig(enabled=True, offset=0.):
    rig = site_rig(**SITE, instruction_stamp_enabled=enabled)
    rig.m._wall = lambda: WALL + offset + rig.now
    site_step(rig)
    return rig


def _moved(rig, then=None):
    """The wall stamp of the newest odom sample (Fleet's pose), then MOVED of travel before receipt."""
    stamp = WALL + rig.now
    if then is not None:
        then()
    for _ in range(5):
        site_step(rig, dx=MOVED/5)
    return stamp


def _bend(rig, stamp):
    return rig.m.set_junction('bend', 'B1', 10., None, 60., None, expect=BEND, pose_stamp=stamp)


def _straight(rig, stamp):
    return rig.m.set_junction('straight', 'J1', 10., expect=WINDOW, pose_stamp=stamp)


def _basis(rig):
    j = rig.m.status().junction
    return j.distance_basis, j.distance_basis_reason


def test_a_stamped_bend_counts_the_travel_since_its_pose():
    rig = _rig()
    assert _bend(rig, _moved(rig)) == (True, 1, 'armed')
    assert rig.m._junction['travel'] == pytest.approx(MOVED, abs=1e-9)
    assert _basis(rig) == ('stamp', None)
    for _ in range(400):
        _, status = site_step(rig, move=True)
        if status.junction.state == 'bending':
            break
    assert rig.x == pytest.approx(.25, abs=.01)         # bend_in - tol from Fleet's pose, not from receipt


def test_an_unstamped_bend_counts_from_receipt_as_before():
    rig = _rig()
    _moved(rig)
    assert _bend(rig, None) == (True, 1, 'armed')
    assert rig.m._junction['travel'] == 0.
    assert _basis(rig) == ('receipt', 'none_sent')
    for _ in range(400):
        _, status = site_step(rig, move=True)
        if status.junction.state == 'bending':
            break
    assert rig.x == pytest.approx(MOVED+.25, abs=.01)


def test_a_stamped_window_starts_at_the_odometer_of_its_pose():
    rig = _rig()
    trail = rig.m._return_evidence.trail
    before = trail.odometer
    stamp = _moved(rig)
    assert _straight(rig, stamp) == (True, 1, 'armed')
    w = rig.m._junction['window']
    assert w['odometer'] == pytest.approx(before, abs=1e-9)
    assert trail.odometer - w['odometer'] == pytest.approx(MOVED, abs=1e-9)
    assert w['peak'] == w['odometer'] and w['retreat'] == 0.
    assert _basis(rig) == ('stamp', None)


def test_the_stamped_sample_is_the_one_odom_message_in_both_logs():
    """The authority log entry found by the stamp and the trail sample whose odometer is the basis
    are the same odom message (stamp_ns), so the two accumulators never mix."""
    rig = _rig()
    stamp = _moved(rig)
    entry, exact = rig.m._odom_entry(stamp)
    (odometer, received_at), why = rig.m._stamp_odometer(stamp, rig.now)
    trail = rig.m._return_evidence.trail
    sample = next(p for p in trail.samples if p.received_at == received_at)
    assert exact and why is None and sample.stamp_ns == entry[2]
    assert trail.odometer_at(sample) == odometer


@pytest.mark.parametrize('offset', [5., -5.])
def test_a_wall_clock_step_after_the_pose_still_finds_its_sample(offset):
    rig = _rig()
    stamp = WALL + rig.now
    rig.m._wall = lambda: WALL + offset + rig.now   # the wall clock steps; the logged stamps stay
    for _ in range(5):
        site_step(rig, dx=MOVED/5)
    _bend(rig, stamp)
    assert _basis(rig) == ('stamp', None)
    assert rig.m._junction['travel'] == pytest.approx(MOVED, abs=1e-9)


def _ambiguous(rig):
    rig.m._wall = lambda: WALL + 7.               # two samples published with one stamp
    site_step(rig, dx=.01)
    site_step(rig, dx=.01)
    rig.m._wall = lambda: WALL + 8. + rig.now
    return WALL + 7.


@pytest.mark.parametrize('stamp, reason', [
    (lambda rig: WALL - 3., 'stale'),
    (lambda rig: WALL + rig.now + .2, 'future'),
    (lambda rig: WALL + rig.now - .025, 'no_sample'),   # between two samples: no exact one
    (_ambiguous, 'ambiguous'),
])
def test_an_unusable_stamp_keeps_the_receipt_basis_with_the_reason(stamp, reason):
    rig = _rig()
    for _ in range(5):
        site_step(rig, dx=MOVED/5)
    assert _bend(rig, stamp(rig)) == (True, 1, 'armed')  # never refused
    assert rig.m._junction['travel'] == 0.
    assert _basis(rig) == ('receipt', reason)
    rig2 = _rig()
    for _ in range(5):
        site_step(rig2, dx=MOVED/5)
    _straight(rig2, stamp(rig2))
    trail = rig2.m._return_evidence.trail
    assert rig2.m._junction['window']['odometer'] == trail.odometer
    assert _basis(rig2) == ('receipt', reason)


def test_with_the_flag_off_a_stamp_is_ignored_and_the_bend_is_todays():
    off, plain = _rig(enabled=False), _rig(enabled=False)
    _bend(off, _moved(off))
    _moved(plain)
    _bend(plain, None)
    assert _basis(off) == ('receipt', 'disabled') and _basis(plain) == ('receipt', 'none_sent')
    for _ in range(60):
        (d1, s1), (d2, s2) = site_step(off, move=True), site_step(plain, move=True)
        assert (d1.linear, d1.angular, s1.state, s1.reason, s1.junction.state) == (
            d2.linear, d2.angular, s2.state, s2.reason, s2.junction.state)


def test_an_instruction_without_a_distance_has_no_basis():
    rig = _rig()
    rig.m.set_junction('stop', 'J1', 10., .1, pose_stamp=WALL + rig.now)
    assert _basis(rig) == (None, None)


def test_capability_follows_the_flag():
    assert Rig(instruction_stamp_enabled=True).m.supports_lane_instruction_stamp is True
    assert Rig().m.supports_lane_instruction_stamp is False
    with pytest.raises(ValueError):
        Rig(instruction_stamp_enabled=1)


@pytest.mark.parametrize('bad', [0., -1., float('nan'), float('inf'), True, '1'])
def test_a_malformed_stamp_is_a_value_error(bad):
    rig = _rig()
    with pytest.raises(ValueError):
        _bend(rig, bad)
