"""D-767 A: a junction or bend instruction carrying ``pose_stamp`` (the odom stamp of the pose Fleet
measured from) has its expect_in_m / bend_in_m measured from that odom sample, not from receipt.
Review (Safety-Review CONDITIONS): a stamp CORE cannot use refuses the instruction (Fleet resends with a
fresh one); counting travel has no age cut while the trail holds the sample."""
import pytest

from core_features.line_follow.recovery.junction.gate import JunctionRefused

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


def _left_the_trail(rig):
    stamp = WALL + rig.now
    for _ in range(110):                          # > 5 s: the trail drops it, the odom log still has it
        site_step(rig)
    return stamp


@pytest.mark.parametrize('stamp, reason', [
    (lambda rig: WALL - 3., 'no_sample'),
    (lambda rig: WALL + rig.now + .2, 'future'),
    (lambda rig: WALL + rig.now - .025, 'no_sample'),   # between two samples: no exact one
    (_ambiguous, 'ambiguous'),
    (_left_the_trail, 'stale'),
])
@pytest.mark.parametrize('send', [_bend, _straight])
def test_an_unusable_stamp_refuses_the_instruction_and_changes_nothing(stamp, reason, send):
    rig = _rig()
    rig.m.set_junction('straight', 'J0', 10.)            # a held instruction the refusal must keep
    for _ in range(5):
        site_step(rig, dx=MOVED/5)
    held, seq = dict(rig.m._junction), rig.m._junction_seq
    with pytest.raises(JunctionRefused) as refused:
        send(rig, stamp(rig))
    assert (refused.value.code, refused.value.reason) == ('INSTRUCTION_STAMP_UNUSABLE', reason)
    assert rig.m._junction == held and rig.m._junction_seq == seq


def test_with_the_flag_off_a_stamped_distance_is_refused_as_disabled():
    rig = _rig(enabled=False)
    with pytest.raises(JunctionRefused) as refused:
        _bend(rig, _moved(rig))
    assert refused.value.reason == 'disabled' and rig.m._junction is None
    assert _bend(rig, None) == (True, 1, 'armed') and _basis(rig) == ('receipt', 'none_sent')


def test_travel_is_counted_from_a_stamp_2_5_s_old():
    """Review HIGH (a): no 2 s age cut for counting travel while the trail holds the sample."""
    rig = _rig()
    stamp = WALL + rig.now
    for _ in range(50):                           # 2.5 s, 0.1 m
        site_step(rig, dx=.002)
    _bend(rig, stamp)
    assert _basis(rig) == ('stamp', None)
    assert rig.m._junction['travel'] == pytest.approx(.1, abs=1e-9)


def test_a_reverse_between_the_stamp_and_receipt_is_a_window_retreat():
    """Review 3: the window folds the samples after the stamp (seen_to is the stamp's sample)."""
    rig = _rig()
    stamp = _moved(rig)                           # stamp after 0 m, then 0.05 m forward
    for _ in range(3):
        site_step(rig, dx=-.01)                   # and 0.03 m back, all before receipt
    _straight(rig, stamp)
    w = rig.m._junction['window']
    rig.m._track_retreat(w)
    assert w['retreat'] == pytest.approx(.03, abs=1e-9)
    assert rig.m._in_window(rig.m._junction, rig.now) is False


def test_an_instruction_without_a_distance_has_no_basis():
    rig = _rig(enabled=False)                     # never refused: the stamp measures nothing here
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
