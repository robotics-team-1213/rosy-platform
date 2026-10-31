"""Real child execution is bounded independently of SDK availability."""
import importlib
from pathlib import Path
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module():
    assert (ROOT / 'run_worker.py').is_file(), 'Bounded SDK worker is missing'
    sys.path.insert(0, str(ROOT))
    return importlib.import_module('run_worker')


def run(tmp_path, code, **kwargs):
    return module().supervise([sys.executable, '-c', code], cwd=tmp_path, env=None,
        descriptors=(), output=tmp_path, stop_requested=lambda: False, **kwargs)


def test_process_exit_does_not_claim_import_success(tmp_path):
    row = run(tmp_path, "print('finished')", timeout=2)
    assert row['exit_code'] == 0
    assert 'import_verified' not in row
    assert (tmp_path / 'sdk.log').read_text().strip() == 'finished'


def test_timeout_and_stop_reap_the_owned_child(tmp_path):
    start = time.monotonic()
    row = run(tmp_path, 'import time; time.sleep(20)', timeout=0.1)
    assert row['reason'] == 'runtime_limit'
    assert row['exit_code'] != 0
    assert time.monotonic() - start < 4
    other = tmp_path / 'stop'
    other.mkdir()
    row = module().supervise([sys.executable, '-c', 'import time;time.sleep(20)'], cwd=other,
        env=None, descriptors=(), output=other, timeout=5, stop_requested=lambda: True)
    assert row['reason'] == 'stop_requested'


def test_output_limit_and_linked_outputs_refuse_success(tmp_path):
    row = run(tmp_path, "print('x'*100000)", timeout=2, log_limit=1024)
    assert row['reason'] == 'output_limit'
    assert (tmp_path / 'sdk.log').stat().st_size <= 1024
    bad = tmp_path / 'linked'
    bad.mkdir()
    row = run(bad, "from pathlib import Path;Path('leak').symlink_to('/etc/passwd')", timeout=2)
    assert row['reason'] == 'unsafe_output'


def test_disk_preflight_keeps_output_budget_in_addition_to_reserve(tmp_path, monkeypatch):
    import shutil
    from types import SimpleNamespace
    monkeypatch.setattr(shutil, 'disk_usage', lambda path: SimpleNamespace(free=1024 ** 3))
    row = run(tmp_path, "from pathlib import Path;Path('launched').write_text('unexpected')")
    assert row['reason'] == 'insufficient_space' and row['exit_code'] is None
    assert not (tmp_path / 'launched').exists()


def test_disk_pressure_reaps_only_the_owned_child(tmp_path, monkeypatch):
    import shutil
    from types import SimpleNamespace
    measured = []
    def available(path):
        measured.append(path)
        return SimpleNamespace(free=2 * 1024 ** 3 if len(measured) == 1 else 0)
    monkeypatch.setattr(shutil, 'disk_usage', available)
    row = run(tmp_path, 'import time; time.sleep(20)', timeout=.2)
    assert row['reason'] == 'insufficient_space' and row['exit_code'] != 0


@pytest.mark.parametrize('kind', ['file', 'directory'])
def test_output_budget_tolerates_entries_removed_after_enumeration(tmp_path, monkeypatch, kind):
    mod = module()
    path = tmp_path / 'temporary-output'
    path.write_bytes(b'temporary') if kind == 'file' else path.mkdir()
    real_walk = mod.os.walk
    def disappearing_walk(*args, **kwargs):
        for base, dirs, files in real_walk(*args, **kwargs):
            if path.name in dirs + files:
                path.unlink() if kind == 'file' else path.rmdir()
            yield base, dirs, files
    monkeypatch.setattr(mod.os, 'walk', disappearing_walk)
    assert mod._budget(tmp_path) is None
    assert not path.exists()


@pytest.mark.parametrize('kind,expected', [('symlink', 'unsafe_output'), ('oversize', 'output_limit')])
def test_output_budget_still_rejects_unsafe_or_oversized_entries(tmp_path, kind, expected):
    path = tmp_path / 'output'
    if kind == 'symlink':
        path.symlink_to(tmp_path / 'missing-target')
    else:
        with path.open('wb') as stream:
            stream.truncate(128 * 1024 * 1024 + 1)
    assert module()._budget(tmp_path) == expected


def test_output_budget_does_not_hide_missing_root_or_other_stat_errors(tmp_path, monkeypatch):
    mod = module()
    with pytest.raises(FileNotFoundError):
        mod._budget(tmp_path / 'missing-root')
    path = tmp_path / 'unreadable-output'
    path.write_bytes(b'present')
    original = Path.lstat
    def unreadable(entry, *args, **kwargs):
        if entry == path:
            raise PermissionError('cannot inspect output')
        return original(entry, *args, **kwargs)
    monkeypatch.setattr(Path, 'lstat', unreadable)
    with pytest.raises(PermissionError):
        mod._budget(tmp_path)


@pytest.mark.parametrize('sdk_version', ['5.1.0.0', '6.2.0.0'])
@pytest.mark.parametrize('evidence', ['none', 'incomplete', 'complete', 'gpu_residual', 'missing_residual', 'cleanup_failed', 'gpu_delayed', 'gpu_probe_overrun', 'exception'])
def test_worker_needs_report_and_cleanup_before_success(tmp_path, monkeypatch, evidence, sdk_version):
    from contextlib import nullcontext
    import os
    import uuid
    mod = module()
    import run_store
    import import_report
    import model_checks
    store = run_store.RunStore(tmp_path / 'records')
    row = store.create(uuid.uuid4().hex, 'omx-f-import', {'seed': 0}, 'a' * 40)
    row = store.update(row['run_id'], 0, {'phase': 'LAUNCH_RESERVED'})
    owner = {'main_pid': os.getpid(), 'invocation_id': 'b' * 32, 'cgroup': '/owned'}
    monkeypatch.setenv('INVOCATION_ID', 'b' * 32)
    monkeypatch.setattr(mod.System, 'observe', lambda self, unit: dict(owner, unit=unit))
    monkeypatch.setattr(mod, 'load_binding', lambda *args: {'source_sha': 'a' * 40,
        'sdk_python': sys.executable, 'sdk_version': sdk_version})
    monkeypatch.setattr(mod, 'sdk_check', lambda binding: {'ready': True, 'uuid': 'GPU-test', 'driver': 'test-driver'})
    from contextlib import contextmanager
    held = [False]
    @contextmanager
    def lease(binding):
        held[0] = True
        try:
            yield ()
        finally:
            held[0] = False
    monkeypatch.setattr(mod, 'acquire', lease)
    def cleanup(owner):
        assert held[0], 'cleanup must precede lease release even after report failure'
        return evidence != 'cleanup_failed'
    monkeypatch.setattr(mod, '_cleanup', cleanup)
    from types import SimpleNamespace
    clock, probes = [0.], []
    def sleep(seconds):
        clock[0] = round(clock[0] + seconds, 6)
    monkeypatch.setattr(mod, 'time', SimpleNamespace(monotonic=lambda: clock[0], sleep=sleep))
    def gpu_state():
        probes.append(clock[0])
        if evidence == 'gpu_probe_overrun' and clock[0] >= 14.8:
            clock[0] += 2.
        ready = (clock[0] >= 4. if evidence == 'gpu_delayed' else
                 evidence not in {'gpu_residual', 'missing_residual', 'gpu_probe_overrun'})
        return {'ready': ready, 'uuid': 'GPU-test', 'driver': 'test-driver'}
    monkeypatch.setattr(mod, 'gpu_state', gpu_state)
    def sdk(*args, **kwargs):
        assert kwargs['env'].get('OMNI_KIT_ACCEPT_EULA') == 'YES'
        assert kwargs['env'].get('ACCEPT_EULA') == 'Y'
        if evidence == 'exception':
            raise FileNotFoundError('temporary SDK output disappeared')
        if evidence not in {'none', 'missing_residual'}:
            path = kwargs['output'] / 'import-report.json'
            import_report.write_report(path, model='omx_f', frames=120, requested=120,
                articulations=['/Manipulator'], joints=sorted(model_checks.EXPECTED_JOINTS['omx_f']),
                sdk_version=sdk_version)
            if evidence == 'incomplete':
                value = __import__('json').loads(path.read_text())
                value['completed_frames'] = 119
                path.write_text(__import__('json').dumps(value))
        return {'exit_code': 0, 'reason': 'process_exited'}
    monkeypatch.setattr(mod, 'supervise', sdk)
    mod.execute(store, tmp_path / 'binding.json', row['run_id'])
    if evidence == 'gpu_delayed':
        assert clock[0] == 4. and 3. in probes
    elif evidence in {'gpu_residual', 'missing_residual', 'gpu_probe_overrun'}:
        assert clock[0] == (16.8 if evidence == 'gpu_probe_overrun' else 15.)
        assert probes[-1] == 14.8 and all(stamp < 15. for stamp in probes)
    elif evidence == 'cleanup_failed':
        assert clock[0] == 0. and probes == [0.]
    final = store.get(row['run_id'])
    if evidence == 'exception':
        assert final['result']['error_type'] == 'FileNotFoundError'
    assert final['status'] == ('SUCCEEDED' if evidence in {'complete', 'gpu_delayed'} else
                               'UNKNOWN' if evidence in {'gpu_residual', 'missing_residual', 'cleanup_failed', 'gpu_probe_overrun'} else 'FAILED')
    if final['status'] == 'UNKNOWN':
        from run_control import Runner
        from types import SimpleNamespace
        expected = {'owned_processes_exited': evidence != 'cleanup_failed',
                    'gpu': {'ready': evidence == 'cleanup_failed', 'uuid': 'GPU-test', 'driver': 'test-driver'}}
        assert final['cleanup'] == 'UNCONFIRMED'
        assert final['runtime']['cleanup_observation'] == expected
        assert all(final['runtime'][key] == value for key, value in owner.items())
        assert final['runtime']['gpu']['uuid'] == 'GPU-test'
        unit = 'rosy-isaac-' + row['run_id'] + '.service'
        assert final['runtime']['unit'] == unit
        runner = Runner(store, tmp_path / 'binding.json',
                        system=SimpleNamespace(observe=lambda unit: {'active': False}))
        observed = runner.status(row['run_id'])
        assert observed['status'] == 'UNKNOWN'
        assert observed['error'] == 'unit is inactive; cleanup and result unconfirmed'
        assert observed['runtime'] == final['runtime']
    if final['status'] == 'SUCCEEDED':
        assert final['result']['task_success'] is None
        assert store.artifact(row['run_id'], 'import-report')['bytes'] > 0
        assert final['result']['gpu']['uuid'] == 'GPU-test'


def test_a_finished_arm_s_run_is_recorded_from_its_own_report():
    """2026-10-26: the arm S report has no completed_frames; the KeyError left every finished run UNKNOWN."""
    mod = module()
    done = []

    class Store:
        def get(self, run_id):
            return {'input': {'scenario_id': 'arm-s-cell-case'}, 'revision': 3, 'status': 'RUNNING'}

        def finish(self, run_id, revision, result, artifacts):
            done.append(result)

    report = {'task_success': True, 'judgement': {'result': 'frame_contact', 'matches_expectation': True}}
    assert mod._finish(Store(), 'r', {'reason': 'process_exited'}, report, [], False) == 0
    assert done[0]['status'] == 'SUCCEEDED' and done[0]['evidence_class'] == 'ARM_S_CELL_FRAME_CONTACT'
    assert done[0]['completed_frames'] is None and done[0]['stage'] == 'arm_s_cell'


@pytest.mark.parametrize('scenario,scene_scope,expected_scope', [
    ('omx-map-container-stack', 'STEP_MM_TO_SIM_Z_X_Y_WITH_TRANSLATION',
     'STEP_MM_TO_SIM_Z_X_Y_WITH_TRANSLATION'),
    ('omx-map-container-stack', 'ANOTHER_IMMUTABLE_SCENE_SCOPE', 'ANOTHER_IMMUTABLE_SCENE_SCOPE'),
    ('omx-map-cube-stack', 'UNUSED_SCENE_SCOPE', 'CONFLUENCE_CAD_WITH_NOMINAL_PHOTO_CELL'),
    ('omx-map-long-stack', 'UNUSED_SCENE_SCOPE', 'CONFLUENCE_CAD_WITH_NOMINAL_PHOTO_CELL'),
])
@pytest.mark.parametrize('task_success', [True, False, None])
def test_mapped_result_uses_container_input_coordinate_scope(scenario, scene_scope, expected_scope, task_success):
    done = []
    class Store:
        def get(self, run_id):
            return {'input': {'scenario_id': scenario, 'scene': {'coordinate_scope': scene_scope}},
                    'revision': 3, 'status': 'RUNNING'}
        def finish(self, run_id, revision, result, artifacts):
            done.append(result)
    report = ({'task_success': task_success, 'trials': [{'task_success': task_success}]}
              if task_success is not None else None)
    code = module()._finish(Store(), 'r', {'reason': 'process_exited'}, report, [], False)
    assert code == (0 if task_success is True else 1)
    assert done[0]['coordinate_scope'] == expected_scope
    assert done[0]['status'] == ('SUCCEEDED' if task_success is True else 'FAILED')


@pytest.mark.parametrize('kind', ['symlink', 'hardlink'])
def test_unsafe_output_names_the_entry_for_the_sdk_log(tmp_path, kind):
    # Run a4e9 stopped on a transient unsafe entry that was gone before anyone could see it.
    path = tmp_path / 'output'
    if kind == 'symlink':
        path.symlink_to(tmp_path / 'missing-target')
    else:
        path.write_bytes(b'x')
        (tmp_path / 'second').hardlink_to(path)
    found = []
    assert module()._budget(tmp_path, found) == 'unsafe_output'
    assert len(found) == 1 and found[0].startswith(('output ', 'second ')) and ('nlink 2' in found[0] or 'mode 0o12' in found[0])
