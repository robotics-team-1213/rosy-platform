"""Owned learning jobs retain identity and fail closed across restarts."""
import base64
import json
from pathlib import Path
import sys
import uuid
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def center(tmp_path, monkeypatch):
    import experiment_center
    config = {'schema': 'rosy.omx.center-config/1', 'root': str(tmp_path / 'center'),
              'python': {'act': sys.executable, 'hilserl': sys.executable}}
    return experiment_center.Center(config)


def test_upload_is_sequential_bounded_and_never_a_path_escape(tmp_path, monkeypatch):
    c = center(tmp_path, monkeypatch)
    uid = str(uuid.uuid4())
    body = dict(upload_id=uid, name='dataset.json', offset=0,
                data=base64.b64encode(b'{}').decode())
    assert c.upload(body)['offset'] == 2
    for name in ('native-split-receipt.json', 'conversion-receipt.json'):
        assert c.upload(dict(body, name=name))['offset'] == 2
    assert c.upload(body)['offset'] == 2
    with pytest.raises(ValueError):
        c.upload(dict(body, data=base64.b64encode(b'[]').decode()))
    for name in ('../escape.npz', '/tmp/escape.npz', 'nested/x.npz', 'bad.txt'):
        with pytest.raises(ValueError):
            c.upload(dict(body, name=name))
    assert not (tmp_path / 'escape.npz').exists()


def test_upload_recovers_partial_chunk_without_overwriting_committed_bytes(tmp_path, monkeypatch):
    c = center(tmp_path, monkeypatch)
    uid = str(uuid.uuid4())
    body = dict(upload_id=uid, name='part.npz', offset=0,
                data=base64.b64encode(b'abcdef').decode())
    root = c.root/'uploads'/uid
    root.mkdir()
    (root/'part.npz').write_bytes(b'abc')
    assert c.upload(body)['offset'] == 6
    assert c.upload(dict(body, data=base64.b64encode(b'ab').decode()))['offset'] == 2
    assert (root/'part.npz').read_bytes() == b'abcdef'
    for offset, data in ((7, b'x'), (1, b'wrong'), (4, b'XXtail')):
        with pytest.raises(ValueError):
            c.upload(dict(body, offset=offset, data=base64.b64encode(data).decode()))
        assert (root/'part.npz').read_bytes() == b'abcdef'


def test_publish_recovers_move_before_sql_commit_and_retries_after_ack_loss(tmp_path, monkeypatch):
    from test_experiment_dataset import dataset
    c = center(tmp_path, monkeypatch)
    uid = str(uuid.uuid4())
    root = c.root/'uploads'/uid
    root.mkdir()
    dataset(root)
    original = {p.name: p.read_bytes() for p in root.iterdir()}
    root.rename(c.root/'datasets'/uid)  # Crash between move and SQL registration.
    body = {'upload_id': uid, 'name': 'Sealed source'}
    first = c.publish(body)
    assert c.publish(body) == first
    raw = original['dataset.json']
    assert c.upload(dict(upload_id=uid, name='dataset.json', offset=0,
        data=base64.b64encode(raw).decode()))['offset'] == len(raw)
    with pytest.raises(ValueError):
        c.upload(dict(upload_id=uid, name='new.npz', offset=0, data=base64.b64encode(b'x').decode()))
    assert not (c.root/'uploads'/uid).exists()
    assert len(c.snapshot()['datasets']) == 1
    assert {p.name: p.read_bytes() for p in (c.root/'datasets'/uid).iterdir()} == original


def test_publish_syncs_both_move_directories_before_sql_commit(tmp_path, monkeypatch):
    import experiment_catalog as module
    from contextlib import contextmanager
    import os
    import stat
    from test_experiment_dataset import dataset
    c = center(tmp_path, monkeypatch)
    uid = str(uuid.uuid4())
    root = c.root/'uploads'/uid
    root.mkdir()
    dataset(root)
    synced = set()
    fsync = os.fsync
    def record(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            synced.add(Path(f'/proc/self/fd/{fd}').resolve())
        fsync(fd)
    monkeypatch.setattr(module.os, 'fsync', record)
    @contextmanager
    def guarded():
        with c.connect() as db:
            yield db
            assert {c.root/'uploads', c.root/'datasets'} <= synced
    monkeypatch.setattr(c.catalog, 'connect', guarded)
    assert c.publish(dict(upload_id=uid, name='Durable registration'))['id'] == uid


def test_publish_does_not_acknowledge_registered_but_missing_dataset(tmp_path, monkeypatch):
    c = center(tmp_path, monkeypatch)
    uid = str(uuid.uuid4())
    with c.connect() as db:
        db.execute('INSERT INTO datasets VALUES (?,?)', (uid, json.dumps({'id': uid})))
    with pytest.raises(ValueError, match='missing'):
        c.publish(dict(upload_id=uid, name='Missing bytes'))


def test_unvalidated_upload_cannot_be_published(tmp_path, monkeypatch):
    c = center(tmp_path, monkeypatch)
    uid = str(uuid.uuid4())
    c.upload(dict(upload_id=uid, name='dataset.json', offset=0,
                  data=base64.b64encode(b'{}').decode()))
    with pytest.raises(ValueError):
        c.publish({'upload_id': uid, 'name': 'Broken upload'})
    assert c.snapshot()['datasets'] == []


def test_unknown_dataset_and_gpu_are_refused_before_process_launch(tmp_path, monkeypatch):
    c = center(tmp_path, monkeypatch)
    request = dict(dataset_id=str(uuid.uuid4()), method='act', steps=2, batch_size=1,
                   device='cpu', seed=0, request_id=str(uuid.uuid4()))
    with pytest.raises(ValueError, match='dataset'):
        c.start(request)
    with pytest.raises(ValueError, match='CPU'):
        c.start(dict(request, device='cuda'))
    assert c.snapshot()['runs'] == []


def test_persisted_job_without_process_proof_is_interrupted(tmp_path, monkeypatch):
    c = center(tmp_path, monkeypatch)
    rid = str(uuid.uuid4())
    with c.connect() as db:
        db.execute('INSERT INTO runs VALUES (?,?,?,?,?)',
                   (rid, 'unique', json.dumps({'id': rid, 'status': 'running',
                    'method': 'act', 'dataset_id': 'gone', 'steps': 2}), '{}', '{}'))
    assert c.snapshot()['runs'][0]['status'] == 'interrupted'
    assert center(tmp_path, monkeypatch).snapshot()['runs'][0]['status'] == 'interrupted'


def test_config_rejects_unknown_keys_and_missing_interpreter(tmp_path):
    import experiment_center
    with pytest.raises(ValueError):
        experiment_center.Center({'root': str(tmp_path), 'command': 'anything'})


def test_job_identity_survives_retry_and_completion_reconnect(tmp_path, monkeypatch):
    import experiment_center as module
    from test_experiment_profile import profile
    c = center(tmp_path, monkeypatch)
    c.methods['act']['available'] = True
    did = str(uuid.uuid4())
    with c.connect() as db:
        db.execute('INSERT INTO datasets VALUES (?,?)', (did, json.dumps({'id': did, 'revision': 'sealed'})))
    monkeypatch.setattr(module, 'load_dataset', lambda *a, **k: SimpleNamespace(revision='sealed', source='synthetic_smoke', profile=profile()))
    child = SimpleNamespace(pid=12345, poll=lambda: None)
    launched = []
    def launch(*args, **kwargs):
        with c.connect() as db:
            reserved = json.loads(db.execute('SELECT document FROM runs').fetchone()[0])
        assert reserved['status'] == 'launching'
        launched.append(args)
        return child
    monkeypatch.setattr(module.subprocess, 'Popen', launch)
    receipt = {'pid': 12345, 'start': '77', 'boot': 'boot'}
    stamps = []
    def stamp(pid, request=None):
        if request is not None:
            stamps.append(pid)
            if len(stamps) == 1:
                return None
        return receipt
    monkeypatch.setattr(module, 'process_stamp', stamp)
    body = dict(dataset_id=did, method='act', steps=2, batch_size=1,
                device='cpu', seed=0, request_id=str(uuid.uuid4()))
    row = c.start(body)
    assert c.start(body)['id'] == row['id']
    assert len(launched) == 1
    assert len(stamps) >= 2
    with pytest.raises(ValueError, match='different inputs'):
        c.start(dict(body, steps=3))
    with pytest.raises(ValueError, match='one owned'):
        c.start(dict(body, request_id=str(uuid.uuid4())))
    out = c.root / 'runs' / row['id'] / 'output'
    out.mkdir()
    (out / 'progress.json').write_text(json.dumps({'step': 1, 'steps': 2, 'loss': 0.5}))
    assert c.snapshot()['runs'][0]['progress']['step'] == 1
    monkeypatch.setattr(module, 'process_stamp', lambda *a: None)
    (out / 'result.json').write_text(json.dumps({'physical_learning_verified': False}))
    child.poll = lambda: 0
    assert c.snapshot()['runs'][0]['status'] == 'succeeded'
    monkeypatch.undo()
    assert center(tmp_path, monkeypatch).snapshot()['runs'][0]['result']['physical_learning_verified'] is False


def test_stop_only_signals_verified_owned_group(tmp_path, monkeypatch):
    import experiment_center as module
    c = center(tmp_path, monkeypatch)
    rid = str(uuid.uuid4())
    receipt = {'pid': 12345, 'start': '77', 'boot': 'boot'}
    with c.connect() as db:
        db.execute('INSERT INTO runs VALUES (?,?,?,?,?)',
                   (rid, 'stop', json.dumps({'id': rid, 'status': 'running'}), '{}', json.dumps(receipt)))
    monkeypatch.setattr(module, 'process_stamp', lambda *a: receipt)
    signals = []
    monkeypatch.setattr(module.os, 'killpg', lambda *a: signals.append(a))
    assert c.stop({'id': rid})['status'] == 'stopping'
    assert signals == [(12345, module.signal.SIGTERM)]
    monkeypatch.setattr(module, 'process_stamp', lambda *a: None)
    assert c.snapshot()['runs'][0]['status'] == 'cancelled'
    c.stop({'id': rid})
    assert len(signals) == 1


def test_dead_launcher_without_worker_preserves_request_as_interrupted(tmp_path, monkeypatch):
    import experiment_center as module
    c = center(tmp_path, monkeypatch)
    rid = str(uuid.uuid4())
    with c.connect() as db:
        db.execute('INSERT INTO runs VALUES (?,?,?,?,?)',
                   (rid, 'reserved', json.dumps({'id': rid, 'status': 'launching'}), '{}',
                    json.dumps({'launcher': {'pid': 999999, 'start': 'gone', 'boot': 'gone'}})))
    monkeypatch.setattr(module, 'process_stamp', lambda *a: None)
    assert c.snapshot()['runs'][0]['status'] == 'interrupted'
    with c.connect() as db:
        assert db.execute('SELECT request_id FROM runs').fetchone()[0] == 'reserved'


def test_model_export_requires_completed_run_and_verified_weights(tmp_path, monkeypatch):
    import hashlib
    import io
    import zipfile
    c = center(tmp_path, monkeypatch)
    rid = str(uuid.uuid4())
    root = c.root / 'runs' / rid / 'output'
    (root / 'policy').mkdir(parents=True)
    weights = root / 'policy/model.safetensors'
    weights.write_bytes(b'weights')
    for name in ('normalization.json', 'profile.json', 'request.json', 'result.json', 'evaluation.json', 'policy/config.json'):
        (root / name).write_text('{}')
    row = dict(id=rid, status='succeeded', result={'policy_sha256': hashlib.sha256(b'weights').hexdigest()})
    with c.connect() as db:
        db.execute('INSERT INTO runs VALUES (?,?,?,?,?)', (rid, 'export', json.dumps(row), '{}', '{}'))
    with zipfile.ZipFile(io.BytesIO(c.artifact(rid))) as archive:
        assert archive.read('policy/model.safetensors') == b'weights'
        assert 'normalization.json' in archive.namelist()
    weights.write_bytes(b'changed')
    with pytest.raises(ValueError, match='changed'):
        c.artifact(rid)
