"""Observe successful host writes outside submission locks; no physical ACK claim."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3
from types import SimpleNamespace

import pytest

from core.bridge import cmd_vel as cycle
from core_features.command.bounded_trial import BoundedTrial, Bounds


@pytest.fixture
def trial(tmp_path):
    bounds = Bounds(.05, .5, .1, .1, .1, .2, .01, 1.1, 5., 'a' * 64)
    owner = BoundedTrial(tmp_path / 'trial.sqlite', trial_id='one', robot_id='synthetic',
                         boot_id='boot', frame_id='odom', bounds=bounds, now=10.)
    owner.observe(x=0., y=0., stamp_ns=1000000000, source_now_ns=1000000000,
                  frame_id='odom', now=10.)
    yield owner
    owner.close()


def run(*, send=None, observe=None, select=None, **kwargs):
    log = []
    selected = cycle.Twist(.04, -.1)
    command = SimpleNamespace(select_output=select or (lambda: selected),
                              announce_pending=lambda: log.append(('announce',)))
    power = SimpleNamespace(on_activity=lambda source: log.append(('activity', source)))

    def write(out):
        log.append(('write', out.linear, out.angular))
        if send is not None:
            send(out)

    def notify(out):
        log.append(('observe', out.linear, out.angular))
        if observe is not None:
            observe(out)

    cycle.cmd_vel_cycle(command, power, write, notify_written=notify,
                        warn=lambda msg: log.append(('warn', msg)), **kwargs)
    return log


def test_observation_precedes_power_and_announcements_but_follows_actual_write():
    assert run() == [('write', .04, -.1), ('observe', .04, -.1),
                     ('activity', 'cmd_vel'), ('announce',)]


@pytest.mark.parametrize('hold', ['hardware', 'devices', 'zero'])
def test_observation_uses_actual_zero_after_hold_or_zero_selection(hold):
    kwargs = dict(readiness=SimpleNamespace(is_ready=lambda: False)) if hold == 'hardware' else (
        dict(motion_ready=lambda: False) if hold == 'devices' else
        dict(select=lambda: cycle.Twist()))
    assert run(**kwargs) == [('write', 0., 0.), ('observe', 0., 0.), ('announce',)]


@pytest.mark.parametrize('fault', ['selection', 'binding', 'expired'])
def test_early_failure_notifies_only_successful_fallback_before_warning(monkeypatch, fault):
    kwargs = {}
    if fault == 'selection':
        def fail():
            raise ValueError('selection failed')
        kwargs['select'] = fail
    elif fault == 'binding':
        monkeypatch.setattr(cycle.PinkyTwistPort, '_bind',
                            lambda *_: (_ for _ in ()).throw(ValueError('binding failed')))
    else:
        bind = cycle.PinkyTwistPort._bind

        def expire(port, guarded):
            port._clock = lambda: 10.
            bind(port, guarded)
            port._clock = lambda: 10. + cycle.GUARD_LIFETIME_S
        monkeypatch.setattr(cycle.PinkyTwistPort, '_bind', expire)
    log = run(**kwargs)
    assert log[:2] == [('write', 0., 0.), ('observe', 0., 0.)]
    assert [entry[0] for entry in log] == ['write', 'observe', 'warn']


def test_trial_denial_notifies_only_zero(trial):
    trial.stop('independent stop')
    assert run(trial_guard=trial, now=10.) == [('write', 0., 0.), ('observe', 0., 0.)]


@pytest.mark.parametrize('zero_fails', [False, True])
def test_unknown_delivery_never_notifies_nonzero_or_retries_it(trial, zero_fails):
    def fail(out):
        if out.linear or zero_fails:
            raise RuntimeError('delivery unknown')
    log = run(send=fail, trial_guard=trial, now=10.)
    assert [entry for entry in log if entry[0] == 'write'] == [
        ('write', .04, -.1), ('write', 0., 0.)]
    assert [entry for entry in log if entry[0] == 'observe'] == (
        [] if zero_fails else [('observe', 0., 0.)])
    assert trial.status()['halted'] is True
    assert not [entry for entry in log if entry[0] in ('activity', 'announce')]


def test_observer_failure_does_not_consume_trial_or_retry_successful_motion(trial):
    def fail(_):
        raise RuntimeError('observer failure')
    log = run(observe=fail, trial_guard=trial, now=10.)
    assert [entry for entry in log if entry[0] == 'write'] == [('write', .04, -.1)]
    assert [entry[0] for entry in log] == ['write', 'observe', 'warn', 'activity', 'announce']
    assert trial.status()['halted'] is False


def test_observation_uses_bound_payload_when_selection_changes_during_send():
    selected = cycle.Twist(.04, -.1)

    def mutate(_):
        selected.linear, selected.angular = 3., 2.
    log = run(select=lambda: selected, send=mutate)
    assert log[:2] == [('write', .04, -.1), ('observe', .04, -.1)]


@pytest.mark.parametrize('denied', [False, True])
def test_observation_runs_after_port_close_and_trial_transaction_release(
        trial, tmp_path, monkeypatch, denied):
    ports = []
    bind = cycle.PinkyTwistPort._bind

    def capture(port, guarded):
        ports.append(port)
        bind(port, guarded)
    monkeypatch.setattr(cycle.PinkyTwistPort, '_bind', capture)
    if denied:
        trial.stop('independent stop')

    def inspect(_):
        port = ports[0]
        assert port.state().state == 'disabled'

        def other_thread():
            for lock in (port._lock, trial._lock):
                assert lock.acquire(blocking=False)
                lock.release()
            with sqlite3.connect(tmp_path / 'trial.sqlite', timeout=0.) as db:
                db.execute('BEGIN IMMEDIATE')
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(other_thread).result(timeout=2.)
    # Raise outside the observer as well: isolation must not hide failed assertions.
    errors = []

    def record(out):
        try:
            inspect(out)
        except Exception as exc:
            errors.append(exc)
    log = run(observe=record, trial_guard=trial, now=10.)
    assert not errors
    assert len([entry for entry in log if entry[0] == 'observe']) == 1


def test_unfenced_publish_exception_has_no_success_observation():
    observed = []

    def fail(_):
        raise RuntimeError('publish failed')
    with pytest.raises(RuntimeError, match='publish failed'):
        run(send=fail, observe=observed.append)
    assert observed == []
