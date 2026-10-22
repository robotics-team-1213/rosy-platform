"""Continuous jobs accept immutable registered experience, never commands or paths."""
import hashlib
import json
from types import SimpleNamespace
import uuid

import numpy as np
import pytest

from test_experiment_center import center
from test_experiment_dataset import dataset


def registered(c, *, shift=0, limit=3):
    did = str(uuid.uuid4())
    root = c.root / 'uploads' / did
    root.mkdir()
    document = dataset(root, hil=True)
    document['profile']['schema'] = 'rosy.omx.learning-profile/2'
    document['profile']['arms'][0]['action_limits'] = [[-limit, limit]] * 3
    for row in document['episodes']:
        for key in ('id', 'session_id', 'parent_id'):
            row[key] = did + '-' + row[key]
        if row['split'] == 'train' and shift:
            file = root / row['file']
            with np.load(file, allow_pickle=False) as archive:
                arrays = dict(archive)
            arrays['action'] += shift
            np.savez(file, **arrays)
            row['sha256'] = hashlib.sha256(file.read_bytes()).hexdigest()
    (root / 'dataset.json').write_text(json.dumps(document))
    return c.publish({'upload_id': did, 'name': 'Validated recordings'})['id']


def running(tmp_path, monkeypatch):
    import experiment_center as module
    c = center(tmp_path, monkeypatch)
    did = registered(c)
    c.methods['hilserl']['available'] = True
    receipt = {'pid': 12345, 'start': '77', 'boot': 'boot'}
    monkeypatch.setattr(module, 'process_stamp', lambda *args: receipt)
    child = SimpleNamespace(pid=12345, poll=lambda: None)
    calls = []
    monkeypatch.setattr(module.subprocess, 'Popen', lambda *args, **kwargs: calls.append(args) or child)
    body = dict(dataset_id=did, method='hilserl', steps=2, batch_size=2,
                device='cpu', seed=7, request_id=str(uuid.uuid4()))
    row = c.start_online(body)
    assert 'experiment_online.py' in calls[0][0][1]
    assert row['execution_mode'] == 'online_experience'
    return c, row, body


def test_experience_is_persistent_ordered_and_idempotent(tmp_path, monkeypatch):
    c, row, body = running(tmp_path, monkeypatch)
    did = registered(c, shift=0.25)
    request = dict(id=row['id'], dataset_id=did, request_id=str(uuid.uuid4()))
    item = c.experience(request)
    assert item['sequence'] == 1 and item['status'] == 'queued'
    assert c.experience(request) == item
    inbox = c.root / 'runs' / row['id'] / 'inbox'
    descriptor = json.loads((inbox / '000001.json').read_text())
    assert descriptor['id'] == request['request_id']
    assert set(descriptor) == {'id', 'dataset_root', 'dataset_revision'}
    assert len(list(inbox.iterdir())) == 1
    with pytest.raises(ValueError, match='already'):
        c.experience(dict(request, request_id=str(uuid.uuid4())))
    # Recovery republishes an acknowledged SQL reservation that lost its file before restart.
    (inbox / '000001.json').unlink()
    assert c.snapshot()['runs'][0]['inputs'][0]['id'] == request['request_id']
    assert (inbox / '000001.json').exists()
    progress = c.root / 'runs' / row['id'] / 'output'
    progress.mkdir()
    (progress / 'progress.json').write_text(json.dumps({'phase': 'waiting_for_experience',
        'total_steps': 4, 'consumed_inputs': [{'id': request['request_id']}], 'input_errors': []}))
    assert c.snapshot()['runs'][0]['inputs'][0]['status'] == 'consumed'


def test_experience_rejects_profile_drift_action_overflow_and_host_paths(tmp_path, monkeypatch):
    c, row, _ = running(tmp_path, monkeypatch)
    for did, reason in [(registered(c, shift=0.25, limit=2), 'profile'),
                        (registered(c, shift=4), 'range')]:
        with pytest.raises(ValueError, match=reason):
            c.experience(dict(id=row['id'], dataset_id=did, request_id=str(uuid.uuid4())))
    with pytest.raises(ValueError):
        c.experience(dict(id=row['id'], dataset_root='/tmp/arbitrary', request_id=str(uuid.uuid4())))
    assert c.snapshot()['runs'][0]['inputs'] == []


def test_online_mode_cannot_reuse_offline_request_identity(tmp_path, monkeypatch):
    c, row, body = running(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='different inputs'):
        c.start(body)


def test_dead_continuous_worker_is_not_success_due_to_an_earlier_checkpoint(tmp_path, monkeypatch):
    import experiment_center as module
    c, row, _ = running(tmp_path, monkeypatch)
    out = c.root / 'runs' / row['id'] / 'output'
    out.mkdir()
    (out / 'result.json').write_text(json.dumps({'steps': 2}))
    monkeypatch.setattr(module, 'process_stamp', lambda *args: None)
    assert c.snapshot()['runs'][0]['status'] == 'interrupted'


def test_center_data_cannot_be_rebound_to_another_review_project(tmp_path, monkeypatch):
    c = center(tmp_path, monkeypatch)
    c.bind_workspace('project-a')
    c.bind_workspace('project-a')
    with pytest.raises(ValueError, match='project'):
        c.bind_workspace('project-b')
