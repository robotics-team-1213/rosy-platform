"""Persistent learner inputs, replay roles and update counts without optional torch."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import uuid

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiment_dataset import load_dataset
from test_experiment_dataset import dataset


def shard(root, suffix):
    root.mkdir()
    document = dataset(root, hil=True)
    document['profile']['schema'] = 'rosy.omx.learning-profile/2'
    for arm in document['profile']['arms']:
        arm['action_limits'] = [[-10.0, 10.0] for _ in arm['joint_names']]
    for row in document['episodes']:
        for key in ('id', 'session_id', 'parent_id'):
            row[key] += suffix
    (root / 'dataset.json').write_text(json.dumps(document))
    return root


def enqueue(output, sequence, root, *, identifier=None, revision=None):
    inbox = output.parent / 'inbox'
    inbox.mkdir(exist_ok=True)
    record = dict(id=identifier or str(uuid.uuid4()), dataset_root=str(root),
                  dataset_revision=revision or load_dataset(root, method='hilserl').revision)
    (inbox / f'{sequence:06}.json').write_text(json.dumps(record))
    return record


@pytest.fixture
def live(tmp_path, monkeypatch):
    import experiment_online as online
    initial = shard(tmp_path / 'initial', '-initial')
    output = tmp_path / 'run' / 'training'
    calls = []

    def trainer(data, destination, *, state, steps, **kwargs):
        if not state:
            state.update(model=object(), optimizers=object(), stats={'fit': 'initial-only'}, total_steps=0)
        before = (state['model'], state['optimizers'], copy.deepcopy(state['stats']))
        state['total_steps'] += steps
        calls.append((data, before, kwargs))
        destination.mkdir(parents=True)
        result = dict(method='hilserl', steps=steps, optimizer_steps=state['total_steps'],
                      policy_sha256=str(state['total_steps']), evaluation={'frames': 6})
        (destination / 'result.json').write_text(json.dumps(result))
        return result

    monkeypatch.setattr(online, 'train_dataset', trainer)
    request = dict(dataset_root=str(initial), method='hilserl', steps=2,
                   batch_size=2, device='cpu', seed=7)
    learner = online.OnlineLearner(request, output)
    return online, learner, output, calls, initial


def test_new_experience_keeps_model_optimizer_normalization_and_initial_eval(live, tmp_path):
    _, learner, output, calls, _ = live
    assert len(calls) == 1
    second = shard(tmp_path / 'second', '-second')
    record = enqueue(output, 1, second)
    assert learner.poll()
    assert len(calls) == 2 and calls[0][1] == calls[1][1]
    assert len(calls[1][0].split('train')) == 2
    assert [episode.metadata['session_id'] for episode in calls[1][0].split('eval')] == ['s1-initial']
    progress = json.loads((output / 'progress.json').read_text())
    assert progress['phase'] == 'waiting_for_experience' and progress['total_steps'] == 4
    assert progress['consumed_inputs'] == ['initial', record['id']]
    assert progress['latest_version'] == '000002'
    result = json.loads((output / 'result.json').read_text())
    assert result['execution_mode'] == 'online_experience'
    assert result['optimizer_steps'] == 4 and result['policy_activation'] is False
    first = (output / 'versions/000001/result.json').read_bytes()
    assert not learner.poll()
    assert (output / 'versions/000001/result.json').read_bytes() == first


def test_duplicate_identity_or_revision_never_updates_twice(live, tmp_path):
    _, learner, output, calls, initial = live
    second = shard(tmp_path / 'second', '-second')
    record = enqueue(output, 1, second)
    learner.poll()
    enqueue(output, 2, second, identifier=record['id'])
    enqueue(output, 3, second)
    enqueue(output, 4, initial)
    learner.poll()
    assert len(calls) == 2
    assert len(json.loads((output / 'progress.json').read_text())['consumed_inputs']) == 2


@pytest.mark.parametrize('fault', ['revision', 'profile', 'session', 'parent', 'content_role', 'action_bounds', 'episode_id'])
def test_invalid_input_preserves_current_policy_and_reports_rejection(live, tmp_path, fault):
    _, learner, output, calls, _ = live
    second = shard(tmp_path / 'second', '-second')
    document = json.loads((second / 'dataset.json').read_text())
    if fault == 'profile':
        document['profile']['cameras'][0]['placement'] = 'different-placement'
    elif fault in ('session', 'parent'):
        document['episodes'][0][fault + '_id'] = ('s1' if fault == 'session' else 'p1') + '-initial'
    elif fault == 'episode_id':
        document['episodes'][0]['id'] = 'train-initial'
    elif fault == 'content_role':
        document['episodes'][0]['file'], document['episodes'][1]['file'] = document['episodes'][1]['file'], document['episodes'][0]['file']
        document['episodes'][0]['sha256'], document['episodes'][1]['sha256'] = document['episodes'][1]['sha256'], document['episodes'][0]['sha256']
    elif fault == 'action_bounds':
        row = document['episodes'][0]
        with np.load(second / row['file']) as archive:
            arrays = dict(archive)
        arrays['action'][0, 0] = 11
        np.savez(second / row['file'], **arrays)
        row['sha256'] = hashlib.sha256((second / row['file']).read_bytes()).hexdigest()
    (second / 'dataset.json').write_text(json.dumps(document))
    enqueue(output, 1, second, revision='0' * 64 if fault == 'revision' else None)
    learner.poll()
    progress = json.loads((output / 'progress.json').read_text())
    assert len(calls) == 1 and progress['input_errors']
    assert progress['total_steps'] == 2 and progress['latest_version'] == '000001'


def test_rejects_non_hil_and_overwrite_before_output(live):
    online, _, output, _, initial = live
    for method, destination in [('act', output.parent / 'bad'), ('hilserl', output)]:
        with pytest.raises(ValueError):
            online.OnlineLearner(dict(dataset_root=str(initial), method=method, steps=2,
                                     batch_size=2, device='cpu', seed=0), destination)


def test_accumulated_replay_memory_is_bounded_before_update(live, tmp_path, monkeypatch):
    online, learner, output, calls, _ = live
    monkeypatch.setattr(online, 'MAX_REPLAY_BYTES', learner.replay_bytes + 1)
    enqueue(output, 1, shard(tmp_path / 'second', '-second'))
    learner.poll()
    assert len(calls) == 1
    assert '512 MiB' in json.loads((output / 'progress.json').read_text())['input_errors'][0]['reason']


def test_declared_bounds_allow_new_actions_outside_initial_observed_range(live, tmp_path):
    _, learner, output, calls, _ = live
    root = shard(tmp_path / 'second', '-second')
    document = json.loads((root / 'dataset.json').read_text())
    row = document['episodes'][0]
    with np.load(root / row['file']) as archive:
        arrays = dict(archive)
    arrays['action'][:] = 5
    np.savez(root / row['file'], **arrays)
    row['sha256'] = hashlib.sha256((root / row['file']).read_bytes()).hexdigest()
    (root / 'dataset.json').write_text(json.dumps(document))
    enqueue(output, 1, root)
    learner.poll()
    assert len(calls) == 2
    assert calls[1][2]['action_bounds'] == [[-10.0, 10.0]] * 3
    assert calls[0][1] == calls[1][1]


def test_inbox_waits_for_missing_sequence_before_later_input(live, tmp_path):
    _, learner, output, calls, _ = live
    later = enqueue(output, 2, shard(tmp_path / 'later', '-later'))
    assert not learner.poll() and len(calls) == 1
    first = enqueue(output, 1, shard(tmp_path / 'first', '-first'))
    assert learner.poll()
    assert len(calls) == 3 and learner.inputs == ['initial', first['id'], later['id']]


def test_float32_action_limit_endpoint_is_accepted_without_clamping(live, tmp_path):
    online, _, _, calls, _ = live

    def bounded(root, suffix, action):
        shard(root, suffix)
        document = json.loads((root / 'dataset.json').read_text())
        document['profile']['arms'][0]['action_limits'] = [[-0.1, 0.1]] * 3
        for row_index, row in enumerate(document['episodes']):
            with np.load(root / row['file']) as archive:
                arrays = dict(archive)
            arrays['action'][:] = action
            arrays['observation.state'] += row_index * 0.01
            np.savez(root / row['file'], **arrays)
            row['sha256'] = hashlib.sha256((root / row['file']).read_bytes()).hexdigest()
        (root / 'dataset.json').write_text(json.dumps(document))
        return root

    initial = bounded(tmp_path / 'endpoint', '-endpoint', np.float32(0.1))
    output = tmp_path / 'endpoint-run' / 'output'
    learner = online.OnlineLearner(dict(dataset_root=str(initial), method='hilserl',
        steps=2, batch_size=2, device='cpu', seed=7), output)
    assert learner.bounds.dtype == np.float32
    assert len(calls) == 2
    beyond = bounded(tmp_path / 'beyond', '-beyond', np.nextafter(np.float32(0.1), np.float32(1)))
    enqueue(output, 1, beyond)
    learner.poll()
    assert len(calls) == 2
    assert 'exceeds' in learner.errors[0]['reason']


def test_online_forwards_selected_arm_and_preserves_model_profile_revision(live, tmp_path):
    online, _, _, _, initial = live
    document = json.loads((initial / 'dataset.json').read_text())
    document['profile']['mode'] = 'independent'
    (initial / 'dataset.json').write_text(json.dumps(document))
    calls = []
    def trainer(data, destination, *, state, **options):
        calls.append(options)
        state['total_steps'] = 1
        destination.mkdir(parents=True)
        return dict(profile_revision='actual-selected-model-profile',
                    training_scope={'arm_ids': ['arm_a']}, evaluation={})
    previous = online.train_dataset
    online.train_dataset = trainer
    try:
        learner = online.OnlineLearner(dict(dataset_root=str(initial), method='hilserl',
            steps=1, batch_size=2, device='cpu', seed=7, arm_id='arm_a'), tmp_path / 'selected/output')
    finally:
        online.train_dataset = previous
    assert calls[0]['arm_id'] == 'arm_a'
    result = json.loads((learner.output / 'result.json').read_text())
    assert result['profile_revision'] == 'actual-selected-model-profile'


def test_malformed_per_arm_experience_is_rejected_before_update_and_next_input_continues(tmp_path, monkeypatch):
    import experiment_online as online
    from experiment_scope import select_dataset
    from test_experiment_scope import independent_dataset
    def recording(name, *, legacy=False):
        root = tmp_path / name
        root.mkdir()
        document = independent_dataset(root, source='robot_rollout', legacy=legacy)
        for row in document['episodes']:
            for key in ('id', 'session_id', 'parent_id'):
                row[key] += '-' + name
        (root / 'dataset.json').write_text(json.dumps(document))
        return root
    calls = []
    def trainer(data, destination, *, state, steps, arm_id, **options):
        # The actual trainer's scope validation must never receive malformed experience.
        _, scope = select_dataset(data, arm_id, method='hilserl')
        if not state:
            state.update(model=object(), optimizers=object(), stats={'frozen': True}, total_steps=0,
                         training_scope=scope)
        state['total_steps'] += steps
        calls.append(data)
        destination.mkdir(parents=True)
        return dict(profile_revision='selected-profile', optimizer_steps=state['total_steps'])
    monkeypatch.setattr(online, 'train_dataset', trainer)
    output = tmp_path / 'run/output'
    learner = online.OnlineLearner(dict(dataset_root=str(recording('initial')), method='hilserl',
        steps=2, batch_size=2, device='cpu', seed=7, arm_id='arm_b'), output)
    model, optimizer = learner.state['model'], learner.state['optimizers']
    original_result = (output / 'result.json').read_bytes()
    original_roles = dict(learner.roles)
    enqueue(output, 1, recording('malformed', legacy=True))
    assert learner.poll()
    assert len(calls) == 1 and learner.state['total_steps'] == 2
    assert learner.state['model'] is model and learner.state['optimizers'] is optimizer
    assert learner.state['stats'] == {'frozen': True}
    assert learner.latest_version == '000001' and learner.roles == original_roles
    assert (output / 'result.json').read_bytes() == original_result
    assert not (output / 'versions/000002').exists()
    assert len(learner.errors) == 1 and 'arm' in learner.errors[0]['reason']
    accepted = enqueue(output, 2, recording('valid'))
    assert learner.poll()
    assert len(calls) == 2 and learner.state['total_steps'] == 4
    assert learner.state['model'] is model and learner.state['optimizers'] is optimizer
    assert learner.latest_version == '000002' and learner.inputs == ['initial', accepted['id']]
