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
