"""Sealed scripted_teacher collections in the record_seal.py layout agreed with the robot owner (0a64b43abc).

No pytest import: the pinned learner Python also loads this module. Never evidence of a real recording.
"""
import hashlib
import json
from pathlib import Path
import shutil

SEGMENTS = dict(A=[0, 3], reset=[3, 4], B=[4, 7])
SOURCE = dict(dataset='local/omx-pick', episode=3, split_s=2.0, end_s=4.5)
REPLAY_PATH = '/home/operator/omx-replays/arm-s-cycle-7f3a.json'  # stands for the absolute site-PC path


def _hashes(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file() and p != root/'manifest.json'}


def write_manifest(root, manifest):
    """Re-cover every file, as record_seal writes the manifest last; teacher_sha256 is left as given."""
    manifest['files'] = _hashes(root)
    (root/'manifest.json').write_text(json.dumps(manifest, indent=2))
    return manifest


def seal_teacher(collections, name, dataset=None, *, source=SOURCE, teacher=None):
    """`dataset` is a finished LeRobot root to copy; None writes a meta-only stub for manifest checks."""
    root = Path(collections)/name
    if dataset is None:
        (root/'dataset'/'meta').mkdir(parents=True)
        (root/'dataset'/'meta'/'info.json').write_text(json.dumps(dict(codebase_version='v3.0', robot_type='omx_follower')))
    else:
        shutil.copytree(dataset, root/'dataset')
    (root/'teacher').mkdir()
    trajectory = json.dumps(dict(schema='rosy.omx-replay-trajectory.v1', fps=10, frames=[[0.0]*6]*7, source=source))
    (root/'teacher'/'trajectory.json').write_text(trajectory)
    sha = hashlib.sha256(trajectory.encode('utf-8')).hexdigest()
    (root/'session.json').write_text(json.dumps(dict(
        config='record.json', teleop_only=False, exit_code=0, safe_end=True, source_mode='scripted_teacher',
        replay=dict(path=REPLAY_PATH, sha256=sha, segments=SEGMENTS, source=source),
        episode_outcomes=[dict(episode=0, segment='A', outcome='unknown'),
                          dict(episode=1, segment='B', outcome='unknown')])))
    (root/'record-config.json').write_text(json.dumps(dict(dataset=dict(root='dataset', num_episodes=2))))
    (root/'calibration').mkdir()
    (root/'calibration'/'arm_s_follower.json').write_text('{"shoulder_pan": {"homing_offset": 0}}')
    files = _hashes(root)
    rows = sorted((k, v) for k, v in files.items() if k.startswith('calibration/'))
    manifest = dict(schema='rosy.omx-collection-session.v1', state='CLOSED', mode='hardware',
                    source_mode='scripted_teacher', robot_type='omx_follower', total_episodes=2, sealed_ns=1,
                    session_id=name, rig_revision='bench-s-r1',
                    calibration_revision=hashlib.sha256(json.dumps(rows).encode('utf-8')).hexdigest(),
                    teacher_sha256=sha, teacher=dict(kind='replay_trajectory', file='teacher/trajectory.json',
                                                     schema='rosy.omx-replay-trajectory.v1', segments=SEGMENTS,
                                                     source=source))
    manifest['teacher'].update(teacher or {})
    write_manifest(root, manifest)
    return root


def teacher_dataset(root, *, marker=None):
    """A real single-arm omx_follower LeRobot v3 recording with episodes A and B (requires lerobot 0.4.4)."""
    import numpy as np
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    names = [f'{joint}.pos' for joint in ('shoulder_pan', 'shoulder_lift', 'elbow_flex', 'wrist_flex', 'wrist_roll', 'gripper')]
    features = {key: dict(dtype='float32', shape=(6,), names=names) for key in ('observation.state', 'action')}
    features['observation.images.top'] = dict(dtype='video', shape=(32, 32, 3), names=['height', 'width', 'channels'])
    dataset = LeRobotDataset.create(repo_id='local/arm-s', fps=10, root=root, robot_type='omx_follower',
                                    features=features, use_videos=True, video_backend='pyav', vcodec='h264',
                                    batch_encoding_size=1)
    try:
        for episode in range(2):
            for frame in range(3):
                dataset.add_frame({'observation.state': np.full(6, episode*10 + frame, np.float32),
                                   'action': np.full(6, episode*10 + frame + .5, np.float32),
                                   'observation.images.top': np.full((32, 32, 3), 40*frame + episode, np.uint8),
                                   'task': 'Move the block from A to B'})
            dataset.save_episode(parallel_encoding=False)
    finally:
        dataset.finalize()
    for name, text in (marker or {}).items():
        (Path(root)/name).write_text(text)
    return root
