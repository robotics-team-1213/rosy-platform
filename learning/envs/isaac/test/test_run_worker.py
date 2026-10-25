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


@pytest.mark.parametrize('evidence', ['none', 'incomplete', 'complete', 'gpu_residual', 'missing_residual'])
def test_worker_needs_report_and_cleanup_before_success(tmp_path, monkeypatch, evidence):
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
        'sdk_python': sys.executable, 'sdk_version': '5.1.0.0'})
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
        return True
    monkeypatch.setattr(mod, '_cleanup', cleanup)
    monkeypatch.setattr(mod, 'gpu_state', lambda: {'ready': evidence not in {'gpu_residual', 'missing_residual'},
                                                  'uuid': 'GPU-test', 'driver': 'test-driver'})
    def sdk(*args, **kwargs):
        if evidence not in {'none', 'missing_residual'}:
            path = kwargs['output'] / 'import-report.json'
            import_report.write_report(path, model='omx_f', frames=120, requested=120,
                articulations=['/Manipulator'], joints=sorted(model_checks.EXPECTED_JOINTS['omx_f']),
                sdk_version='5.1.0.0')
            if evidence == 'incomplete':
                value = __import__('json').loads(path.read_text())
                value['completed_frames'] = 119
                path.write_text(__import__('json').dumps(value))
        return {'exit_code': 0, 'reason': 'process_exited'}
    monkeypatch.setattr(mod, 'supervise', sdk)
    mod.execute(store, tmp_path / 'binding.json', row['run_id'])
    final = store.get(row['run_id'])
    assert final['status'] == ('SUCCEEDED' if evidence == 'complete' else
                               'UNKNOWN' if evidence in {'gpu_residual', 'missing_residual'} else 'FAILED')
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
