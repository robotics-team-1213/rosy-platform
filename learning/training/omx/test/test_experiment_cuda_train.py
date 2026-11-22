"""CUDA OMX preflight, immediate worker crash propagation, and bounded bundle manifest tests."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from types import SimpleNamespace
import uuid

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import experiment_center  # noqa: E402
import experiment_cuda_train as cuda  # noqa: E402
import experiment_jobs  # noqa: E402
from experiment_io import write_json  # noqa: E402


def _make_dataset(root: Path, *, episodes=2, frames=20):
    (root / 'meta').mkdir(parents=True, exist_ok=True)
    write_json(root / 'meta' / 'info.json', {'total_episodes': episodes, 'total_frames': frames})
    return root


def _make_center(tmp_path, monkeypatch, *, cuda_available=True):
    monkeypatch.setattr(experiment_center.os, 'name', 'posix')
    monkeypatch.setattr(
        experiment_center.subprocess, 'run',
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=b'True\n' if cuda_available else b'False\n'),
    )
    return experiment_center.Center({
        'schema': 'rosy.omx.center-config/1',
        'root': str(tmp_path / 'center'),
        'python': {'act': sys.executable, 'hilserl': sys.executable},
    })


def _valid_body(dataset_root: Path, output_dir: Path, **overrides):
    body = {
        'request_id': str(uuid.uuid4()),
        'dataset_root': str(dataset_root),
        'arm_id': 'arm_b',
        'steps': 100,
        'batch_size': 8,
        'seed': 42,
        'output_dir': str(output_dir),
    }
    body.update(overrides)
    return body


def test_preflight_refuses_existing_output_dir_when_resume_false(tmp_path):
    ds = _make_dataset(tmp_path / 'ds')
    out = tmp_path / 'train-existing'
    out.mkdir()
    spec = cuda.check_cuda_request(_valid_body(ds, out, resume=False), tmp_path / 'center')
    with pytest.raises(ValueError, match='output_dir already exists'):
        cuda.preflight_cuda(spec, out, jobs_dir=tmp_path / 'jobs', check_gpu=False)


def test_preflight_resume_requires_and_accepts_train_config(tmp_path):
    ds = _make_dataset(tmp_path / 'ds')
    out = tmp_path / 'train-resume'
    out.mkdir()
    spec = cuda.check_cuda_request(_valid_body(ds, out, resume=True), tmp_path / 'center')
    with pytest.raises(ValueError, match='train_config.json'):
        cuda.preflight_cuda(spec, out, jobs_dir=tmp_path / 'jobs', check_gpu=False)
    cfg_dir = out / 'checkpoints' / 'last' / 'pretrained_model'
    cfg_dir.mkdir(parents=True)
    (cfg_dir / 'train_config.json').write_text('{}', encoding='utf-8')
    summary = cuda.preflight_cuda(spec, out, jobs_dir=tmp_path / 'jobs', check_gpu=False)
    assert summary['total_episodes'] == 2 and summary['total_frames'] == 20


def test_preflight_checks_data_gate_receipt_and_job_locks(tmp_path, monkeypatch):
    ds = _make_dataset(tmp_path / 'ds')
    out = tmp_path / 'train-new'
    gate = ds / 'gate-receipt.json'
    write_json(gate, {'counts': {'accept': 2, 'reject': 1, 'review': 0}})
    spec = cuda.check_cuda_request(_valid_body(ds, out), tmp_path / 'center')
    with pytest.raises(ValueError, match='unaccepted'):
        cuda.preflight_cuda(spec, out, jobs_dir=tmp_path / 'jobs', check_gpu=False)

    write_json(gate, {'counts': {'accept': 2, 'reject': 0, 'review': 0}})
    jobs = tmp_path / 'jobs'
    jobs.mkdir()
    dead_lock = jobs / 'train-999999.lock'
    dead_lock.write_text('999999\n', encoding='utf-8')
    monkeypatch.setattr(cuda, '_pid_alive', lambda pid: pid == os.getpid())
    summary = cuda.preflight_cuda(spec, out, jobs_dir=jobs, check_gpu=False)
    assert summary['stale_locks'] == ['train-999999.lock']

    live_lock = jobs / f'train-{os.getpid()}.lock'
    live_lock.write_text(f'{os.getpid()}\n', encoding='utf-8')
    with pytest.raises(ValueError, match='active GPU training lock'):
        cuda.preflight_cuda(spec, out, jobs_dir=jobs, check_gpu=False)


def test_start_cuda_requires_cuda_method_and_is_idempotent(tmp_path, monkeypatch):
    ds = _make_dataset(tmp_path / 'ds')
    out = tmp_path / 'train-idemp'
    c_cpu = _make_center(tmp_path / 'cpu', monkeypatch, cuda_available=False)
    with pytest.raises(ValueError, match='CUDA learner'):
        cuda.start_cuda(c_cpu, _valid_body(ds, out), jobs_dir=tmp_path / 'jobs', check_gpu=False)

    c = _make_center(tmp_path / 'gpu', monkeypatch, cuda_available=True)
    child = SimpleNamespace(pid=22222, poll=lambda: None)
    monkeypatch.setattr(experiment_jobs.subprocess, 'Popen', lambda *a, **k: child)
    receipt = {'pid': 22222, 'start': '10', 'boot': 'boot'}
    monkeypatch.setattr(cuda, 'process_stamp', lambda *a, **k: receipt)
    monkeypatch.setattr(experiment_center, 'process_stamp', lambda *a, **k: receipt)

    body = _valid_body(ds, out)
    first = cuda.start_cuda(c, body, jobs_dir=tmp_path / 'jobs', check_gpu=False)
    assert first['execution_mode'] == 'omx_cuda_train' and first['status'] == 'running'
    # Idempotent retry succeeds even if output_dir were created after launch.
    out.mkdir()
    assert cuda.start_cuda(c, body, jobs_dir=tmp_path / 'jobs', check_gpu=False)['id'] == first['id']
    with pytest.raises(ValueError, match='different inputs'):
        cuda.start_cuda(c, dict(body, steps=200), jobs_dir=tmp_path / 'jobs', check_gpu=False)


def test_reaper_propagates_worker_crash_immediately_without_snapshot_poll(tmp_path, monkeypatch):
    c = _make_center(tmp_path, monkeypatch, cuda_available=True)
    ds = _make_dataset(tmp_path / 'ds')
    out = tmp_path / 'train-crash'
    body = _valid_body(ds, out)
    real_popen = subprocess.Popen

    def crashing_popen(cmd, **kwargs):
        # Preserve --request/--out in argv so /proc/<pid>/cmdline process_stamp matches.
        snippet = 'import sys, time; time.sleep(0.08); sys.stderr.write("FileExistsError: simulated\\n"); sys.exit(2)'
        return real_popen([sys.executable, '-c', snippet, *cmd[2:]], **kwargs)

    monkeypatch.setattr(experiment_jobs.subprocess, 'Popen', crashing_popen)
    row = cuda.start_cuda(c, body, jobs_dir=tmp_path / 'jobs', check_gpu=False)
    rid = row['id']
    assert row['status'] == 'running'

    deadline = time.monotonic() + 3.0
    stored = row
    while time.monotonic() < deadline:
        with sqlite3.connect(c.db) as db:
            doc = db.execute('SELECT document FROM runs WHERE id=?', (rid,)).fetchone()[0]
        stored = json.loads(doc)
        if stored['status'] != 'running':
            break
        time.sleep(0.02)

    assert stored['status'] == 'failed'
    assert 'code 2' in stored['error'] and 'FileExistsError: simulated' in stored['error']
    assert c.run(rid)['status'] == 'failed'


def test_bundle_manifest_and_file_verify_hashes_and_block_traversal_and_symlinks(tmp_path, monkeypatch):
    c = _make_center(tmp_path, monkeypatch, cuda_available=True)
    rid = str(uuid.uuid4())
    train_dir = tmp_path / 'ext-train'
    model_dir = train_dir / 'checkpoints' / '007500' / 'pretrained_model'
    model_dir.mkdir(parents=True)
    (model_dir / 'config.json').write_text('{"type":"act"}', encoding='utf-8')
    weights = model_dir / 'model.safetensors'
    weights.write_bytes(b'safetensors-bytes')
    digest = hashlib.sha256(b'safetensors-bytes').hexdigest()

    out_dir = c.root / 'runs' / rid / 'output'
    out_dir.mkdir(parents=True)
    row = {
        'id': rid, 'status': 'succeeded', 'execution_mode': 'omx_cuda_train',
        'train_dir': str(train_dir),
        'result': {'policy_sha256': digest, 'checkpoint_dir': str(model_dir)},
    }
    with c.connect() as db:
        db.execute('INSERT INTO runs VALUES (?,?,?,?,?)', (rid, str(uuid.uuid4()), json.dumps(row), '{}', '{}'))

    manifest = c.bundle_manifest(rid)
    assert manifest['schema'] == cuda.MANIFEST_SCHEMA
    assert manifest['policy_revision'] == digest
    assert {f['path'] for f in manifest['files']} == {'config.json', 'model.safetensors'}
    assert len(json.dumps(manifest).encode('utf-8')) <= cuda.MANIFEST_LIMIT
    assert c.bundle_file(rid, 'config.json') == b'{"type":"act"}'
    assert c.bundle_file(rid, 'model.safetensors') == b'safetensors-bytes'

    for bad_path in ('../secret', 'sub/../config.json', '/etc/passwd', 'a\\b', '%2e%2e/x', ''):
        with pytest.raises(ValueError):
            c.bundle_file(rid, bad_path)

    (model_dir / 'link.json').symlink_to(model_dir / 'config.json')
    with pytest.raises(ValueError, match='symlink'):
        c.bundle_manifest(rid)
    (model_dir / 'link.json').unlink()

    weights.write_bytes(b'tampered')
    with pytest.raises(ValueError, match='changed'):
        c.bundle_manifest(rid)


def test_preflight_blocks_dangling_symlink_busy_gpu_and_oversized_bundle(tmp_path, monkeypatch):
    from contextlib import contextmanager
    ds = _make_dataset(tmp_path / 'ds')
    dangling = tmp_path / 'dangling-out'
    dangling.symlink_to(tmp_path / 'nonexistent-target')
    with pytest.raises(ValueError, match='non-symlink'):
        cuda.check_cuda_request(_valid_body(ds, dangling), tmp_path / 'center')

    out = tmp_path / 'train-gpu-busy'
    spec = cuda.check_cuda_request(_valid_body(ds, out), tmp_path / 'center')
    @contextmanager
    def busy_lease(*a, **k):
        raise cuda.GpuBusy('busy gpu')
        yield
    monkeypatch.setattr(cuda, 'gpu_lease', busy_lease)
    monkeypatch.setattr(cuda.os, 'name', 'posix')
    with pytest.raises(ValueError, match='busy gpu'):
        cuda.preflight_cuda(spec, out, jobs_dir=tmp_path / 'jobs', check_gpu=True)

    c = _make_center(tmp_path, monkeypatch, cuda_available=True)
    rid = str(uuid.uuid4())
    train_dir = tmp_path / 'ext-big'
    model_dir = train_dir / 'checkpoints' / '007500' / 'pretrained_model'
    model_dir.mkdir(parents=True)
    weights = model_dir / 'model.safetensors'
    weights.write_bytes(b'big')
    monkeypatch.setattr(cuda, 'FILE_LIMIT', 2)
    row = {
        'id': rid, 'status': 'succeeded', 'execution_mode': 'omx_cuda_train',
        'train_dir': str(train_dir), 'result': {'checkpoint_dir': str(model_dir)},
    }
    with c.connect() as db:
        db.execute('INSERT INTO runs VALUES (?,?,?,?,?)', (rid, str(uuid.uuid4()), json.dumps(row), '{}', '{}'))
    with pytest.raises(ValueError, match='size limit'):
        c.bundle_manifest(rid)
