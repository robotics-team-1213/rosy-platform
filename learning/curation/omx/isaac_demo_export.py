"""Isaac two-arm demonstrations (D-969) -> ACT experiment dataset (rosy.omx.experiment-dataset/1, source scripted_teacher).

One container is one episode. State and action are both arms, arm_a (fixture arm 0) then arm_b, six joints each in the real
arm's units: body joints by grasp_planner.rad_to_norm (normalized_-100_100) and the gripper as the pad gap over 40 mm x 100
(ASSUMED until the real gripper's 0-100 is measured against the jaw gap). Images are the real top and side views, resized,
plus each arm's wrist camera (arm_a_wrist, arm_b_wrist) when the runs recorded them (wrist-demo cases).
A run's episodes stay in one split (session = parent = run directory name).

  python isaac_demo_export.py OUT RUN_DIR [RUN_DIR ...] [--every 2] [--size 64 48] [--eval-runs 1]
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT/'deploy/robot/omx'), str(ROOT/'middleware/devices/omx/adapter'), str(ROOT/'learning/envs/isaac'),
                str(ROOT/'learning/training/omx')]
from demo_units import OPEN_GAP_M, gap_m, rad_to_norm, to_units as arm_units  # noqa: E402,F401  (re-exported for tests)

JOINTS = ['shoulder_pan.pos', 'shoulder_lift.pos', 'elbow_flex.pos', 'wrist_flex.pos', 'wrist_roll.pos', 'gripper.pos']
CAMERAS = ('top', 'side')
WRIST = ('arm_a_wrist', 'arm_b_wrist')
TASK = 'stack three-cell containers on the ship plate with arm_a and arm_b'  # the policy's task text (act_policy_server)


def cameras(runs):
    """The views every run recorded: top and side, plus both wrist cameras when all runs have them (never a mix)."""
    wrist = {all((run/f'demo-{camera}.mp4').exists() for camera in WRIST) for run in runs}
    if len(wrist) > 1:
        raise ValueError('some runs recorded the wrist cameras and some did not; export them separately')
    return CAMERAS+(WRIST if wrist.pop() else ())


def _camera_entry(camera, size):
    wrist = camera in WRIST
    return dict(id=camera, input_key='observation.images.'+camera, arm_id=camera[:-len('_wrist')] if wrist else None,
                role='front' if wrist else camera,  # D-794: writers still name the wrist camera 'front'
                source_identity='isaac-real-'+camera, placement='wrist' if wrist else 'fixed',
                shape=[3, size[1], size[0]], purposes=['policy', 'record'])


def episodes(run, every, size, views=CAMERAS):
    """(item, state, action, {camera: images}) per container in one run directory, frames subsampled by `every`."""
    rows = [json.loads(line) for line in (run/'demo.jsonl').read_text(encoding='utf-8').splitlines()]
    keep = {}
    for i, row in enumerate(rows):
        if row['item'] is not None:
            keep.setdefault(row['item'], []).append(i)
    keep = {item: index[::every] for item, index in keep.items()}
    wanted = {i for index in keep.values() for i in index}
    frames = {}
    for camera in views:
        video, images, i = cv2.VideoCapture(str(run/f'demo-{camera}.mp4')), {}, 0
        while True:
            ok, bgr = video.read()
            if not ok:
                break
            if i in wanted:
                images[i] = cv2.resize(bgr, size, interpolation=cv2.INTER_AREA)[:, :, ::-1].transpose(2, 0, 1)
            i += 1
        if i != len(rows):
            raise ValueError(f'{run.name}: demo-{camera}.mp4 has {i} frames for {len(rows)} rows')
        frames[camera] = images
    for item, index in sorted(keep.items()):
        yield (item, np.array([arm_units(rows[i]['state']) for i in index], np.float32),
               np.array([arm_units(rows[i]['action']) for i in index], np.float32),
               {camera: np.stack([frames[camera][i] for i in index]).astype(np.uint8) for camera in views})


def export(out, runs, *, every=2, size=(64, 48), eval_runs=1):
    out.mkdir(parents=True)
    views = cameras(runs)
    profile = dict(schema='rosy.omx.learning-profile/1', name='omx-two-arm-container-stack', mode='independent',
                   task=TASK,
                   arms=[dict(id=arm, joint_names=JOINTS[:], units='normalized_-100_100') for arm in ('arm_a', 'arm_b')],
                   cameras=[_camera_entry(camera, size) for camera in views])
    document = dict(schema='rosy.omx.experiment-dataset/1', profile=profile, source='scripted_teacher', episodes=[])
    for k, run in enumerate(runs):
        split = 'eval' if k >= len(runs)-eval_runs else 'train'
        for item, state, action, images in episodes(run, every, size, views):
            name = f'{run.name}-{item}.npz'
            with (out/name).open('xb') as stream:
                np.savez_compressed(stream, **{'observation.state': state, 'action': action},
                                    **{'observation.images.'+camera: images[camera] for camera in views})
            document['episodes'].append(dict(id=f'{run.name}-{item}', session_id=run.name, parent_id=run.name, split=split,
                                             file=name, sha256=hashlib.sha256((out/name).read_bytes()).hexdigest()))
    (out/'dataset.json').write_text(json.dumps(document, indent=1), encoding='utf-8')
    from experiment_dataset import load_dataset
    return load_dataset(out, method='act')


def export_lerobot(out, runs, *, every=1, size=(320, 240), repo_id='rosy/omx-two-arm-container-stack'):
    """The same episodes as a LeRobot 0.4.4 dataset (bi_omx_follower) for the official ACT trainer; read back by count."""
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    names = [f'{arm}.{joint}' for arm in ('arm_a', 'arm_b') for joint in JOINTS]
    views = cameras(runs)
    features = {key: {'dtype': 'float32', 'shape': (12,), 'names': names} for key in ('observation.state', 'action')}
    features.update({'observation.images.'+camera: {'dtype': 'video', 'shape': (3, size[1], size[0]),
                                                   'names': ['channels', 'height', 'width']} for camera in views})
    dataset = LeRobotDataset.create(repo_id=repo_id, fps=10//every, features=features, root=out, robot_type='bi_omx_follower',
                                    use_videos=True, video_backend='pyav', vcodec='h264', batch_encoding_size=1)
    task, count = TASK, 0
    for run in runs:
        for _, state, action, images in episodes(run, every, size, views):
            for i in range(len(state)):
                dataset.add_frame({'observation.state': state[i], 'action': action[i], 'task': task,
                                   **{'observation.images.'+c: images[c][i].transpose(1, 2, 0) for c in views}})
            dataset.save_episode(parallel_encoding=False)
            count += 1
    dataset.finalize()
    reader = LeRobotDataset(repo_id, root=out, video_backend='pyav', download_videos=False)
    if reader.meta.total_episodes != count:
        raise ValueError(f'LeRobot readback has {reader.meta.total_episodes} episodes, wrote {count}')
    return reader


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('out', type=Path)
    parser.add_argument('runs', type=Path, nargs='+')
    parser.add_argument('--every', type=int, default=2, help='keep every n-th 10 Hz frame (2: 5 Hz)')
    parser.add_argument('--size', type=int, nargs=2, default=(64, 48), metavar=('W', 'H'), help='LeRobot use: 320 240')
    parser.add_argument('--eval-runs', type=int, default=1)
    parser.add_argument('--lerobot', action='store_true', help='write a LeRobot 0.4.4 dataset for the official ACT trainer')
    args = parser.parse_args(argv)
    if args.lerobot:
        reader = export_lerobot(args.out, args.runs, every=args.every, size=tuple(args.size))
        print(json.dumps(dict(episodes=reader.meta.total_episodes, frames=reader.meta.total_frames)))
        return
    data = export(args.out, args.runs, every=args.every, size=tuple(args.size), eval_runs=args.eval_runs)
    print(json.dumps(dict(revision=data.revision, episodes=len(data.episodes))))


if __name__ == '__main__':
    main()
