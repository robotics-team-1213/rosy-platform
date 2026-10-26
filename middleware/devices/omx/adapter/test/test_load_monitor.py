"""Read-only source-time tracking; no bus, controller or stop guarantee."""
import pytest

from load_motion_fixtures import characteristics, health, request
from omx_adapter.motion_characteristics import characteristics_digest
from omx_adapter.load_assessment import command_positions
from omx_adapter.load_monitor import LoadMonitor


def monitor(p=None, r=None):
    p = p or characteristics()
    r = r or request(p)
    return LoadMonitor(p, r, accepted_digest=characteristics_digest(p), candidate_id='direct',
                       command_id='fixture-command', started_at=100.,
                       session_id='00000000-0000-4000-8000-000000000001')


def observation(p, r, captured, *, error=0., age=0.):
    h = health(p, age=age)
    desired = command_positions(r, 'direct', captured - 100.)
    for motor, q in zip(h.motors, desired):
        j = p['joints'][motor.joint]
        motor.present_raw = j['raw_zero'] + (q + error) / j['rad_per_raw']
    return h


def observe(m, p, r, t, *, error=0., age=0.):
    return m.observe(observation(p, r, t, error=error, age=age), captured_at=t,
                     now=t + age, context=r['context'])


def test_uses_source_time_not_receipt_time_final_goal_or_raw_goal():
    p, r = characteristics(), request()
    m = monitor(p, r)
    out = observe(m, p, r, 100.8, age=.05)
    assert out['status'] == 'observing'
    assert out['errors_rad']['joint2'] == pytest.approx(0.)
    assert out['motion_admitted'] is out['automatic_recovery_enabled'] is False
    assert out['command_id'] == 'fixture-command'
    assert out['characteristics_sha256'] == characteristics_digest(p)


def test_signed_raw_calibration_is_applied():
    p = characteristics()
    p['joints']['joint2']['rad_per_raw'] = -.001
    r = request(p)
    assert observe(monitor(p, r), p, r, 100.5)['errors_rad']['joint2'] == pytest.approx(0.)


def test_persistent_tracking_error_hysteresis_and_latched_recovery():
    p, r = characteristics(), request()
    m = monitor(p, r)
    assert observe(m, p, r, 100., error=.06)['status'] == 'observing'
    assert observe(m, p, r, 100.08, error=.03)['status'] == 'observing'
    assert observe(m, p, r, 100.16, error=.06)['status'] == 'observing'
    out = observe(m, p, r, 100.24, error=.06)
    assert out['status'] == 'hold_for_owner_review'
    assert 'following_error:joint2' in out['reasons']
    assert observe(m, p, r, 100.32)['status'] == 'hold_for_owner_review'
    assert out['recommendation'] == 'replan_from_fresh_state_after_owner_recovery'


def test_small_error_clears_persistence_timer():
    p, r = characteristics(), request()
    m = monitor(p, r)
    observe(m, p, r, 100., error=.06)
    observe(m, p, r, 100.08)
    assert observe(m, p, r, 100.16, error=.06)['status'] == 'observing'
    assert observe(m, p, r, 100.24, error=.06)['status'] == 'observing'


def test_oscillation_detects_repeated_signed_error_not_planned_motion():
    p = characteristics()
    p['monitor']['tracking_duration_s'] = 2.
    r = request(p)
    m = monitor(p, r)
    for i, err in enumerate([.045, -.045, .045, -.045, .045]):
        out = observe(m, p, r, 100. + i * .08, error=err)
    assert 'oscillation:joint2' in out['reasons']
    m = monitor(p, r)
    for i in range(8):
        out = observe(m, p, r, 100. + i * .08)
    assert out['status'] == 'observing'


@pytest.mark.parametrize('change,reason', [
    (lambda h: setattr(h.motors[0], 'hardware_error', 32), 'hardware_fault'),
    (lambda h: setattr(h.motors[0], 'temperature_c', 75.), 'temperature_limit'),
    (lambda h: setattr(h.motors[0], 'voltage_v', 9.), 'voltage_limit'),
    (lambda h: setattr(h.motors[0], 'temperature_c', 50.), 'outside_measured_domain'),
    (lambda h: setattr(h.motors[0], 'torque_enabled', False), 'torque_unconfirmed'),
    (lambda h: setattr(h.motors[0], 'group', 'other'), 'motor_identity'),
    (lambda h: setattr(h.motors[0], 'id', 99), 'motor_identity'),
    (lambda h: setattr(h, 'session_id', '00000000-0000-4000-8000-000000000002'), 'session_changed'),
    (lambda h: h.motors.pop(), 'joint_coverage'),
])
def test_faults_and_missing_identity_prevent_healthy_result(change, reason):
    p, r = characteristics(), request()
    m = monitor(p, r)
    h = observation(p, r, 100.)
    change(h)
    out = m.observe(h, captured_at=100., now=100., context=r['context'])
    assert out['status'] == 'hold_for_owner_review'
    assert any(reason in v for v in out['reasons'])


def test_clock_regression_gap_and_configuration_change_are_not_recoveries():
    p, r = characteristics(), request()
    m = monitor(p, r)
    observe(m, p, r, 100.)
    assert 'feedback_gap' in observe(m, p, r, 100.3)['reasons']
    m = monitor(p, r)
    observe(m, p, r, 100.1)
    assert 'source_clock_regressed' in observe(m, p, r, 100.)['reasons']
    m = monitor(p, r)
    context = dict(r['context'], calibration_revision='changed')
    out = m.observe(health(p), captured_at=100., now=100., context=context)
    assert 'configuration_changed' in out['reasons']


def test_stale_feedback_and_replayed_sample_do_not_look_healthy():
    p, r = characteristics(), request()
    m = monitor(p, r)
    assert 'stale_feedback' in observe(m, p, r, 100., age=.3)['reasons']
    m = monitor(p, r)
    observe(m, p, r, 100.)
    assert 'source_clock_regressed' in observe(m, p, r, 100.)['reasons']


def test_empty_or_terminal_source_returns_hold_without_fabricated_positions():
    from core_common.protocol.motor_health import MotorHealthResponse
    p, r = characteristics(), request()
    h = MotorHealthResponse(evidence='unavailable', status='unavailable')
    out = monitor(p, r).observe(h, captured_at=100., now=100., context=r['context'])
    assert out['status'] == 'hold_for_owner_review'
    assert out['errors_rad'] == {}
