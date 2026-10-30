"""Request replay and unit ownership survive request-process restarts."""
import importlib
from pathlib import Path
import sys
import uuid

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHA = 'a' * 40


def module():
    assert (ROOT / 'run_control.py').is_file(), 'Bounded Isaac Runner is missing'
    sys.path.insert(0, str(ROOT))
    return importlib.import_module('run_control')


class System:
    def __init__(self):
        self.launches, self.stop_calls = [], []
        self.owner = {'invocation_id': 'b' * 32, 'boot_id': 'boot',
                      'cgroup': '/user.slice/own.service', 'active': True}
        self.error = False

    def check(self, binding):
        return {'ready': True, 'sdk_version': '5.1.0.0'}

    def launch(self, unit, binding_file, run_id):
        self.launches.append(run_id)
        if self.error:
            raise OSError('lost launch response')

    def observe(self, unit):
        return dict(self.owner, unit=unit)

    def stop(self, owner):
        self.stop_calls.append(owner)
        self.owner['active'] = False


@pytest.fixture
def setup(tmp_path, monkeypatch):
    mod = module()
    monkeypatch.setattr(mod, 'load_binding', lambda path, sha=None: {'source_sha': SHA})
    store = mod.RunStore(tmp_path / 'runs')
    system = System()
    runner = mod.Runner(store, tmp_path / 'binding.json', system=system)
    request = {'request_id': uuid.uuid4().hex, 'scenario_id': 'omx-f-import',
               'config': {'seed': 0}, 'source_sha': SHA,
               'expected_input_sha256': mod.input_snapshot('omx-f-import', {'seed': 0}, SHA)['input_sha256']}
    return mod, runner, system, request


def test_duplicate_start_and_restarted_request_process_never_launch_twice(setup):
    mod, runner, system, request = setup
    first = runner.start(request)
    second = mod.Runner(runner.store, runner.binding_file, system=system).start(request)
    assert first['run_id'] == second['run_id']
    assert system.launches == [first['run_id']]


def test_lost_launch_response_stays_observable_without_retry(setup):
    _, runner, system, request = setup
    system.error = True
    first = runner.start(request)
    assert first['status'] == 'UNKNOWN'
    assert runner.start(request)['run_id'] == first['run_id']
    assert len(system.launches) == 1


def test_changed_input_and_unchecked_fingerprint_refuse_launch(setup):
    _, runner, system, request = setup
    for changes in [{'expected_input_sha256': '0' * 64}, {'source_sha': 'HEAD'}, {'cmd': 'anything'}]:
        with pytest.raises(ValueError):
            runner.start(dict(request, **changes))
    assert system.launches == []


def test_check_returns_readiness_refusal_without_losing_input_fingerprint(setup):
    _, runner, system, request = setup
    def busy(binding):
        raise ValueError('GPU owner is active')
    system.check = busy
    checked = runner.check(request['scenario_id'], request['config'], SHA)
    assert checked['ready'] is False
    assert checked['input_sha256'] == request['expected_input_sha256']
    assert checked['reason']
    assert system.launches == []


def running(setup):
    _, runner, system, request = setup
    row = runner.start(request)
    owner = system.observe('rosy-isaac-' + row['run_id'] + '.service')
    row = runner.store.update(row['run_id'], row['revision'], {'status': 'RUNNING', 'runtime': owner})
    return runner, system, row


def test_stop_stale_receipt_never_targets_new_invocation(setup):
    runner, system, row = running(setup)
    system.owner['invocation_id'] = 'c' * 32
    with pytest.raises(ValueError):
        runner.stop(row['run_id'], row['revision'])
    assert system.stop_calls == []


def test_stop_requires_current_revision_and_preserves_failed_stop(setup):
    runner, system, row = running(setup)
    with pytest.raises(ValueError):
        runner.stop(row['run_id'], row['revision'] - 1)
    assert system.stop_calls == []
    def failed(owner):
        raise OSError('stop failed')
    system.stop = failed
    stopped = runner.stop(row['run_id'], row['revision'])
    assert stopped['status'] == 'UNKNOWN'
    assert 'stop' in stopped['error']


def test_unit_loss_after_restart_is_unknown_and_never_restarted(setup):
    runner, system, row = running(setup)
    system.owner['active'] = False
    assert runner.status(row['run_id'])['status'] == 'UNKNOWN'
    assert len(system.launches) == 1


def test_listing_keeps_corrupt_run_placeholder_and_healthy_run(setup):
    _, runner, _, request = setup
    row = runner.start(request)
    broken = runner.store.root / 'runs' / ('f' * 32)
    broken.mkdir()
    (broken / 'state.json').write_text('broken')
    rows = runner.list()
    assert any(item['run_id'] == row['run_id'] for item in rows)
    assert any(item['run_id'] == 'f' * 32 and item['status'] == 'UNKNOWN' for item in rows)


@pytest.mark.parametrize('sdk_version', ['5.1.0.0', '6.0.0.0', '6.2.0.0'])
def test_binding_accepts_root_owned_interpreter_and_excludes_managed_data(tmp_path, monkeypatch, sdk_version):
    module()
    import hashlib
    import json
    import run_binding
    from types import SimpleNamespace
    source = tmp_path / 'source'
    source.mkdir()
    monkeypatch.setattr(run_binding, '__file__', str(source / 'learning/envs/isaac/run_binding.py'))
    monkeypatch.setattr(run_binding.subprocess, 'run', lambda argv, **kw:
                         SimpleNamespace(stdout=SHA if 'rev-parse' in argv else ''))
    owner = tmp_path / 'managed'
    owner.mkdir()
    data = tmp_path / 'data'
    data.mkdir()
    venv = tmp_path / 'venv/bin'
    venv.mkdir(parents=True)
    python = venv / 'python'
    python.symlink_to('/usr/bin/python3')
    import os
    binding = {'uid': os.getuid(), 'source_root': str(source), 'source_sha': SHA,
               'sdk_python': str(python), 'sdk_python_sha256': hashlib.sha256(python.read_bytes()).hexdigest(),
               'sdk_version': sdk_version, 'model_code_root': str(owner), 'data_root': str(data)}
    path = tmp_path / 'binding.json'
    path.write_text(json.dumps(binding))
    assert run_binding.load_binding(path)['sdk_python'] == str(python)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert run_binding.load_binding(path, expected_digest=digest)['data_root'] == str(data)
    for unsupported in ('6.2.0.1', '6.3.0.0', '6.2.0.0+rosy.1'):
        path.write_text(json.dumps(dict(binding, sdk_version=unsupported)))
        with pytest.raises(ValueError, match='Unapproved SDK'):
            run_binding.load_binding(path)
    replacement = tmp_path / 'other-data'
    replacement.mkdir()
    path.write_text(json.dumps(dict(binding, data_root=str(replacement))))
    with pytest.raises(ValueError):
        run_binding.load_binding(path, expected_digest=digest)
    nested = owner / 'releases/runs'
    nested.mkdir(parents=True)
    path.write_text(json.dumps(dict(binding, data_root=str(nested))))
    with pytest.raises(ValueError):
        run_binding.load_binding(path)


def test_system_stop_pins_worker_instead_of_signalling_reused_unit(monkeypatch):
    module()
    import run_system
    owner = {'unit': 'rosy-isaac-' + 'a' * 32 + '.service', 'invocation_id': 'b' * 32,
             'boot_id': 'boot', 'cgroup': '/owned', 'main_pid': 1234, 'pid_start': '42', 'uid': 1000}
    calls = []
    monkeypatch.setattr(run_system.System, 'observe', lambda self, unit: dict(owner))
    monkeypatch.setattr(run_system, '_identity', lambda pid: {'pid_start': '42', 'uid': 1000, 'cgroup': '/owned'})
    monkeypatch.setattr(run_system.os, 'pidfd_open', lambda pid: calls.append(('open', pid)) or 99)
    monkeypatch.setattr(run_system.os, 'close', lambda fd: calls.append(('close', fd)))
    monkeypatch.setattr(run_system.signal, 'pidfd_send_signal', lambda fd, sig: calls.append(('signal', fd, sig)))
    monkeypatch.setattr(run_system.subprocess, 'run', lambda *a, **k: pytest.fail('unit-name signal is forbidden'))
    run_system.System().stop(owner)
    assert calls[0] == ('open', 1234)
    assert calls[1][0:2] == ('signal', 99)
    assert calls[-1] == ('close', 99)


@pytest.mark.parametrize('missing', [None, 'ffmpeg', 'ffprobe'])
def test_container_check_refuses_before_launch_without_recording_tools(setup, monkeypatch, missing):
    mod, runner, system, _ = setup
    monkeypatch.setattr(mod.shutil, 'which', lambda tool: None if tool == missing else '/usr/bin/'+tool)
    config = {'seed': 42, 'layers': 3, 'case': 'nominal'}
    checked = runner.check('omx-map-container-stack', config, SHA)
    assert checked['ready'] is (missing is None)
    if missing:
        assert 'ffmpeg' in checked['reason'] and '--approve sim' in checked['reason']
    # Scenarios without continuous film do not need the tools.
    assert runner.check('omx-f-import', {'seed': 0}, SHA)['ready'] is True
