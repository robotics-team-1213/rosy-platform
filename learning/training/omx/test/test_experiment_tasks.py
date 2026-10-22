"""Task-bound host jobs retain the checked scope through evaluation and download."""
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import uuid
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiment_profile import profile_revision
from test_experiment_center import center
from test_experiment_profile import profile


class Registry:
    def __init__(self, setup):
        self.profile_revision = profile_revision(setup)
        self.task_id = str(uuid.uuid4())
        self.calls = []
        self.reject = False

    def resolve(self, task_id, dataset_id, dataset_revision, profile_revision, component_ids, host_id):
        if self.reject or task_id != self.task_id or profile_revision != self.profile_revision:
            raise ValueError('task dataset/profile binding differs')
        self.calls.append((dataset_id, dataset_revision, list(component_ids), host_id))
        robot_id = str(uuid.uuid4())
        participants = [dict(robot_id=robot_id, component_id=part, role='arm') for part in component_ids]
        return dict(task_id=task_id, task_revision='a' * 64, project_id='project',
                    dataset_id=dataset_id, dataset_revision=dataset_revision,
                    profile_id=str(uuid.uuid4()), profile_revision=profile_revision,
                    compute_host=host_id, component_ids=list(component_ids),
                    task_participants=participants, participants=participants,
                    robots=[dict(id=robot_id, kind='omx', model_revision='model-v1',
                                 device_id='registered-device', revision='c' * 64)])


@pytest.fixture
def owned(tmp_path, monkeypatch):
    import experiment_center as module
    from experiment_dataset import ExperimentDataset
    c = center(tmp_path, monkeypatch)
    c.host_id = 'model'
    c.methods['act']['available'] = c.methods['hilserl']['available'] = True
    setup = profile()
    checked = ExperimentDataset(setup, 'synthetic_smoke', [], 'b' * 64)
    did = str(uuid.uuid4())
    with c.connect() as db:
        db.execute('INSERT INTO datasets VALUES (?,?)', (did, json.dumps(dict(id=did, revision=checked.revision, profile=setup))))
    monkeypatch.setattr(module, 'load_dataset', lambda *a, **k: checked)
    monkeypatch.setattr(module, 'check_action_space', lambda *a: None)
    registry = Registry(setup)
    c.tasks = registry
    launches = []

    def launch(owner, db, request_id, request, row, stamp):
        launches.append(json.loads((owner.root / 'runs' / row['id'] / 'request.json').read_text()))
        row['status'] = 'running'
        db.execute('INSERT INTO runs VALUES (?,?,?,?,?)', (row['id'], request_id, json.dumps(row), request, '{}'))
        return row

    monkeypatch.setattr(module, 'launch', launch)
    monkeypatch.setattr(c, '_refresh', lambda db: None)
    body = dict(dataset_id=did, method='act', steps=2, batch_size=1, device='cpu', seed=0,
                request_id=str(uuid.uuid4()), task_id=registry.task_id, compute_host='model')
    return c, registry, checked, body, launches


@pytest.mark.parametrize('mode,arm_ids', [('cooperative', ['arm_a', 'arm_b']), ('independent', ['arm_b'])])
def test_task_scope_worker_request_retry_and_evaluation_archive(owned, mode, arm_ids):
    c, registry, checked, body, launches = owned
    checked.profile['mode'] = mode
    registry.profile_revision = profile_revision(checked.profile)
    if mode == 'independent':
        body['arm_id'] = 'arm_b'
    source = c.root / 'datasets' / body['dataset_id']
    source.mkdir()
    receipt_bytes = b'{"source_revision":"reviewed-source-r1"}'
    (source / 'conversion-receipt.json').write_bytes(receipt_bytes)
    row = c.start(body)
    binding = row['learning_task']
    assert binding == launches[0]['learning_task']
    assert binding['component_ids'] == arm_ids and binding['compute_host'] == 'model'
    assert binding['attachment_kind'] == 'historical_dataset_attachment'
    assert binding['source_receipts'] == [{'name': 'conversion-receipt.json',
                                         'sha256': hashlib.sha256(receipt_bytes).hexdigest()}]
    assert registry.calls == [(body['dataset_id'], checked.revision, arm_ids, 'model')]
    assert c.start(body) == row and len(launches) == 1
    root = c.root / 'runs' / row['id'] / 'output'
    (root / 'policy').mkdir(parents=True)
    result = dict(policy_sha256=hashlib.sha256(b'weights').hexdigest(), learning_task=binding)
    for name, value in {'normalization.json': {}, 'profile.json': checked.profile,
                        'request.json': {'learning_task': binding}, 'result.json': result,
                        'evaluation.json': {'frames': 6, 'learning_task': binding}, 'policy/config.json': {}}.items():
        (root / name).write_text(json.dumps(value))
    (root / 'policy/model.safetensors').write_bytes(b'weights')
    row.update(status='succeeded', result=result)
    with c.connect() as db:
        db.execute('UPDATE runs SET document=? WHERE id=?', (json.dumps(row), row['id']))
    with zipfile.ZipFile(io.BytesIO(c.artifact(row['id']))) as archive:
        receipt = json.loads(archive.read('learning-task.json'))
        assert receipt['learning_task'] == binding
        assert receipt['evaluation_sha256'] == hashlib.sha256(archive.read('evaluation.json')).hexdigest()
    changed = copy.deepcopy(binding)
    changed['task_id'] = str(uuid.uuid4())
    (root / 'evaluation.json').write_text(json.dumps({'learning_task': changed}))
    with pytest.raises(ValueError, match='task|lineage'):
        c.artifact(row['id'])


@pytest.mark.parametrize('fault', ['host', 'unset_host', 'registry', 'unknown_task', 'profile'])
def test_task_start_fails_closed_before_reserving_worker(owned, fault):
    c, registry, checked, body, launches = owned
    if fault == 'host':
        body['compute_host'] = 'ai'
    elif fault == 'unset_host':
        c.host_id = None
    elif fault == 'registry':
        c.tasks = None
    elif fault == 'unknown_task':
        body['task_id'] = str(uuid.uuid4())
    else:
        checked.profile['task'] = 'Changed source setup'
    with pytest.raises(ValueError):
        c.start(body)
    assert launches == []
    with c.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM runs').fetchone()[0] == 0


def test_taskless_start_still_works_without_registry_or_host(owned):
    c, _, _, body, launches = owned
    c.tasks = c.host_id = None
    body.pop('task_id')
    body.pop('compute_host')
    row = c.start(body)
    assert 'learning_task' not in row and 'learning_task' not in launches[0]


@pytest.mark.parametrize('missing', ['task_id', 'compute_host'])
def test_task_and_host_are_required_together(owned, missing):
    c, _, _, body, launches = owned
    body.pop(missing)
    with pytest.raises(ValueError):
        c.start(body)
    assert launches == []


def test_cross_task_continuous_experience_never_reaches_inbox(owned, monkeypatch):
    c, registry, checked, body, _ = owned
    body['method'] = 'hilserl'
    row = c.start_online(body)
    did = str(uuid.uuid4())
    with c.connect() as db:
        db.execute('INSERT INTO datasets VALUES (?,?)', (did, json.dumps(dict(id=did, revision=checked.revision, profile=checked.profile))))
    registry.reject = True
    admitted = []
    monkeypatch.setattr(c.inbox, 'add', lambda *args: admitted.append(args))
    with pytest.raises(ValueError, match='task'):
        c.experience(dict(id=row['id'], dataset_id=did, request_id=str(uuid.uuid4())))
    assert admitted == []


def test_training_entry_preserves_task_binding_and_checks_source_before_updates(owned, tmp_path, monkeypatch):
    import experiment_train as trainer
    c, _, checked, body, _ = owned
    row = c.start(body)
    binding = row['learning_task']
    monkeypatch.setattr(trainer, 'load_dataset', lambda *a, **k: checked)
    calls = []
    monkeypatch.setattr(trainer, 'train_dataset', lambda *a, **k: calls.append(k))
    trainer.train(tmp_path / 'source', tmp_path / 'trained', learning_task=binding)
    assert calls[0]['learning_task'] == binding
    wrong = copy.deepcopy(binding)
    wrong['dataset_revision'] = 'd' * 64
    with pytest.raises(ValueError, match='task|revision'):
        trainer.train(tmp_path / 'source', tmp_path / 'trained', learning_task=wrong)
    assert len(calls) == 1


def test_worker_task_metadata_is_fixed_and_bounded(owned):
    from experiment_jobs import check_learning_task
    c, _, _, body, _ = owned
    binding = c.start(body)['learning_task']
    assert check_learning_task(binding) == binding
    for changed in (dict(binding, command='anything'), dict(binding, project_id='x' * 65536),
                    dict(binding, component_ids=['not-in-participants']), dict(binding, compute_host='other')):
        with pytest.raises(ValueError):
            check_learning_task(changed)
