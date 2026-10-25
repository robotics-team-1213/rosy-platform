"""Preflight checks plus opt-in actual pinned LeRobot save/reload integration."""
import importlib.metadata
import copy
import json
import sys
import types
from pathlib import Path

import pytest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_experiment_dataset import dataset


def test_scope_projection_precedes_human_target_selection_and_bounds(tmp_path, monkeypatch):
    from experiment_dataset import load_dataset
    import experiment_train as trainer
    dataset(tmp_path, hil=True)
    original = load_dataset(tmp_path)
    original.source = 'robot_rollout'
    original.split('train')[0].arrays['is_intervention'][:] = False
    view = copy.deepcopy(original)
    view.profile['arms'][0]['joint_names'] = ['elbow', 'gripper']
    for episode in view.episodes:
        episode.arrays['is_intervention'][:] = True
        for key in ('observation.state', 'action', 'next_state'):
            episode.arrays[key] = episode.arrays[key][:, 1:]
    scope = dict(mode='independent', arm_ids=['arm_a'], source_profile_revision='full',
                 action_indices=[1, 2], camera_keys=['observation.images.top'])
    calls = []
    def select(data, arm_id=None, *, method):
        calls.append((data, arm_id, method))
        return view, scope
    monkeypatch.setitem(sys.modules, 'experiment_scope', types.SimpleNamespace(select_dataset=select))
    class ReachedModelImport(Exception):
        pass
    def version(_):
        raise ReachedModelImport
    monkeypatch.setattr(trainer.importlib.metadata, 'version', version)
    with pytest.raises(ReachedModelImport):
        trainer.train_dataset(original, tmp_path / 'output', method='act', steps=1,
            batch_size=2, device='cpu', seed=7, arm_id='arm_a',
            action_bounds=[[-1, 1], [-2, 2], [-3, 3]])
    assert calls == [(original, 'arm_a', 'act')]
    assert not (tmp_path / 'output').exists()


def test_retained_model_rejects_changed_scope_before_optional_import(tmp_path, monkeypatch):
    from experiment_dataset import load_dataset
    import experiment_train as trainer
    dataset(tmp_path, hil=True)
    loaded = load_dataset(tmp_path)
    monkeypatch.setitem(sys.modules, 'experiment_scope', types.SimpleNamespace(
        select_dataset=lambda *args, **kwargs: (loaded, {'arm_ids': ['other']})))
    with pytest.raises(ValueError, match='scope'):
        trainer.train_dataset(loaded, tmp_path / 'output', method='hilserl', steps=1,
            batch_size=2, device='cpu', seed=7, arm_id='other',
            state={'training_scope': {'arm_ids': ['first']}})


def test_train_forwards_optional_arm_id(tmp_path, monkeypatch):
    import experiment_train as trainer
    dataset(tmp_path, hil=True)
    monkeypatch.setattr(trainer, 'train_dataset', lambda data, output, **options: options)
    options = trainer.train(tmp_path, tmp_path.parent / (tmp_path.name + '-out'),
                            arm_id='arm_a', steps=1)
    assert options['arm_id'] == 'arm_a'


@pytest.mark.parametrize('option,value', [('steps', 0), ('batch_size', True),
    ('device', 'auto'), ('method', 'fake'), ('seed', -1)])
def test_train_refuses_invalid_request_before_import_or_output(tmp_path, option, value):
    from experiment_train import train
    options = dict(method='act', steps=1, batch_size=2, device='cpu', seed=1)
    options[option] = value
    with pytest.raises(ValueError):
        train(tmp_path / 'missing', tmp_path / 'output', **options)
    assert not (tmp_path / 'output').exists()


def test_normalization_fits_train_only(tmp_path):
    from experiment_dataset import load_dataset
    from experiment_train import fit_normalization
    dataset(tmp_path)
    stats = fit_normalization(load_dataset(tmp_path))
    assert stats['action']['mean'] == [0, 0, 0]
    assert stats['fit_episodes'] == ['train']


def test_declared_narrow_action_bounds_encode_and_decode_exact_endpoints():
    from experiment_train import transform_action
    normal = {'min': [0.0], 'max': [1e-8]}
    actual = np.array([[0.0], [5e-9], [1e-8]])
    encoded = transform_action(actual, normal, declared=True)
    np.testing.assert_allclose(encoded, [[-1.0], [0.0], [1.0]])
    decoded = transform_action(encoded, normal, inverse=True, declared=True)
    np.testing.assert_allclose(decoded, actual, atol=0, rtol=1e-15)
    assert decoded.max() <= normal['max'][0]


def test_declared_zero_width_is_rejected_and_offline_constant_targets_remain_supported():
    from experiment_train import transform_action
    normal = {'min': [0.0], 'max': [0.0]}
    for inverse in (False, True):
        with pytest.raises(ValueError, match='positive finite width'):
            transform_action(np.zeros(1), normal, inverse=inverse, declared=True)
    assert np.isfinite(transform_action(np.zeros(1), normal)).all()


def test_act_only_supervises_human_segments_of_robot_rollouts(tmp_path):
    from experiment_dataset import load_dataset
    from experiment_train import training_indices
    dataset(tmp_path, hil=True)
    loaded = load_dataset(tmp_path)
    loaded.source = 'robot_rollout'
    assert [i for _, i in training_indices(loaded, 'act')] == [0, 1, 4, 5]
    assert [i for _, i in training_indices(loaded, 'hilserl')] == list(range(6))
    loaded.split('train')[0].arrays['is_intervention'][:] = False
    with pytest.raises(ValueError, match='human'):
        training_indices(loaded, 'act')
    loaded.source = 'reviewed_demonstration'
    assert len(training_indices(loaded, 'act')) == 6


@pytest.mark.parametrize('method', ['act', 'hilserl'])
def test_actual_pinned_models_train_save_reload(tmp_path, method):
    try:
        version = importlib.metadata.version('lerobot')
    except importlib.metadata.PackageNotFoundError:
        pytest.skip('heavy integration requires isolated lerobot==0.4.4 environment')
    if version != '0.4.4':
        pytest.skip('heavy integration requires lerobot==0.4.4')
    from experiment_train import train
    dataset(tmp_path, hil=method == 'hilserl')
    events = []
    result = train(tmp_path, tmp_path.parent / (tmp_path.name + '-output'), method=method,
                   steps=2, batch_size=2, device='cpu', seed=7, progress=events.append)
    assert result['steps'] == 2
    assert result['execution_mode'] == 'offline_replay'
    assert result['physical_learning_verified'] is False
    assert result['evaluation']['frames'] == 6
    assert [event['step'] for event in events] == [1, 2]
    output = tmp_path.parent / (tmp_path.name + '-output')
    assert (output / 'policy/model.safetensors').is_file()
    assert json.loads((output / 'normalization.json').read_text())['fit_episodes'] == ['train']


@pytest.mark.parametrize('method', ['act', 'hilserl'])
def test_actual_independent_arm_models_keep_distinct_width_stats_and_optimizers(tmp_path, method):
    try:
        if importlib.metadata.version('lerobot') != '0.4.4':
            pytest.skip('isolated lerobot==0.4.4 integration required')
    except importlib.metadata.PackageNotFoundError:
        pytest.skip('isolated lerobot==0.4.4 integration required')
    from test_experiment_scope import independent_dataset
    from experiment_dataset import load_dataset
    from experiment_train import train_dataset
    from experiment_profile import policy_cameras, profile_revision
    root = tmp_path / 'dataset'
    root.mkdir()
    independent_dataset(root, source='robot_rollout')
    data = load_dataset(root, method=method)
    states = [{}, {}]
    bounds = [[-1, 1], [-2, 2], [-3, 3], [-4, 4], [-5, 5]]
    for index, arm in enumerate(data.profile['arms']):
        output = tmp_path / ('policy-' + arm['id'])
        result = train_dataset(data, output, method=method, steps=1, batch_size=2,
            device='cpu', seed=7, state=states[index], arm_id=arm['id'], action_bounds=bounds)
        profile = json.loads((output / 'profile.json').read_text())
        normal = json.loads((output / 'normalization.json').read_text())
        request = json.loads((output / 'request.json').read_text())
        columns = [0, 1, 2] if index == 0 else [3, 4]
        assert request['training_scope']['action_indices'] == columns
        assert request['training_scope']['source_profile_revision'] == profile_revision(data.profile)
        assert request['dataset_revision'] == data.revision
        assert len(normal['action']['mean']) == len(columns)
        assert normal['action']['min'] == [-bounds[column][1] for column in columns]
        assert len(profile['arms']) == 1 and profile['arms'][0]['id'] == arm['id']
        assert len(policy_cameras(profile)) == 2
        assert states[index]['model'].config.output_features['action'].shape == (len(columns),)
        assert set(states[index]['model'].config.input_features) == {'observation.state', *policy_cameras(profile)}
        assert result['profile_revision'] == profile_revision(profile)
        if method == 'act':
            expected = int(data.split('train')[0].arrays['arms.' + arm['id'] + '.is_intervention'].sum())
            assert result['supervised_frames'] == expected
        assert result['optimizer_steps'] == 1
        assert set(states[index]['optimizers']) == ({'act'} if method == 'act' else {'actor', 'critic', 'temperature'})
    assert states[0]['model'] is not states[1]['model']
    assert states[0]['optimizers'] is not states[1]['optimizers']
