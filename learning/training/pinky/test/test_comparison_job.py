import json
from pathlib import Path
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'learning/training/pinky'))
from comparison_job import validate_split, metrics, fit_models, run


def source(revision, session):
    return {'dataset_revision': revision, 'episode_revision': revision,
            'source_session': session, 'robot_type': 'pinky_pro', 'environment': 'real',
            'raw_bag_sha256': [revision]}


def test_repackaged_session_cannot_leak_into_eval():
    with pytest.raises(ValueError, match='disjoint'):
        validate_split([source('a', 'one'), source('b', 'two')], source('c', 'one'))


def test_renamed_source_with_same_raw_bag_cannot_leak_into_eval():
    with pytest.raises(ValueError, match='raw content'):
        validate_split([source('a', 'one'), source('b', 'two')],
                       {**source('c', 'renamed'), 'raw_bag_sha256': ['a']})


def test_different_robot_or_environment_rejected():
    with pytest.raises(ValueError, match='robot/environment'):
        validate_split([source('a', 'one'), source('b', 'two')],
                       {**source('c', 'three'), 'environment': 'sim'})


def test_channel_units_and_stop_subset_are_separate():
    result = metrics(np.array([[0., 0.], [.1, .4]]), np.array([[.1, .2], [.1, .2]]))
    assert result['mae_m_s'] == pytest.approx(.05)
    assert result['mae_rad_s'] == pytest.approx(.2)
    assert result['moving_frames'] == result['stop_frames'] == 1
    assert result['stop_prediction_abs_m_s'] == pytest.approx(.1)
    assert result['moving_mae_m_s'] == 0


def test_nonfinite_prediction_rejected():
    with pytest.raises(ValueError, match='finite'):
        metrics(np.zeros((2, 2)), np.array([[0., 0.], [np.nan, 0.]]))


def test_native_model_save_reload(tmp_path):
    pytest.importorskip('torch')
    rng = np.random.default_rng(7)
    images = rng.random((12, 3, 48, 64), dtype=np.float32)
    actions = np.column_stack((images[:, 0].mean(axis=(1, 2)), images[:, 1].mean(axis=(1, 2))))
    predictions = fit_models(images[:8], actions[:8], images[8:], tmp_path, steps=2, seed=7)
    assert set(predictions) == {'constant', 'zero', 'rgb_ridge', 'tiny_cnn'}
    for values in predictions.values():
        assert values.shape == (4, 2) and np.isfinite(values).all()
    stats = json.loads((tmp_path / 'normalization.json').read_text())
    np.testing.assert_allclose(stats['action_mean'], actions[:8].mean(axis=0))
    assert (tmp_path / 'tiny_cnn.pt').is_file() and (tmp_path / 'rgb_ridge.npz').is_file()


def test_native_three_session_job_from_real_mcap(tmp_path):
    pytest.importorskip('torch'); pytest.importorskip('mcap_ros2')
    sys.path.insert(0, str(ROOT / 'learning/curation/pinky/test'))
    from test_raw_mcap import native_recording
    from pinky_episode import convert
    datasets = []
    for i in range(3):
        base = tmp_path / str(i); base.mkdir()
        raw, meta = native_recording(base, raw_linear=.02 + .01 * i)
        named = raw.with_name(f'capture{i}'); raw.rename(named)
        metadata = json.loads(meta.read_text())
        metadata['source']['session'] = named.name
        meta.write_text(json.dumps(metadata))
        side = meta.with_suffix('.jsonl')
        rows = [json.loads(line) for line in side.read_text().splitlines()]
        for row in rows:
            row['side']['cmd_vel']['linear'] = .02 + .01 * i
        side.write_text('\n'.join(json.dumps(row) for row in rows))
        dataset = base / 'common'
        convert(named, meta, dataset, environment='sim', clock_domain='gazebo_sim')
        datasets.append(dataset)
    result = run(datasets[:2], datasets[-1], tmp_path / 'job', steps=2, seed=7, stride=1)
    assert result['train_frames'] == 4 and result['eval_frames'] == 2
    assert result['verdict'] == 'research_only' and result['promotion'] == 'not_eligible'
    state = json.loads((tmp_path / 'job/state.json').read_text())
    assert state['status'] == 'research_exported'
    assert not (tmp_path / 'job/policy-artifact.json').exists()
