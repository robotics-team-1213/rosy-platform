"""A dropped observer must not replace or terminate a bounded simulation job."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools' / 'remote'))
import remote_sim_job as jobs
import remote_job


@pytest.fixture
def transport(tmp_path):
    home = tmp_path / 'home'
    name = 'sim-' + 'a' * 10 + '-123abc'
    (home / 'rosy-test' / 'runs' / name).mkdir(parents=True)
    env = {**os.environ, 'HOME': str(home)}
    calls = []

    def call(ssh, host, script, *args):
        calls.append(script)
        return subprocess.run(['bash', '-c', script, 'remote', *args],
                              capture_output=True, env=env, timeout=10)

    binding = dict(name=name, host='model.example', role='model', source_revision='a' * 40,
                   command_sha256='b' * 64, cpus=8, memory_gib=6, minutes=1)
    return home, name, binding, calls, call


def test_lost_start_reply_tracks_one_actor_and_recovers_complete_log(tmp_path, transport):
    home, name, binding, calls, actual = transport
    first = True

    def dropped_reply(ssh, host, script, *args):
        nonlocal first
        result = actual(ssh, host, script, *args)
        if script == jobs.START and first:
            first = False
            return None
        return result

    code = jobs.run('model.example', name, [name], '',
                    'printf "launch\\n" >> "$HOME/launches"; sleep 0.1; printf "complete\\n"; exit 7',
                    tmp_path / 'run.txt', binding, ssh=[], call=dropped_reply,
                    sleep=lambda _: time.sleep(.02), budget=2)
    assert code == 7
    assert (home / 'launches').read_text() == 'launch\n'
    assert (tmp_path / 'run.txt').read_bytes() == b'complete\n'
    assert calls.count(jobs.START) == 2
    meta = json.loads((tmp_path / 'remote-run.json').read_bytes())
    assert jobs.follow('model.example', name, tmp_path / 'again.txt', meta,
                       ssh=[], call=actual, sleep=lambda _: None, budget=2) == 7
    assert (tmp_path / 'again.txt').read_bytes() == b'complete\n'


def test_observer_loss_preserves_original_actor_metadata(tmp_path, transport):
    home, name, binding, calls, actual = transport

    def lost_poll(ssh, host, script, *args):
        return actual(ssh, host, script, *args) if script == jobs.START else None

    tick = iter(range(20))
    with pytest.raises(remote_job.Lost):
        jobs.run('model.example', name, [name], '', 'printf "done\\n"',
                 tmp_path / 'run.txt', binding, ssh=[], call=lost_poll,
                 sleep=lambda _: None, clock=lambda: next(tick), budget=1)
    assert (tmp_path / 'remote-run.json').exists()
    assert (home / 'rosy-test' / 'runs' / (name + '.sim-job') / 'submitted').exists()
    assert calls == [jobs.START]


def test_reused_pid_is_not_alive_and_cannot_be_cancelled(tmp_path, transport):
    home, name, binding, calls, actual = transport
    journal = home / 'rosy-test' / 'runs' / (name + '.sim-job')
    journal.mkdir()
    digest = 'c' * 64
    (journal / 'binding.sha256').write_text(digest)
    (journal / '0.pid').write_text(str(os.getpid()) + '\n')
    (journal / '0.starttime').write_text('0\n')
    (journal / '0.log').write_text('partial\n')
    result = actual([], 'model.example', jobs.POLL, name, digest, '0')
    assert remote_job.parse_poll(result.stdout) == (None, False, b'partial\n')
    assert actual([], 'model.example', jobs.KILL, name, digest).returncode != 0


@pytest.mark.parametrize('has_log', [False, True])
def test_claim_without_a_live_actor_never_starts_a_replacement(tmp_path, transport, has_log):
    home, name, binding, calls, actual = transport
    journal = home / 'rosy-test' / 'runs' / (name + '.sim-job')
    journal.mkdir()
    (journal / 'submitted').mkdir()
    if has_log:
        (journal / '0.log').write_text('')

    def attempted():
        return jobs.run('model.example', name, [name], '', 'touch "$HOME/replacement"',
                        tmp_path / 'run.txt', binding, ssh=[], call=actual,
                        sleep=lambda _: None, budget=1)

    if has_log:
        assert attempted() == remote_job.VANISHED_EXIT
    else:
        with pytest.raises(remote_job.Lost, match='identity/log mismatch'):
            attempted()
    assert not (home / 'replacement').exists()


def test_durable_observer_loss_skips_simulation_stop_and_cleanup(tmp_path, monkeypatch):
    import remote_sim
    calls = []
    monkeypatch.setattr(remote_sim.rp, 'ship', lambda *a: None)
    monkeypatch.setattr(remote_sim.rp, 'remote', lambda *a, **k: calls.append(a))

    def lost(*args, **kwargs):
        raise remote_job.Lost('observer disconnected')

    monkeypatch.setattr(jobs, 'run', lost)
    assert remote_sim.run_sim('model.example', 'model', 'true', [], 'a' * 40,
                              tmp_path, tmp_path / 'logs', 1, durable=True) == 255
    assert calls == []


def test_cancellation_records_terminal_rc_only_after_child_cleanup(transport):
    home, name, binding, calls, actual = transport
    digest = 'c' * 64
    child = r'''trap 'touch "$HOME/cleaning"; sleep .2; touch "$HOME/cleaned"' EXIT
trap 'exit 143' TERM
touch "$HOME/ready"
sleep 5
'''
    body = jobs.SUPERVISOR + '\nbash -c ' + shlex.quote(child) + '\n'
    assert actual([], 'model.example', jobs.START, name, digest, body, name).returncode == 0
    journal = home / 'rosy-test' / 'runs' / (name + '.sim-job')
    deadline = time.monotonic() + 3
    while not (home / 'ready').exists():
        assert time.monotonic() < deadline
        time.sleep(.01)
    assert actual([], 'model.example', jobs.KILL, name, digest).returncode == 0
    while not (home / 'cleaning').exists():
        assert time.monotonic() < deadline
        time.sleep(.01)
    assert not (journal / '0.rc').exists()
    while not (journal / '0.rc').exists():
        assert time.monotonic() < deadline
        time.sleep(.01)
    assert (home / 'cleaned').exists()
    assert (journal / '0.rc').read_text() == '143'
