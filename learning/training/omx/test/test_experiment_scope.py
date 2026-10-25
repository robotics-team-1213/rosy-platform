"""Independent policies use explicit per-arm supervision, never copied group rewards."""
import copy
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pytest

from test_experiment_profile import profile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def independent_dataset(root, *, source='synthetic_smoke', transitions=True, legacy=False):
    setup = profile()
    setup['mode'] = 'independent'
    setup['schema'] = 'rosy.omx.learning-profile/2'
    setup['arms'][1]['joint_names'] = ['elbow', 'gripper']
    for arm in setup['arms']:
        arm['action_limits'] = [[-2, 2]] * len(arm['joint_names'])
    document = dict(schema='rosy.omx.experiment-dataset/1' if legacy else 'rosy.omx.experiment-dataset/2',
                    profile=setup, source=source, episodes=[])
    for number, split in enumerate(('train', 'eval', 'test')):
        state = np.arange(30, dtype=np.float32).reshape(6, 5) + number
        arrays = {'observation.state': state, 'action': state / 30}
        for i, camera in enumerate(setup['cameras']):
            key = camera['input_key']
            arrays[key] = np.full((6, *camera['shape']), i + number, dtype=np.uint8)
            if transitions:
                arrays['next.' + key] = arrays[key] + 1
        if transitions:
            arrays['next_state'] = state + 1
            for i, arm in enumerate(setup['arms'][:1] if legacy else setup['arms']):
                prefix = '' if legacy else 'arms.' + arm['id'] + '.'
                arrays[prefix + 'reward'] = np.full(6, 1 if not i else -2, dtype=np.float32)
                arrays[prefix + 'terminated'] = np.array([False] * 5 + [True])
                arrays[prefix + 'truncated'] = np.zeros(6, dtype=bool)
                arrays[prefix + 'is_intervention'] = np.array([True, True, False, False, True, True]) ^ bool(i)
        file = root / (split + '.npz')
        np.savez(file, **arrays)
        document['episodes'].append(dict(id=split, session_id='session-' + split, parent_id='parent-' + split,
                                        split=split, file=file.name, sha256=hashlib.sha256(file.read_bytes()).hexdigest()))
    (root / 'dataset.json').write_text(json.dumps(document))
    return document


@pytest.mark.parametrize('arm_id,indices,reward,camera', [
    ('arm_a', [0, 1, 2], 1, 'observation.images.arm_a_wrist'),
    ('arm_b', [3, 4], -2, 'observation.images.arm_b_wrist')])
def test_independent_view_keeps_exact_columns_signals_cameras_and_source(tmp_path, arm_id, indices, reward, camera):
    from experiment_dataset import load_dataset
    from experiment_profile import profile_revision
    from experiment_scope import select_dataset
    from experiment_train import training_indices
    independent_dataset(tmp_path, source='robot_rollout')
    source = load_dataset(tmp_path, method='hilserl')
    original = copy.deepcopy(source)
    view, scope = select_dataset(source, arm_id, method='hilserl')
    assert [arm['id'] for arm in view.profile['arms']] == [arm_id]
    assert [c['input_key'] for c in view.profile['cameras']] == ['observation.images.top', camera]
    assert view.revision == source.revision and view.source == source.source
    assert scope == dict(mode='independent', arm_ids=[arm_id], source_profile_revision=profile_revision(source.profile),
                         action_indices=indices, camera_keys=['observation.images.top', camera])
    for expected, actual, before in zip(source.episodes, view.episodes, original.episodes):
        assert expected.metadata == actual.metadata == before.metadata
        np.testing.assert_array_equal(actual.arrays['action'], expected.arrays['action'][:, indices])
        np.testing.assert_array_equal(actual.arrays['next_state'], expected.arrays['next_state'][:, indices])
        assert set(actual.arrays) == {'observation.state', 'action', 'next_state', 'reward', 'terminated',
                                     'truncated', 'is_intervention', 'observation.images.top', camera,
                                     'next.observation.images.top', 'next.' + camera}
        assert np.all(actual.arrays['reward'] == reward)
        np.testing.assert_array_equal(actual.arrays['is_intervention'], expected.arrays['arms.' + arm_id + '.is_intervention'])
        for key in expected.arrays:
            np.testing.assert_array_equal(expected.arrays[key], before.arrays[key])
    assert source.profile == original.profile
    indices = training_indices(view, 'act')
    assert [i for _, i in indices] == ([0, 1, 4, 5] if arm_id == 'arm_a' else [2, 3])


def test_missing_unknown_or_cooperative_target_and_group_signal_reuse_refused(tmp_path):
    from experiment_dataset import load_dataset
    from experiment_scope import select_dataset
    document = independent_dataset(tmp_path, legacy=True)
    loaded = load_dataset(tmp_path, method='hilserl')
    for arm_id in (None, 'missing', True):
        with pytest.raises(ValueError, match='arm'):
            select_dataset(loaded, arm_id, method='hilserl')
    with pytest.raises(ValueError, match='arm.*signal'):
        select_dataset(loaded, 'arm_a', method='hilserl')
    document['profile']['mode'] = 'cooperative'
    (tmp_path / 'dataset.json').write_text(json.dumps(document))
    cooperative = load_dataset(tmp_path, method='hilserl')
    with pytest.raises(ValueError, match='cooperative'):
        select_dataset(cooperative, 'arm_a', method='act')
    view, scope = select_dataset(cooperative, method='hilserl')
    assert view is cooperative and scope['action_indices'] == list(range(5))


@pytest.mark.parametrize('bad', ['reward', 'flag', 'overlap', 'missing', 'group_mode'])
def test_per_arm_signals_are_strictly_validated(tmp_path, bad):
    from experiment_dataset import load_dataset
    document = independent_dataset(tmp_path)
    row = document['episodes'][0]
    file = tmp_path / row['file']
    with np.load(file, allow_pickle=False) as archive:
        arrays = dict(archive)
    if bad == 'reward':
        arrays['arms.arm_b.reward'][0] = np.nan
    elif bad == 'flag':
        arrays['arms.arm_b.is_intervention'] = np.ones(6, dtype=np.float32)
    elif bad == 'overlap':
        arrays['arms.arm_b.truncated'][-1] = True
    elif bad == 'missing':
        del arrays['arms.arm_b.reward']
    else:
        document['profile']['mode'] = 'cooperative'
    np.savez(file, **arrays)
    row['sha256'] = hashlib.sha256(file.read_bytes()).hexdigest()
    (tmp_path / 'dataset.json').write_text(json.dumps(document))
    with pytest.raises(ValueError):
        load_dataset(tmp_path, method='hilserl')


def test_independent_reviewed_act_base_does_not_invent_transition_signals(tmp_path):
    from experiment_dataset import load_dataset
    from experiment_scope import select_dataset
    independent_dataset(tmp_path, source='reviewed_demonstration', transitions=False)
    loaded = load_dataset(tmp_path, method='act')
    view, _ = select_dataset(loaded, 'arm_b', method='act')
    assert view.episodes[0].arrays['action'].shape == (6, 2)
    assert 'reward' not in view.episodes[0].arrays
    with pytest.raises(ValueError):
        select_dataset(loaded, 'arm_b', method='hilserl')
