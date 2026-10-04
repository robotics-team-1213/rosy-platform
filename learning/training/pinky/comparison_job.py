"""CPU image-to-recorded-velocity study; never expert certification or runtime authority."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'learning/curation/pinky'))
from verify_raw import verify
from rosy.contracts.learning.pinky import validate_profile


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')


def validate_split(train, evaluation):
    all_sources = [*train, evaluation]
    if len(train) < 2:
        raise ValueError('two train and one disjoint eval sessions required')
    for key in ('dataset_revision', 'episode_revision', 'source_session'):
        if len({item[key] for item in all_sources}) != len(all_sources):
            raise ValueError('disjoint dataset/Episode/source sessions required')
    seen = set()
    for source in all_sources:
        bags = set(source['raw_bag_sha256'])
        if not bags or bags & seen:
            raise ValueError('disjoint nonempty raw content required')
        seen.update(bags)
    if any((s['robot_type'], s['environment']) != ('pinky_pro', all_sources[0]['environment'])
           for s in all_sources):
        raise ValueError('same Pinky robot/environment required')


def metrics(truth, prediction):
    truth, prediction = np.asarray(truth), np.asarray(prediction)
    if (truth.shape != prediction.shape or truth.ndim != 2 or truth.shape[1] != 2 or not len(truth)
            or not np.isfinite(truth).all() or not np.isfinite(prediction).all()):
        raise ValueError('matching nonempty finite velocity arrays required')
    errors = np.abs(truth - prediction)
    moving = (np.abs(truth[:, 0]) > .01) | (np.abs(truth[:, 1]) > .05)
    result = {'mae_m_s': float(errors[:, 0].mean()), 'mae_rad_s': float(errors[:, 1].mean()),
              'eval_frames': len(truth), 'moving_frames': int(moving.sum()),
              'stop_frames': int((~moving).sum())}
    for label, mask in (('moving', moving), ('stop', ~moving)):
        for i, unit in enumerate(('m_s', 'rad_s')):
            result[f'{label}_mae_{unit}'] = float(errors[mask, i].mean()) if mask.any() else None
            result[f'{label}_prediction_abs_{unit}'] = float(np.abs(prediction[mask, i]).mean()) if mask.any() else None
    return result


def fit_models(images, actions, evaluation, out, *, steps, seed):
    import cv2
    import torch
    from torch import nn
    torch.set_num_threads(4); torch.manual_seed(seed)
    mean = actions.mean(axis=0); std = np.maximum(actions.std(axis=0), .001)
    write(out / 'normalization.json', {'action_mean': mean.tolist(), 'action_std': std.tolist(),
                                      'source': 'train_only', 'rgb_scale': 1/255})
    predictions = {'constant': np.broadcast_to(mean, (len(evaluation), 2)).copy(),
                   'zero': np.zeros((len(evaluation), 2))}

    def features(values):
        rgb = np.stack([cv2.resize(im.transpose(1, 2, 0), (8, 6), interpolation=cv2.INTER_AREA).ravel()
                        for im in values]).astype(np.float64)
        return np.column_stack((rgb, np.ones(len(rgb))))

    x = features(images); xe = features(evaluation)
    penalty = np.eye(x.shape[1]) * 10.; penalty[-1, -1] = 0
    weights = np.linalg.solve(x.T @ x + penalty, x.T @ ((actions - mean) / std))
    predictions['rgb_ridge'] = (xe @ weights) * std + mean
    np.savez(out / 'rgb_ridge.npz', weights=weights, mean=mean, std=std)
    with np.load(out / 'rgb_ridge.npz', allow_pickle=False) as saved:
        np.testing.assert_allclose((xe @ saved['weights']) * saved['std'] + saved['mean'],
                                   predictions['rgb_ridge'], atol=1e-7, rtol=1e-7)

    def model():
        return nn.Sequential(nn.Conv2d(3, 8, 5, stride=2), nn.ReLU(), nn.Conv2d(8, 16, 3, stride=2),
                             nn.ReLU(), nn.AdaptiveAvgPool2d((4, 4)), nn.Flatten(),
                             nn.Linear(256, 32), nn.ReLU(), nn.Linear(32, 2))

    cnn = model(); optimizer = torch.optim.Adam(cnn.parameters(), lr=.001)
    tensor = torch.from_numpy(images); target = torch.from_numpy(((actions - mean) / std).astype(np.float32))
    losses = []
    generator = torch.Generator().manual_seed(seed)
    for _ in range(steps):
        indices = torch.randint(len(images), (32,), generator=generator)
        loss = nn.functional.mse_loss(cnn(tensor[indices]), target[indices])
        if not torch.isfinite(loss):
            raise ValueError('nonfinite training loss')
        optimizer.zero_grad(); loss.backward(); optimizer.step(); losses.append(float(loss.detach()))
    torch.save(cnn.state_dict(), out / 'tiny_cnn.pt')
    reloaded = model(); reloaded.load_state_dict(torch.load(out / 'tiny_cnn.pt', weights_only=True))
    cnn.eval(); reloaded.eval()
    with torch.no_grad():
        values = torch.from_numpy(evaluation)
        pred = torch.cat([cnn(chunk) for chunk in values.split(64)]).numpy()
        restored = torch.cat([reloaded(chunk) for chunk in values.split(64)]).numpy()
    np.testing.assert_allclose(restored, pred, atol=1e-7, rtol=1e-7)
    predictions['tiny_cnn'] = pred * std + mean
    write(out / 'history.json', {'loss': losses})
    return predictions


def read_frames(root, report, stride):
    import cv2
    episode = json.loads((root / 'episode.json').read_text(encoding='utf-8'))
    checked = validate_profile(episode, root=root)
    metadata, rows = checked['metadata'], checked['rows']
    source = {'dataset_revision': report['dataset_revision'], 'episode_revision': report['episode_revision'],
              'source_session': metadata['source']['session'], 'robot_type': episode['robot_type'],
              'environment': episode['environment'], 'device': episode['device'],
              'raw_bag_sha256': [ref['sha256'] for ref in episode['sources'] if ref['path'].endswith('.mcap')]}
    capture = cv2.VideoCapture(str(root / 'source/video' / metadata['video']['file']))
    images, actions, indices = [], [], []
    missing = 0
    try:
        for i, row in enumerate(rows):
            ok, image = capture.read()
            if not ok:
                raise ValueError('video truncated during model input read')
            if i % stride:
                continue
            cmd = row['side'].get('cmd_vel')
            if cmd is None:
                missing += 1; continue
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            images.append(cv2.resize(rgb, (64, 48), interpolation=cv2.INTER_AREA).transpose(2, 0, 1))
            actions.append([cmd['linear'], cmd['angular']]); indices.append(i)
    finally:
        capture.release()
    if not images:
        raise ValueError('no usable recorded command frames')
    return source, np.asarray(images, np.float32) / 255., np.asarray(actions, np.float32), indices, missing


def run(train, evaluation, out, *, steps=40, seed=42760, stride=4):
    if type(steps) is not int or not 1 <= steps <= 10000 or type(stride) is not int or not 1 <= stride <= 32:
        raise ValueError('bounded integer steps/stride required')
    roots = [Path(p).resolve() for p in [*train, evaluation]]; out = Path(out).resolve()
    if out.exists() or out.drive.upper() == 'F:' or any(out.is_relative_to(p) or p.is_relative_to(out) for p in roots):
        raise ValueError('new output outside F and separate from source required')
    out.mkdir(parents=True)
    try:
        config = {'steps': steps, 'seed': seed, 'stride': stride, 'ridge_penalty': 10.,
                  'model_shape': [3, 48, 64], 'ridge_shape': [3, 6, 8], 'device': 'cpu',
                  'train_roots': [str(p) for p in roots[:-1]], 'eval_root': str(roots[-1]),
                  'tool_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
        config['packages'] = {name: importlib.metadata.version(name) for name in ('numpy', 'torch', 'opencv-python-headless')}
        write(out / 'config.json', config)
        arrays, sources = [], []
        for i, root in enumerate(roots):
            report = verify(root)
            write(out / f'raw-verification-{i}.json', report)
            source, images, actions, indices, missing = read_frames(root, report, stride)
            source.update(selected_indices=indices, missing_command_frames=missing)
            sources.append(source); arrays.append((images, actions))
        validate_split(sources[:-1], sources[-1])
        write(out / 'split.json', {'schema': 'rosy.pinky-research-split/1', 'train': sources[:-1], 'eval': sources[-1]})
        train_images = np.concatenate([a[0] for a in arrays[:-1]])
        train_actions = np.concatenate([a[1] for a in arrays[:-1]])
        predictions = fit_models(train_images, train_actions, arrays[-1][0], out, steps=steps, seed=seed)
        np.savez(out / 'evaluation-predictions.npz', truth=arrays[-1][1], **predictions)
        report = {'schema': 'rosy.pinky-behavior-comparison/1', 'verdict': 'research_only',
                  'target': 'recorded_core_final_velocity', 'expert_status': 'unverified',
                  'train_frames': len(train_actions), 'eval_frames': len(arrays[-1][1]),
                  'models': {name: metrics(arrays[-1][1], pred) for name, pred in predictions.items()},
                  'reloaded_prediction_verified': True,
                  'holds': ['camera_identity_calibration', 'expert_intent', 'pixel_provenance',
                            'owner_contract', 'independent_task_acceptance'], 'promotion': 'not_eligible'}
        write(out / 'comparison-report.json', report)
        from dataset_store import closure
        for root, source in zip(roots, sources):
            if closure(root)['revision'] != source['dataset_revision']:
                raise ValueError('dataset changed during model run')
        files = [p for p in out.iterdir() if p.is_file()]
        write(out / 'files.json', {p.name: {'sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
                                          'bytes': p.stat().st_size} for p in files})
        write(out / 'state.json', {'status': 'research_exported', 'promotion': 'not_eligible'})
        return report
    except BaseException as exc:
        write(out / 'state.json', {'status': 'failed', 'error': f'{type(exc).__name__}: {exc}'})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--train', nargs='+', type=Path, required=True)
    parser.add_argument('--eval', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--steps', type=int, default=40)
    parser.add_argument('--seed', type=int, default=42760)
    parser.add_argument('--stride', type=int, default=4)
    args = parser.parse_args()
    print(json.dumps(run(args.train, args.eval, args.out, steps=args.steps, seed=args.seed, stride=args.stride)))


if __name__ == '__main__':
    main()
