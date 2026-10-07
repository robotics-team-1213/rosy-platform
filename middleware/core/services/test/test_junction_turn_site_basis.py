"""D-498: the junction turn's motion basis is the D-400 enforce proof or the site basis
(fresh IR guard verdict, live D-422 body stop, junction_turn_site_accepted)."""
import pytest

from core_features.line_follow.model import LineFollowConfig, LineFollowMode, LineObservation
from test_line_junction import BODY, Rig

SITE = dict(BODY, ir_guard_enabled=True, junction_turn_site_accepted=True)
CLEAR = [(1.5, 1.5)]
IR = LineFollowMode.IR_LINE


def site_step(rig, ir='clear', points=CLEAR, **kwargs):
    """One rig tick with an IR guard sample ('clear', 'centre' or 'stale' = none) and a scan."""
    t = round(rig.now + .05, 6)
    if ir != 'stale':
        visible = ir == 'centre'
        rig.m.observe(LineObservation(IR, t, visible, 0. if visible else None, .9 if visible else 0.,
                                      ir_calibrated=True, calibration_revision='r'), received_at=t)
    return rig.step(points=points, **kwargs)


def _corner(rig):
    rig.m.observe_junction('no_boundary', rig.now, corner_turning=True)


def test_enforce_basis_alone_reports_junction_turn():
    rig = Rig()                                  # D-400 enforce proof bound and configured
    _corner(rig)
    assert rig.m.supports_junction_turn is True


def test_site_basis_alone_reports_junction_turn():
    rig = Rig(proof=False, **SITE)
    site_step(rig)
    _corner(rig)
    assert rig.m.supports_junction_turn is True


@pytest.mark.parametrize('missing', ['accepted', 'ir_stale', 'ir_departure', 'scan_stale', 'body'])
def test_any_missing_site_piece_reports_no_junction_turn(missing):
    config = dict(SITE)
    if missing == 'accepted':
        config['junction_turn_site_accepted'] = False
    if missing == 'body':
        config = {k: v for k, v in config.items() if k != 'body_front_x_m'}
    rig = Rig(proof=False, **config)
    site_step(rig, ir={'ir_stale': 'stale', 'ir_departure': 'centre'}.get(missing, 'clear'))
    if missing == 'scan_stale':
        rig.now += 1.                            # beyond clearance_stale_s; IR still fresh
        rig.m.observe(LineObservation(IR, rig.now, False, None, 0., ir_calibrated=True,
                                      calibration_revision='r'), received_at=rig.now)
    _corner(rig)
    assert rig.m.supports_junction_turn is False


def test_capability_is_recomputed_when_the_ir_verdict_ages():
    rig = Rig(proof=False, **SITE)
    site_step(rig)
    _corner(rig)
    assert rig.m.supports_junction_turn is True
    rig.now += .4                                # IR older than stale_after_s
    _corner(rig)
    assert rig.m.supports_junction_turn is False


def _site_turning(rig):
    site_step(rig)
    rig.send('left', turn_deg=90.)
    for _ in range(10):
        decision, status = site_step(rig, junction=True, seen=False, move=True)
        if decision.angular:
            break
    assert status.junction.state == 'turning' and decision.angular > 0
    return decision, status


def test_site_basis_turns_without_a_motion_probe_and_completes():
    rig = Rig(proof=False, **SITE)
    _site_turning(rig)
    for _ in range(200):
        decision, status = site_step(rig, seen=False, move=True)
        if status.junction.state != 'turning':
            break
    assert status.junction.state == 'advancing' and decision.linear > 0


@pytest.mark.parametrize('ir', ['stale', 'centre'])
def test_losing_the_site_basis_mid_turn_aborts_turn_basis_lost(ir):
    rig = Rig(proof=False, **SITE)
    _site_turning(rig)
    rig.now += .3 if ir == 'stale' else 0.
    decision, status = site_step(rig, ir=ir, seen=False, move=True)
    assert (status.junction.state, status.junction.reason) == ('aborted', 'turn_basis_lost')
    assert (decision.linear, decision.angular) == (0., 0.)


def test_without_any_basis_the_turn_is_motion_unconfirmed():
    rig = Rig(proof=False, **BODY)
    site_step(rig, ir='stale')
    rig.send('left', turn_deg=90.)
    decision, status = rig.step(junction=True, seen=False, points=CLEAR)
    assert (status.junction.state, status.junction.reason) == ('aborted', 'motion_unconfirmed')


@pytest.mark.parametrize('bad', [dict(junction_turn_site_accepted=True),
                                 dict(junction_turn_site_accepted='true', ir_guard_enabled=True)])
def test_site_acceptance_needs_the_ir_guard_and_a_boolean(bad):
    with pytest.raises(ValueError, match='junction_turn_site_accepted'):
        LineFollowConfig(**bad)


def test_default_is_off_and_reports_no_turn_without_enforce():
    assert LineFollowConfig().junction_turn_site_accepted is False
    rig = Rig(proof=False, **BODY)
    site_step(rig, ir='stale')
    _corner(rig)
    assert rig.m.supports_junction_turn is False
