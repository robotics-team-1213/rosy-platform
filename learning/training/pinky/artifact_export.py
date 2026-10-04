"""Bind verified research files to a Pinky PolicyArtifact; no runtime qualification."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import os

import numpy as np
import yaml

from comparison_job import ROOT, metrics, validate_split, read_frames
from verify_raw import verify
from dataset_store import closure
from pinky_episode import ref
from registry import pinky_assessment
from rosy.contracts.learning import seal, validate_dataset, validate_policy
from rosy.contracts.learning.pinky import validate_profile


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, doc):
    path.write_text(json.dumps(doc, indent=2, allow_nan=False), encoding='utf-8')


def source_check(root):
    index = read(root / 'files.json')
    refs = [{'path': name, **value} for name, value in index.items()]
    split = read(root / 'split.json'); sources = split['train'] + [split['eval']]
    manifest = seal({'schema': 'rosy.dataset-manifest/1', 'episodes': [s['episode_revision'] for s in sources],
                     'transformation': {'tool_revision': 'pinky-comparison-source-check',
                                        'config_sha256': hashlib.sha256((root / 'config.json').read_bytes()).hexdigest()},
                     'files': refs})
    validate_dataset(manifest, root=root)
    required = {'config.json', 'split.json', 'normalization.json', 'comparison-report.json',
                'evaluation-predictions.npz', 'tiny_cnn.pt', 'rgb_ridge.npz'}
    required.update(f'raw-verification-{i}.json' for i in range(len(sources)))
    if not required <= set(index):
        raise ValueError('complete comparison source file closure required')
    config = read(root / 'config.json')
    if config['tool_sha256'] != hashlib.sha256((ROOT / 'learning/training/pinky/comparison_job.py').read_bytes()).hexdigest():
        raise ValueError('supported comparison tool hash required')
    if len(config['train_roots']) != len(split['train']):
        raise ValueError('source split count differs')
    validate_split(split['train'], split['eval'])
    roots = [Path(p) for p in config['train_roots'] + [config['eval_root']]]
    actions, episodes, shapes = [], [], []
    for i, (path, source) in enumerate(zip(roots, sources)):
        dataset = closure(path)
        episode = read(path / 'episode.json'); checked = validate_profile(episode, root=path)
        metadata, rows = checked['metadata'], checked['rows']
        raw = read(root / f'raw-verification-{i}.json')
        if (dataset['revision'] != source['dataset_revision'] or episode['revision'] != source['episode_revision']
                or dataset['episodes'] != [episode['revision']] or metadata['source']['session'] != source['source_session']
                or raw['verdict'] != 'pass' or raw['dataset_revision'] != dataset['revision']
                or raw['episode_revision'] != episode['revision'] or raw['frames'] != len(rows)
                or raw['episode_context']['streams'] != episode['streams']
                or source['robot_type'] != episode['robot_type'] or source['environment'] != episode['environment']
                or source['device'] != episode['device']
                or source['raw_bag_sha256'] != [r['sha256'] for r in episode['sources'] if r['path'].endswith('.mcap')]):
            raise ValueError('comparison source binding differs')
        expected = [j for j, row in enumerate(rows) if j % config['stride'] == 0 and row['side'].get('cmd_vel') is not None]
        if expected != source['selected_indices']:
            raise ValueError('selected source frame indices differ')
        actions.append(np.asarray([[rows[j]['side']['cmd_vel']['linear'], rows[j]['side']['cmd_vel']['angular']]
                                   for j in expected], np.float32))
        shapes.append([3, metadata['video']['height'], metadata['video']['width']]); episodes.append(episode)
    if any(shape != shapes[0] for shape in shapes) or any(e['revisions']['camera_profile'] is not None for e in episodes):
        raise ValueError('same source shape and explicitly unknown camera profile required')
    normalization = read(root / 'normalization.json'); train = np.concatenate(actions[:-1])
    if (normalization['source'] != 'train_only' or normalization['rgb_scale'] != 1/255
            or not np.allclose(normalization['action_mean'], train.mean(axis=0), atol=1e-7, rtol=1e-7)
            or not np.allclose(normalization['action_std'], np.maximum(train.std(axis=0), .001), atol=1e-7, rtol=1e-7)):
        raise ValueError('train-only normalization differs')
    comparison = read(root / 'comparison-report.json')
    if (comparison['verdict'] != 'research_only' or comparison['target'] != 'recorded_core_final_velocity'
            or comparison['expert_status'] != 'unverified' or comparison['reloaded_prediction_verified'] is not True
            or comparison['train_frames'] != len(train)):
        raise ValueError('recorded comparison semantics differ')
    with np.load(root / 'evaluation-predictions.npz', allow_pickle=False) as arrays:
        truth = arrays['truth'].copy()
        if not np.array_equal(truth, actions[-1]):
            raise ValueError('evaluation truth differs from recorded commands')
        predictions = {name: arrays[name].copy() for name in ('constant', 'zero', 'rgb_ridge', 'tiny_cnn')}
        for name, values in predictions.items():
            if metrics(truth, values) != comparison['models'][name]:
                raise ValueError('comparison prediction metrics differ')
        if (not np.array_equal(predictions['zero'], np.zeros_like(truth))
                or not np.allclose(predictions['constant'], train.mean(axis=0), atol=1e-7, rtol=1e-7)):
            raise ValueError('comparison baseline differs from train-only data')
    return manifest, config, sources, roots, episodes, shapes[0], truth, predictions, comparison


def replay_model(source, model, evaluation_root, raw, stride, expected):
    import cv2
    import torch
    from torch import nn
    _, images, _, _, _ = read_frames(evaluation_root, raw, stride)
    stats = read(source / 'normalization.json')
    mean = np.asarray(stats['action_mean'], np.float32); std = np.asarray(stats['action_std'], np.float32)
    if model == 'rgb_ridge':
        rgb = np.stack([cv2.resize(im.transpose(1, 2, 0), (8, 6), interpolation=cv2.INTER_AREA).ravel()
                        for im in images]).astype(np.float64)
        features = np.column_stack((rgb, np.ones(len(rgb))))
        with np.load(source / 'rgb_ridge.npz', allow_pickle=False) as weights:
            if not np.array_equal(weights['mean'], mean) or not np.array_equal(weights['std'], std):
                raise ValueError('model normalization differs')
            prediction = (features @ weights['weights']) * std + mean
    else:
        torch.set_num_threads(4)
        network = nn.Sequential(nn.Conv2d(3, 8, 5, stride=2), nn.ReLU(), nn.Conv2d(8, 16, 3, stride=2),
                                nn.ReLU(), nn.AdaptiveAvgPool2d((4, 4)), nn.Flatten(),
                                nn.Linear(256, 32), nn.ReLU(), nn.Linear(32, 2))
        network.load_state_dict(torch.load(source / 'tiny_cnn.pt', weights_only=True))
        network.eval()
        with torch.no_grad():
            prediction = torch.cat([network(chunk) for chunk in torch.from_numpy(images).split(64)]).numpy() * std + mean
    if prediction.shape != expected.shape or not np.allclose(prediction, expected, atol=1e-7, rtol=1e-7):
        raise ValueError('model prediction differs from bound evaluation')


def export(source, output, *, model='tiny_cnn'):
    if model not in ('tiny_cnn', 'rgb_ridge'):
        raise ValueError('supported trained model required')
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists() or output.drive.upper() == 'F:' or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError('new output separate from source and outside F required')
    before, config, sources, roots, episodes, shape, truth, predictions, comparison = source_check(source)
    fresh_raw = [verify(path) for path in roots]
    for result, item in zip(fresh_raw, sources):
        if result['dataset_revision'] != item['dataset_revision'] or result['episode_revision'] != item['episode_revision']:
            raise ValueError('fresh raw derivation source changed')
    replay_model(source, model, roots[-1], read(source / f'raw-verification-{len(sources)-1}.json'),
                 config['stride'], predictions[model])
    profile = ROOT / 'src/products/pinky_pro/profile/config/profile.yaml'
    profile_bytes = profile.read_bytes(); values = yaml.safe_load(profile_bytes)['profile']
    limits = [[-values['max_linear_velocity'], values['max_linear_velocity']],
              [-values['max_angular_velocity'], values['max_angular_velocity']]]
    selected = comparison['models'][model]
    evaluation = {'schema': 'rosy.pinky-offline-eval/1', 'model': model, 'verdict': 'reject',
                  'target': comparison['target'], 'expert_status': 'unverified',
                  'eval_frames': len(truth), 'reloaded_prediction_verified': True,
                  'prediction_limit_violations': int(((predictions[model] < np.asarray(limits)[:, 0]) |
                                                     (predictions[model] > np.asarray(limits)[:, 1])).sum()),
                  'mae_m_s': selected['mae_m_s'], 'mae_rad_s': selected['mae_rad_s'],
                  'dataset_revisions': [s['dataset_revision'] for s in sources],
                  'comparison_report_sha256': hashlib.sha256((source / 'comparison-report.json').read_bytes()).hexdigest()}
    for baseline in ('zero', 'constant'):
        for unit in ('m_s', 'rad_s'):
            evaluation[f'{baseline}_mae_{unit}'] = comparison['models'][baseline][f'mae_{unit}']
    evaluation['assessment'] = pinky_assessment(evaluation)
    weight = 'tiny_cnn.pt' if model == 'tiny_cnn' else 'rgb_ridge.npz'
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.pinky-artifact-', dir=output.parent) as scratch:
        stage = Path(scratch) / 'files'; stage.mkdir()
        names = ['config.json', 'split.json', 'normalization.json', 'comparison-report.json',
                 'evaluation-predictions.npz', weight] + [f'raw-verification-{i}.json' for i in range(len(sources))]
        for name in names:
            shutil.copyfile(source / name, stage / name)
            expected = next(item for item in before['files'] if item['path'] == name)
            if ref(stage / name, stage) != expected:
                raise ValueError('comparison source changed during snapshot')
        (stage / 'nominal-profile.yaml').write_bytes(profile_bytes)
        for name in ('comparison_job.py', 'artifact_export.py'):
            shutil.copyfile(Path(__file__).with_name(name), stage / name)
        write(stage / 'offline-report.json', evaluation)
        for i, result in enumerate(fresh_raw):
            write(stage / f'raw-reverification-{i}.json', result)
        write(stage / 'model-config.json', {'model': model, 'weight_file': weight, 'input': 'RGB_CHW_0_1',
                                           'input_shape': [3, 48, 64], 'ridge_resize_hwc': [6, 8, 3],
                                           'target': 'recorded_core_final_velocity', 'runtime': 'unregistered'})
        policy = seal({'schema': 'rosy.policy-artifact/1', 'profile': 'pinky_base_velocity_v1',
                       'robot_type': 'pinky_pro', 'environment': episodes[0]['environment'],
                       'device_profile_revision': 'nominal-profile-sha256:' + hashlib.sha256(profile_bytes).hexdigest(),
                       'camera_profile_revision': None,
                       'cameras': [{'name': 'front', 'identity': 'declared-topic:camera/front',
                                    'calibration_sha256': None, 'source_shape': shape, 'model_shape': [3, 48, 64],
                                    'color': 'rgb', 'scale': 1/255}],
                       'joint_names': [], 'normalization': ref(stage / 'normalization.json', stage),
                       'observation': {'names': ['rgb_front'], 'units': ['rgb_0_1'], 'shape': [3, 48, 64]},
                       'action': {'names': ['linear_x', 'angular_z'], 'units': ['m/s', 'rad/s'],
                                  'semantics': 'base_velocity_candidate', 'limits': limits},
                       'owner': {'kind': 'pinky_core_command_manager',
                                 'controller_revision': 'unregistered-recorded-velocity-study',
                                 'envelope_revision': 'unregistered-nominal-profile-study'},
                       'timing': {'period_ns': 125_000_000, 'max_observation_age_ns': 250_000_000,
                                  'max_action_age_ns': 125_000_000},
                       'failure_mode': 'hold', 'reset_events': ['stop', 'hold', 'lease_change', 'episode_change'],
                       'dataset_revisions': evaluation['dataset_revisions'],
                       'evaluations': [ref(stage / 'offline-report.json', stage)],
                       'tool_revision': 'sha256:' + hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                       'files': [ref(p, stage) for p in sorted(stage.iterdir()) if p.name not in ('offline-report.json', 'normalization.json')]})
        validate_policy(policy, root=stage)
        if source_check(source)[0] != before:
            raise ValueError('comparison source changed during export')
        for path, item in zip(roots, sources):
            if closure(path)['revision'] != item['dataset_revision']:
                raise ValueError('dataset changed during export')
        write(stage / 'policy-artifact.json', policy)
        os.rename(stage, output)
    return policy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path); parser.add_argument('output', type=Path)
    parser.add_argument('--model', choices=['tiny_cnn', 'rgb_ridge'], default='tiny_cnn')
    args = parser.parse_args()
    policy = export(args.source, args.output, model=args.model)
    print(json.dumps({'policy_revision': policy['revision'], 'model': args.model, 'stage': 'unregistered'}))


if __name__ == '__main__':
    main()
