"""Registered native exports reuse owned job admission and register completed arrays once."""
import json
from types import SimpleNamespace
import uuid

import pytest

from test_experiment_center import center
from test_experiment_dataset import dataset, save


def launch(tmp_path, monkeypatch):
    import experiment_center as module
    import experiment_export
    c = center(tmp_path, monkeypatch)
    c.methods['act']['available'] = True
    prepared = dict(id=uuid.uuid4().hex, kind='omx', path=str(tmp_path/'prepared'), name='Recorded')
    body = dict(prepared_id=prepared['id'], name='Reviewed export', profile={'test': True},
                request_id=str(uuid.uuid4()))
    def prepare(actual, row):
        assert actual == body and row == prepared
        return {'schema': 'test-worker'}, dict(prepared_id=row['id'], name=body['name'],
            source='reviewed_demonstration', method='act', execution_mode='native_export')
    monkeypatch.setattr(experiment_export, 'prepare_export', prepare)
    proof = {'pid': 12345, 'start': '77', 'boot': 'boot'}
    monkeypatch.setattr(module, 'process_stamp', lambda *args: proof)
    child = SimpleNamespace(pid=12345, poll=lambda: None)
    calls = []
    def popen(*args, **kwargs):
        with c.connect() as db:
            row = json.loads(db.execute('SELECT document FROM runs').fetchone()[0])
        assert row['status'] == 'launching'
        calls.append(args)
        return child
    monkeypatch.setattr(module.subprocess, 'Popen', popen)
    return c, prepared, body, child, calls


def test_export_reserves_before_launch_and_retry_reuses_owned_job(tmp_path, monkeypatch):
    c, prepared, body, child, calls = launch(tmp_path, monkeypatch)
    row = c.start_export(body, prepared)
    assert row['execution_mode'] == 'native_export' and row['status'] == 'running'
    assert 'experiment_export.py' in calls[0][0][1]
    assert c.start_export(body, prepared)['id'] == row['id'] and len(calls) == 1
    with pytest.raises(ValueError, match='different inputs'):
        c.start_export(dict(body, name='Changed'), prepared)
    with pytest.raises(ValueError, match='one owned'):
        c.start_export(dict(body, request_id=str(uuid.uuid4())), prepared)
    assert c.snapshot()['runs'][0]['prepared_id'] == prepared['id']


def test_export_uses_only_explicit_current_server_review_snapshot(tmp_path, monkeypatch):
    import experiment_export
    c, prepared, body, child, calls = launch(tmp_path, monkeypatch)
    review_id = str(uuid.uuid4())
    snapshot = {'id': review_id, 'source_revision': 'a'*64, 'decisions': []}
    def resolve(actual_id, actual_row):
        assert actual_id == review_id and actual_row == prepared
        return snapshot
    def prepare(core, actual_row, *, review):
        assert core == body and actual_row == prepared and review is snapshot
        return {'review': review}, dict(prepared_id=prepared['id'], name=body['name'],
                source='reviewed_demonstration', method='act', execution_mode='native_export', review_id=review_id)
    monkeypatch.setattr(c.reviews, 'for_export', resolve)
    monkeypatch.setattr(experiment_export, 'prepare_export', prepare)
    row = c.start_export(dict(body, review_id=review_id), prepared)
    assert row['review_id'] == review_id
    assert json.loads((c.root/'runs'/row['id']/'request.json').read_bytes())['review'] == snapshot
    with pytest.raises(ValueError, match='different inputs'):
        c.start_export(body, prepared)


def test_export_resolves_saved_profile_exactly_and_refuses_unsaved_changes(tmp_path, monkeypatch):
    import copy
    import experiment_export
    from experiment_profile import profile_revision
    from test_experiment_profile import profile
    c, prepared, body, child, calls = launch(tmp_path, monkeypatch)
    setup = profile()
    setup['schema'] = 'rosy.omx.learning-profile/2'
    for arm in setup['arms']:
        arm['action_limits'] = [[-1.0, 1.0] for _ in arm['joint_names']]
    saved = c.profiles.save({'profile': setup, 'request_id': str(uuid.uuid4())})
    submitted = copy.deepcopy(setup)
    for arm in submitted['arms']:
        arm['action_limits'] = [[-1, 1] for _ in arm['joint_names']]
    assert submitted == setup and profile_revision(submitted) != saved['revision']
    def prepare(core, actual_row):
        assert actual_row == prepared and set(core) == set(body)
        assert profile_revision(core['profile']) == saved['revision']
        return {'profile': core['profile']}, dict(prepared_id=prepared['id'], name=body['name'],
                source='reviewed_demonstration', method='act', execution_mode='native_export')
    monkeypatch.setattr(experiment_export, 'prepare_export', prepare)
    changed = copy.deepcopy(submitted)
    changed['cameras'][0]['placement'] = 'different-placement'
    request = dict(body, profile=submitted, profile_id=saved['id'])
    with pytest.raises(ValueError, match='profile'):
        c.start_export(dict(request, profile=changed), prepared)
    assert not calls
    row = c.start_export(request, prepared)
    assert row['profile_id'] == saved['id'] and row['profile_revision'] == saved['revision']
    worker = json.loads((c.root/'runs'/row['id']/'request.json').read_bytes())
    assert profile_revision(worker['profile']) == saved['revision']


def test_export_only_accepts_registered_omx_and_no_paths(tmp_path, monkeypatch):
    c, prepared, body, child, calls = launch(tmp_path, monkeypatch)
    for row in (None, dict(prepared, kind='policy'), dict(prepared, id=uuid.uuid4().hex)):
        with pytest.raises(ValueError, match='registered'):
            c.start_export(body, row)
    with pytest.raises(ValueError):
        c.start_export(dict(body, prepared_root='/tmp/anything'), prepared)
    assert not calls and c.snapshot()['runs'] == []


def test_completed_export_registers_dataset_once_and_survives_crash_between_move_and_commit(
        tmp_path, monkeypatch):
    import experiment_center as module
    from experiment_dataset import load_dataset
    c, prepared, body, child, calls = launch(tmp_path, monkeypatch)
    row = c.start_export(body, prepared)
    output = c.root/'runs'/row['id']/'output'
    converted = output/'export/dataset'
    converted.mkdir(parents=True)
    document = dataset(converted)
    document['source'] = 'reviewed_demonstration'
    save(converted, document)
    revision = load_dataset(converted).revision
    (converted/'conversion-receipt.json').write_text(json.dumps({'dataset_revision': revision}))
    (output/'result.json').write_text(json.dumps({'dataset_revision': revision, 'act_only': True,
        'physical_learning_verified': False, 'policy_activation': False}))
    child.poll = lambda: 0
    monkeypatch.setattr(module, 'process_stamp', lambda *args: None)
    # Simulate a prior process having moved the immutable dataset but not committed its SQL row.
    converted.rename(c.root/'datasets'/row['id'])
    value = c.snapshot()
    run = value['runs'][0]
    assert run['status'] == 'succeeded' and run['result']['dataset_id'] == row['id']
    assert run['result']['dataset_revision'] == revision
    assert len(value['datasets']) == 1 and value['datasets'][0]['name'] == body['name']
    assert value['datasets'][0]['source'] == 'reviewed_demonstration'
    assert c.snapshot()['datasets'] == value['datasets']
    monkeypatch.undo()
    assert center(tmp_path, monkeypatch).snapshot()['datasets'] == value['datasets']
    with pytest.raises(ValueError, match='model|learning'):
        c.artifact(row['id'])


@pytest.mark.parametrize('failure', ['worker_error', 'revision_changed'])
def test_export_never_registers_tampered_or_failed_output(tmp_path, monkeypatch, failure):
    import experiment_center as module
    c, prepared, body, child, calls = launch(tmp_path, monkeypatch)
    row = c.start_export(body, prepared)
    output = c.root/'runs'/row['id']/'output'
    output.mkdir()
    if failure == 'worker_error':
        (output/'error.json').write_text(json.dumps({'error': 'source changed during export'}))
        child.poll = lambda: 2
    else:
        converted = output/'export/dataset'
        converted.mkdir(parents=True)
        dataset(converted)
        (converted/'conversion-receipt.json').write_text(json.dumps({'dataset_revision': 'a'*64}))
        (output/'result.json').write_text(json.dumps({'dataset_revision': 'a'*64, 'act_only': True}))
        child.poll = lambda: 0
    monkeypatch.setattr(module, 'process_stamp', lambda *args: None)
    value = c.snapshot()
    assert value['runs'][0]['status'] == 'failed' and not value['datasets']
    assert not (c.root/'datasets'/row['id']).exists()
