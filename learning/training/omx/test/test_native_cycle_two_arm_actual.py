"""Opt-in: real LeRobot ACT on the two-arm layout, twelve joints and four cameras; synthetic frames, no robot."""
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

pytest.importorskip('torch', reason='actual numerical model required')
pytest.importorskip('lerobot', reason='pinned local ACT SDK required')
if importlib.metadata.version('lerobot') != '0.4.4':
    pytest.skip('heavy integration requires lerobot==0.4.4', allow_module_level=True)

HERE = Path(__file__).resolve().parents[1]
CAMERAS = ('top', 'side', 'arm_a_wrist', 'arm_b_wrist')


def native_cycle():
    spec = importlib.util.spec_from_file_location('omx_native_cycle', HERE / 'native_cycle.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def record(root, repo_id, names, *, episodes=2, frames=10):
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    features = {key: dict(dtype='float32', shape=(len(names),), names=names) for key in ('action', 'observation.state')}
    features.update({f'observation.images.{camera}': dict(dtype='image', shape=(24, 32, 3),
                                                          names=['height', 'width', 'channels']) for camera in CAMERAS})
    data = LeRobotDataset.create(repo_id, 10, root=root, robot_type='bi_omx_follower', features=features, use_videos=False)
    for episode in range(episodes):
        for frame in range(frames):
            state = np.arange(len(names), dtype=np.float32) + frame + episode
            images = {f'observation.images.{camera}': np.full((24, 32, 3), 40 * index + frame, np.uint8)
                      for index, camera in enumerate(CAMERAS)}
            data.add_frame({'action': state + 1, 'observation.state': state, 'task': 'carry both', **images})
        data.save_episode()
    data.finalize()


def test_actual_act_trains_reloads_and_reports_every_joint_of_both_arms(tmp_path, monkeypatch):
    cycle = native_cycle()
    names = [f'{arm}.{joint}' for arm in ('arm_a', 'arm_b') for joint in cycle.native.JOINTS]
    splits, repo_id = tmp_path / 'splits', 'local/two-arm'
    record(splits / 'train', repo_id + '_train', names)
    record(splits / 'eval', repo_id + '_eval', names, episodes=1)
    config = json.loads((HERE / 'native-act.example.json').read_text())
    config['dataset'].update(root=str(splits / 'train'), repo_id=repo_id + '_train')
    config.update(output_dir=str(tmp_path / 'trainer'), steps=2, save_freq=2, batch_size=2, log_freq=1)
    (tmp_path / 'config.json').write_text(json.dumps(config))
    subprocess.run([sys.executable, '-m', 'lerobot.scripts.lerobot_train', f'--config_path={tmp_path / "config.json"}'],
                   check=True, env={**os.environ, 'HF_HUB_OFFLINE': '1', 'HF_DATASETS_OFFLINE': '1'})
    model = tmp_path / 'trainer/checkpoints/last/pretrained_model'
    saved = json.loads((model / 'config.json').read_text())
    assert saved['output_features']['action']['shape'] == [12]
    assert sum(feature['type'] == 'VISUAL' for feature in saved['input_features'].values()) == 4
    # Only the sealed receipt is replaced: the reader, the reload and the evaluation loop are the real ones.
    monkeypatch.setattr(cycle, 'validate_split', lambda root: dict(source=dict(repo_id=repo_id), decisions=[]))
    monkeypatch.setattr(cycle.native, 'validate_environment', lambda source: {})
    monkeypatch.setattr(cycle.native, 'split_coverage', lambda environment, decisions: {})
    cycle._evaluate_inputs(model, splits, repo_id, tmp_path / 'evaluation.json')
    evaluation = json.loads((tmp_path / 'evaluation.json').read_text())
    assert evaluation['joint_names'] == names and evaluation['samples'] == 10
    assert len(evaluation['mae_per_joint']) == 12 and all(np.isfinite(evaluation['mae_per_joint']))
