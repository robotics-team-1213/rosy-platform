"""Durable local attempts expose interrupted/failed delivery without logging secrets."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'model'))
import deliver


ARGS = ['status', 'robot-test', '--identity', '/private/key', '--known-hosts', '/private/hosts']


def rows(root):
    files = list(root.glob('*.jsonl'))
    assert len(files) == 1
    return [json.loads(line) for line in files[0].read_text().splitlines()]


def test_unreachable_status_records_attempt_and_terminal_outcome(tmp_path):
    def runner(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 255, '', 'ssh: connect to host robot-test port 22: Connection timed out')
    out = tmp_path / 'journal'
    code = deliver.main([*ARGS, '--journal-dir', str(out)], runner=runner)
    assert code == 78
    events = rows(out)
    assert [e['event'] for e in events] == ['started', 'step_started', 'step_finished', 'finished']
    assert events[-1]['outcome'] == 'failed' and events[-1]['exit_code'] == 78
    assert len({e['attempt_id'] for e in events}) == 1
    assert '/private/key' not in json.dumps(events)


def test_journal_failure_prevents_network_calls(tmp_path):
    file = tmp_path / 'not-a-directory'
    file.write_text('preserved')
    calls = []
    assert deliver.main([*ARGS, '--journal-dir', str(file)], runner=lambda *a, **k: calls.append(a)) == 3
    assert not calls and file.read_text() == 'preserved'


def test_unexpected_runner_failure_leaves_terminal_uncertainty(tmp_path):
    def runner(*args, **kwargs):
        raise OSError('private error detail')
    out = tmp_path / 'journal'
    with pytest.raises(OSError):
        deliver.main([*ARGS, '--journal-dir', str(out)], runner=runner)
    events = rows(out)
    assert events[-1]['event'] == 'interrupted'
    assert events[-1]['outcome'] == 'unknown'
    assert 'private error detail' not in json.dumps(events)


def test_separate_attempt_files_do_not_mix_operations(tmp_path):
    out = tmp_path / 'journal'
    def runner(cmd, **kwargs): return subprocess.CompletedProcess(cmd, 0, 'secret response', '')
    for _ in range(2): assert deliver.main([*ARGS, '--journal-dir', str(out)], runner=runner) == 0
    files = list(out.glob('*.jsonl'))
    assert len(files) == 2
    for file in files:
        events = [json.loads(line) for line in file.read_text().splitlines()]
        assert events[-1]['outcome'] == 'succeeded'
        assert 'secret response' not in file.read_text()


def test_timeout_after_rollback_invocation_keeps_remote_outcome_unknown(tmp_path):
    out = tmp_path / 'journal'
    def runner(command, **kwargs): raise subprocess.TimeoutExpired(command, kwargs['timeout'])
    args = ['rollback', *ARGS[1:], '--journal-dir', str(out)]
    assert deliver.main(args, runner=runner) == 78
    final = rows(out)[-1]
    assert final['outcome'] == 'unknown'
    assert final['command_outcome'] == 'failed'


def test_push_records_transfer_and_pointer_steps_then_rollback(tmp_path):
    from test_model_deliver import FakeRunner, _model, SSH
    models = tmp_path / 'models'
    revision = _model(models, 'pass')
    out = tmp_path / 'journal'
    assert deliver.main(['push', 'robot-test', revision, '--models', str(models),
                         *SSH, '--journal-dir', str(out)], runner=FakeRunner()) == 0
    events = rows(out)
    assert [e['phase'] for e in events if e['event'] == 'step_started'] == ['prepare', 'transfer', 'push']
    assert events[-1]['outcome'] == 'succeeded'
    assert events[-1]['device_acceptance_verified'] is False
    assert deliver.main(['rollback', 'robot-test', *SSH, '--journal-dir', str(out)], runner=FakeRunner()) == 0
    assert len(list(out.glob('*.jsonl'))) == 2
