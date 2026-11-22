"""U2 (2026-11-21): a recording child that ended non-zero is "stopped, safe end proven" only when session.json says so."""
import json

import pytest

from test_omx_bench_record import _setup, finished
import omx_incident_fleet

# the fields record_session.Session.finish writes at the end of a session whose arm ended safely
GOOD = {'exit_code': 1, 'safe_end': True, 'torque_off_confirmed': True, 'caps_restored': True,
        'hardware_faults': [], 'manual_attention_required': False}
CAUSE = 'RuntimeError: guard stop: stale control loop'


def _exit(bench, code, drop_session=False):
    """The record_session child exits with `code`, after writing its log line (and session.json, unless dropped)."""
    real = bench.popen

    def popen(command, cwd, **kwargs):
        child = real(command, cwd, **kwargs)
        if command[1].endswith('record_session.py'):
            kwargs['stdout'].write(('episode 0 saved\n' + CAUSE + '\n').encode())
            kwargs['stdout'].flush()
            if drop_session:
                (cwd / 'session.json').unlink()
            child.wait = lambda timeout=None: code
        return child
    bench.popen = popen


def test_nonzero_exit_with_proven_safe_end_is_stopped_safe_and_not_sealed(tmp_path, monkeypatch):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch, record=GOOD)
    _exit(bench, 1)
    bench.start(body)
    state = finished(bench)
    assert state['status'] == 'stopped_safe' and state['unconfirmed'] == [] and state['stop_cause'] == CAUSE
    assert len(commands) == 1  # no record_seal
    assert len([c for c in calls if c[0] == 'start']) == 3  # units restored


@pytest.mark.parametrize('change', [{'safe_end': False}, {'torque_off_confirmed': False}, {'torque_off_confirmed': None},
                                    {'caps_restored': ['follower elbow_flex: no reply']}, {'manual_attention_required': True},
                                    {'hardware_faults': ['elbow_flex overload']}, {'runner_held': {'runner_pid': 1}},
                                    {'interrupted': True}])
def test_unproven_safe_end_stays_unsafe_with_items(tmp_path, monkeypatch, change):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch, record=dict(GOOD, **change))
    _exit(bench, 1)
    bench.start(body)
    state = finished(bench)
    if change.get('interrupted'):  # existing path: raw recording kept, not an unsafe verdict
        assert state['status'] == 'stopped_not_sealed'
    else:
        assert state['status'] == 'unsafe_or_failed' and state['unconfirmed']


def test_missing_session_json_and_missing_fields_stay_unsafe(tmp_path, monkeypatch):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch, record=GOOD)
    _exit(bench, 1, drop_session=True)
    bench.start(body)
    state = finished(bench)
    assert state['status'] == 'unsafe_or_failed' and state['unconfirmed'] == ['session.json 없음 또는 읽을 수 없음']
    bench2, body2, _, _ = _setup(tmp_path / 'two', monkeypatch, record={'safe_end': True})  # an older/partial record proves nothing
    _exit(bench2, 1)
    bench2.start(body2)
    assert finished(bench2)['status'] == 'unsafe_or_failed'


def test_open_arm_incident_keeps_unsafe_and_status_rejudges_an_old_unsafe_state(tmp_path, monkeypatch):
    bench, body, calls, commands = _setup(tmp_path, monkeypatch, record=GOOD)
    omx_incident_fleet.keep_hold('arm_a', 'elbow overload latched')
    _exit(bench, 1)
    bench.start(body)
    state = finished(bench)
    assert state['status'] == 'unsafe_or_failed' and any('arm_a 사고 열림' in x for x in state['unconfirmed'])
    omx_incident_fleet.hold_path('arm_a').unlink()  # the incident is cleared in Fleet: the next poll resolves it, no restart
    state = bench.status()
    assert state['status'] == 'stopped_safe' and state['unconfirmed'] == []
