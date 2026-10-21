"""Explicit independent arm choice reaches a fixed worker without rewriting source data."""
import json
from types import SimpleNamespace
import uuid

import pytest

from test_experiment_center import center
from test_experiment_scope import independent_dataset


@pytest.mark.parametrize('mode', ['act', 'hilserl', 'online'])
def test_arm_target_checked_before_launch_and_persisted_with_full_source(tmp_path, monkeypatch, mode):
    import experiment_center as module
    c = center(tmp_path, monkeypatch)
    did = str(uuid.uuid4())
    upload = c.root / 'uploads' / did
    upload.mkdir()
    document = independent_dataset(upload, source='robot_rollout')
    c.publish({'upload_id': did, 'name': 'SYNTHETIC independent scope test'})
    method = 'act' if mode == 'act' else 'hilserl'
    c.methods[method]['available'] = True
    start = c.start_online if mode == 'online' else c.start
    receipt = {'pid': 12345, 'start': '77', 'boot': 'boot'}
    monkeypatch.setattr(module, 'process_stamp', lambda *a: receipt)
    calls = []
    monkeypatch.setattr(module.subprocess, 'Popen', lambda *a, **k: calls.append(a) or SimpleNamespace(pid=12345, poll=lambda: None))
    saved = c.profiles.save({'profile': document['profile'], 'request_id': str(uuid.uuid4())})
    body = dict(dataset_id=did, method=method, steps=2, batch_size=2, device='cpu', seed=7,
                request_id=str(uuid.uuid4()), profile_id=saved['id'])
    for extra in ({}, {'arm_id': 'unknown'}, {'arm_id': None}):
        with pytest.raises(ValueError, match='arm'):
            start(dict(body, **extra))
    assert not calls and not c.snapshot()['runs']
    row = start(dict(body, arm_id='arm_b'))
    assert row['training_scope']['arm_ids'] == ['arm_b']
    assert row['training_scope']['action_indices'] == [3, 4]
    assert row['selected_profile'] == {'id': saved['id'], 'revision': saved['revision']}
    assert start(dict(body, arm_id='arm_b'))['id'] == row['id'] and len(calls) == 1
    with pytest.raises(ValueError, match='different inputs'):
        start(dict(body, arm_id='arm_a'))
    request = json.loads((c.root / 'runs' / row['id'] / 'request.json').read_text())
    assert request['arm_id'] == 'arm_b' and 'profile_id' not in request
    original = json.loads((c.root / 'datasets' / did / 'dataset.json').read_text())
    assert original == document and len(original['profile']['arms']) == 2


def test_independent_experience_requires_arm_signals_before_queuing(tmp_path, monkeypatch):
    import experiment_center as module
    c = center(tmp_path, monkeypatch)
    identifiers = []
    for legacy in (False, True):
        did = str(uuid.uuid4())
        upload = c.root / 'uploads' / did
        upload.mkdir()
        document = independent_dataset(upload, legacy=legacy)
        for episode in document['episodes']:
            for key in ('id', 'session_id', 'parent_id'):
                episode[key] = did + '-' + episode[key]
        (upload / 'dataset.json').write_text(json.dumps(document))
        identifiers.append(c.publish({'upload_id': did, 'name': 'SYNTHETIC signal admission'})['id'])
    c.methods['hilserl']['available'] = True
    monkeypatch.setattr(module, 'process_stamp', lambda *a: {'pid': 12345, 'start': '77', 'boot': 'boot'})
    monkeypatch.setattr(module.subprocess, 'Popen', lambda *a, **k: SimpleNamespace(pid=12345, poll=lambda: None))
    row = c.start_online(dict(dataset_id=identifiers[0], method='hilserl', steps=2, batch_size=2,
                             device='cpu', seed=7, request_id=str(uuid.uuid4()), arm_id='arm_b'))
    with pytest.raises(ValueError, match='arm.*signal'):
        c.experience(dict(id=row['id'], dataset_id=identifiers[1], request_id=str(uuid.uuid4())))
    current = c.snapshot()['runs'][0]
    assert current['status'] == 'running' and not current['inputs']
    assert not list((c.root / 'runs' / row['id'] / 'inbox').iterdir())
