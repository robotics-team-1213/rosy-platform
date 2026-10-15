"""D-760 rev 3: a new wait never borrows an earlier driving interval."""
import pytest
from test_lane_arc import ArcRig, V, _authority


def test_first_wait_tick_does_not_extend_an_arc_deadline():
    rig = ArcRig()
    rig.open()
    rig.drive(10, seen=False)
    before = rig.m._arc['deadline']
    _authority(rig, True)
    rig.step(seen=False)
    assert rig.m._arc['deadline'] == pytest.approx(before)
    rig.step(seen=False)
    assert rig.m._arc['deadline'] == pytest.approx(before + .05)


def test_stalled_driving_tick_cannot_be_reclassified_as_a_wait():
    rig = ArcRig()
    rig.open()
    rig.drive(10, seen=False)
    _authority(rig, True)
    with rig.m._lock:
        assert rig.m._regulated_wait_share(rig.now + .2, .2, V) == 0.


def test_same_tick_does_not_change_the_previous_wait_sample():
    rig = ArcRig()
    rig.open()
    rig.drive(10, seen=False)
    _authority(rig, True)
    with rig.m._lock:
        assert rig.m._regulated_wait_share(rig.now, .05, V) == 0.
        assert rig.m._regulated_wait_share(rig.now + .05, .05, V) == 0.


def test_credit_needs_the_immediately_preceding_tick():
    rig = ArcRig()
    rig.open()
    rig.drive(10, seen=False)
    _authority(rig, True)
    rig.step(seen=False)
    with rig.m._lock:
        assert rig.m._regulated_wait_share(rig.now + 1., .05, V) == 0.


def test_mode_change_starts_without_a_previous_wait_sample():
    rig = ArcRig()
    rig.open()
    _authority(rig, True)
    rig.step(seen=False)
    rig.step(seen=False)
    rig.m.set_mode('CAMERA_LINE')
    with rig.m._lock:
        assert rig.m._regulated_wait_share(rig.now + .05, .05, V) == 0.


def test_same_tick_unheld_sample_removes_wait_credit():
    rig = ArcRig()
    rig.open()
    rig.drive(10, seen=False)
    now = rig.now + .05
    _authority(rig, True)
    with rig.m._lock:
        rig.m._regulated_wait_share(now, .05, V)
        _authority(rig, False)
        rig.m._regulated_wait_share(now, .05, V)
        _authority(rig, True)
        assert rig.m._regulated_wait_share(now + .05, .05, V) == 0.
        assert rig.m._regulated_wait_share(now + .10, .05, V) == pytest.approx(.05)


def _credit(rig, states):
    """The clock credit over one 0.05 s tick per authority state in `states` (D-760 rev 4)."""
    clock, total = {'added': 0.}, 0.
    rig.m._authority_on = lambda: True
    with rig.m._lock:
        for i, state in enumerate(states):
            rig.m._authority_state = lambda now, state=state: (state, None, 'test')
            total += rig.m._regulated_wait_share(round(rig.now + .05*(i+1), 6), .05, V, clock)
    return total


def test_free_holding_flapping_every_tick_earns_no_credit():
    rig = ArcRig()
    rig.open()
    assert _credit(rig, ['FREE', 'HOLDING']*300) == 0.


@pytest.mark.parametrize('state,credit', [('HOLDING', 29.95), ('NONE', 15.), ('EXPIRED', 15.)])
def test_only_a_holding_authority_is_uncapped(state, credit):
    """Fleet alive and saying wait stands the clock for the whole wait; no or a lapsed authority
    (link lost) keeps the crosswalk_report_s + clear_s cap, so a stale maneuver cannot resume."""
    rig = ArcRig()
    rig.open()
    assert _credit(rig, [state]*600) == pytest.approx(credit)
