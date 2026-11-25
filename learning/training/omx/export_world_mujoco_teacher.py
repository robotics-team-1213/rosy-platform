"""Export a new MuJoCo cell teacher dataset for the World offline ACT preset."""
import argparse
import hashlib
from pathlib import Path
import sys

import numpy as np

from experiment_dataset import load_dataset
from experiment_io import write_json

CAMERAS = ('top', 'wrist')
CAMERA_SHAPE = (3, 60, 80)
TRAIN_SEEDS = range(1000, 1032)
EVAL_SEEDS = range(100000, 100032)


def _collect(cell, seed):
    data, xy, yaw = cell.reset(seed)
    frames = {key: [] for key in ('observation.state', 'action',
                                  *(f'observation.images.{name}' for name in CAMERAS))}
    peak = 0.0
    for target in cell.teacher(data, xy, yaw):
        for name, image in zip(CAMERAS, cell.views(data), strict=True):
            pixels = image[::4, ::4].transpose(2, 0, 1)
            if pixels.shape != CAMERA_SHAPE or pixels.dtype != np.uint8:
                raise ValueError('MuJoCo RGB camera shape differs from the export profile')
            frames[f'observation.images.{name}'].append(pixels.copy())
        frames['observation.state'].append(data.qpos[cell.qadr].astype(np.float32))
        frames['action'].append(np.array(target, dtype=np.float32, copy=True))
        cell.advance(data, target)
        peak = max(peak, float(data.body('box').xpos[2]))
    if cell.judge(data, peak)['strict']:
        return {key: np.stack(values) for key, values in frames.items()}
    return None


def export(cell, scene_sha256, output, joint_names, task, train_count, eval_count):
    if not all(type(count) is int and 1 <= count <= 8 for count in (train_count, eval_count)):
        raise ValueError('one to eight episodes are required in each split')
    output = Path(output).resolve()
    if any((parent / '.git').exists() for parent in (output, *output.parents)):
        raise ValueError('export belongs outside the code checkout')
    output.mkdir(parents=True)
    profile = dict(schema='rosy.omx.learning-profile/1', name='MuJoCo OMX cell teacher',
                   mode='independent', task=task,
                   arms=[dict(id='arm_b', joint_names=list(joint_names), units='rad')],
                   cameras=[dict(id=name, input_key=f'observation.images.{name}',
                                 arm_id='arm_b' if name == 'wrist' else None, role=name,
                                 source_identity=f'mujoco:{scene_sha256}:{name}',
                                 placement='on_arm' if name == 'wrist' else 'fixed',
                                 shape=list(CAMERA_SHAPE), purposes=['policy', 'record'])
                            for name in CAMERAS])
    manifest = dict(schema='rosy.omx.experiment-dataset/1', profile=profile,
                    source='scripted_teacher', episodes=[])
    attempts = []
    for split, candidates, count in (('train', TRAIN_SEEDS, train_count), ('eval', EVAL_SEEDS, eval_count)):
        accepted = 0
        for seed in candidates:
            frames = _collect(cell, seed)
            attempts.append(dict(split=split, seed=seed, strict_pass=frames is not None))
            if frames is None:
                continue
            episode = f'mujoco-{seed}'
            path = output / f'{episode}.npz'
            with path.open('xb') as stream:
                np.savez_compressed(stream, **frames)
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            manifest['episodes'].append(dict(id=episode, session_id=episode, parent_id=episode,
                                            split=split, file=path.name, sha256=digest))
            accepted += 1
            if accepted == count:
                break
        if accepted != count:
            raise ValueError(f'MuJoCo teacher accepted {accepted} of {count} requested {split} episodes')
    write_json(output / 'dataset.json', manifest)
    dataset = load_dataset(output)
    receipt = dict(schema='rosy.omx.mujoco-teacher-conversion/1', dataset_origin='mujoco',
                   scene_sha256=scene_sha256, dataset_revision=dataset.revision, attempts=attempts,
                   physical_acceptance=False)
    write_json(output / 'conversion-receipt.json', receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cell', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--train-episodes', type=int, default=2)
    parser.add_argument('--eval-episodes', type=int, default=2)
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'tools' / 'sim'))
    from omx_cell_sim import Cell, JOINTS, TASK, mujoco

    cell = Cell(args.cell.resolve(strict=True))
    try:
        model_bytes = np.empty(mujoco.mj_sizeModel(cell.model), dtype=np.uint8)
        mujoco.mj_saveModel(cell.model, None, model_bytes)
        receipt = export(cell, hashlib.sha256(model_bytes).hexdigest(), args.out, JOINTS, TASK,
                         args.train_episodes, args.eval_episodes)
        print(f'Scene {receipt["scene_sha256"]}\nDataset {receipt["dataset_revision"]}')
    finally:
        cell.renderer.close()
        cell.meshes.cleanup()


if __name__ == '__main__':
    main()
