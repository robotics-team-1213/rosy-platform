"""Create deterministic synthetic replay for model plumbing, never physical evidence."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from experiment_dataset import load_dataset
from experiment_profile import validate_profile


def generate(output: Path, *, arms=2, cameras=3):
    for name, value, maximum in (('arms', arms, 32), ('cameras', cameras, 64)):
        if type(value) is not int or not 1 <= value <= maximum:
            raise ValueError(f'{name} must be an integer in 1..{maximum}')
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('new synthetic smoke directory required')
    profile = validate_profile({
        'schema': 'rosy.omx.learning-profile/1',
        'name': 'Synthetic smoke only - no physical evidence',
        'mode': 'cooperative' if arms > 1 else 'independent',
        'task': 'Artificial replay checks model updates and save/reload; no real task success',
        'arms': [{'id': f'arm_{index}', 'joint_names': ['shoulder', 'elbow', 'gripper'],
                  'units': 'rad'} for index in range(arms)],
        'cameras': [{'id': f'camera_{index}', 'input_key': f'observation.images.view_{index}',
            'arm_id': None if index == 0 else f'arm_{(index - 1) % arms}',
            'role': 'top' if index == 0 else 'wrist',
            'source_identity': f'synthetic-camera-{index}',
            'placement': f'synthetic-placement-{index}', 'shape': [3, 64, 64],
            'purposes': ['policy', 'record']} for index in range(cameras)],
    })
    document = {'schema': 'rosy.omx.experiment-dataset/1', 'profile': profile,
                'source': 'synthetic_smoke', 'episodes': []}
    output.mkdir(parents=True)
    grid_y, grid_x = np.indices((64, 64))
    for split_index, split in enumerate(('train', 'eval', 'test')):
        phase = np.arange(11, dtype=np.float32)[:, None] * 0.15
        dimensions = np.arange(arms * 3, dtype=np.float32)[None, :] * 0.2
        states = np.sin(phase + dimensions + split_index * 0.3).astype(np.float32)
        arrays = {
            'observation.state': states[:-1].copy(), 'next_state': states[1:].copy(),
            'action': (states[:-1] * 0.6 + 0.1).astype(np.float32),
            'reward': np.linspace(0, 1, 10, dtype=np.float32),
            'terminated': np.array([False] * 9 + [True]),
            'truncated': np.zeros(10, dtype=bool),
            'is_intervention': np.array([False, False, True, True, True,
                                         False, False, True, False, False]),
        }
        for camera_index, camera in enumerate(profile['cameras']):
            frames = np.stack([np.stack([
                (grid_x * (channel + 1) + grid_y + frame * 7
                 + camera_index * 31 + split_index * 17) % 256
                for channel in range(3)]) for frame in range(11)]).astype(np.uint8)
            arrays[camera['input_key']] = frames[:-1].copy()
            arrays['next.' + camera['input_key']] = frames[1:].copy()
        path = output / f'{split}.npz'
        np.savez_compressed(path, **arrays)
        document['episodes'].append({'id': f'synthetic-{split}',
            'session_id': f'synthetic-session-{split}', 'parent_id': f'synthetic-parent-{split}',
            'split': split, 'file': path.name,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    (output / 'dataset.json').write_text(json.dumps(document, indent=2, allow_nan=False), encoding='utf-8')
    # Exercise the same strict reader as real learner requests before reporting fixture readiness.
    loaded = load_dataset(output, method='hilserl')
    return dict(source=loaded.source, physical_learning_verified=False,
                arms=arms, cameras=cameras, frames_per_episode=10,
                splits=['train', 'eval', 'test'], dataset_revision=loaded.revision)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--arms', type=int, default=2)
    parser.add_argument('--cameras', type=int, default=3)
    args = parser.parse_args(argv)
    print(json.dumps(generate(args.out, arms=args.arms, cameras=args.cameras), allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
