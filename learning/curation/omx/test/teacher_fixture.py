"""Sealed scripted_teacher collections in the record_seal.py layout of the robot owner's local main (5ceabe6015).

That seal writes no session_id, rig_revision, calibration_revision or calibration/; `revisions=True` adds
them as the later origin seal does. No pytest import: the pinned learner Python also loads this module.
Never evidence of a real recording.
"""
import hashlib
import json
from pathlib import Path
import shutil

NAMES = [f'{joint}.pos' for joint in ('shoulder_pan', 'shoulder_lift', 'elbow_flex', 'wrist_flex', 'wrist_roll', 'gripper')]
SEGMENTS = dict(A=[0, 3], reset=[3, 4], B=[4, 7])
SOURCE = dict(dataset='/home/operator/omx-data/arm-s-demos', episode=3, split_s=2.0, end_s=4.5)
OPERATOR = dict(rig_revision='bench-s-r1', calibration_revision='arm-s-cal-2026-10-25')
# Stand-ins for the absolute site-PC paths and by-id device names a real recording carries.
REPLAY_PATH = '/home/operator/omx-replays/arm-s-cycle-7f3a.json'
SITE_STRINGS = ('/home/', '/dev/serial', '/dev/v4l')


def _hashes(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file() and p != root/'manifest.json'}


def write_manifest(root, manifest):
    """Re-cover every file, as record_seal writes the manifest last; teacher_sha256 is left as given."""
    manifest['files'] = _hashes(root)
    (root/'manifest.json').write_text(json.dumps(manifest, indent=2))
    return manifest


def trajectory(source=SOURCE, segments=SEGMENTS):
    return dict(schema='rosy.omx-replay-trajectory.v1', fps=10, names=NAMES,
                frames=[[0.0]*6] * max(segments['B'][1], 0), source=source, segments=segments)


def seal_teacher(collections, name, dataset=None, *, source=SOURCE, segments=SEGMENTS, teacher=None,
                 revisions=False):
    """`dataset` is a finished LeRobot root to copy; None writes a meta-only stub for manifest checks."""
    root = Path(collections)/name
    if dataset is None:
        (root/'dataset'/'meta').mkdir(parents=True)
        (root/'dataset'/'meta'/'info.json').write_text(json.dumps(dict(codebase_version='v3.0', robot_type='omx_follower')))
    else:
        shutil.copytree(dataset, root/'dataset')
    (root/'teacher').mkdir()
    text = json.dumps(trajectory(source, segments))
    (root/'teacher'/'trajectory.json').write_text(text)
    sha = hashlib.sha256(text.encode('utf-8')).hexdigest()
    (root/'session.json').write_text(json.dumps(dict(
        config='/home/operator/rosy-test/omx-runs/record.json', teleop_only=False, exit_code=0, safe_end=True,
        source_mode='scripted_teacher', replay=dict(path=REPLAY_PATH, sha256=sha, segments=segments, source=source),
        episode_outcomes=[dict(episode=0, segment='A', outcome='unknown'),
                          dict(episode=1, segment='B', outcome='unknown')])))
    (root/'record-config.json').write_text(json.dumps(dict(
        dataset=dict(root='/home/operator/omx-data/arm-s-replay', num_episodes=2, fps=10),
        robot=dict(type='omx_follower', port='/dev/serial/by-id/usb-FAKE_FOLLOWER-if00',
                   cameras=dict(top=dict(type='opencv', index_or_path='/dev/v4l/by-id/usb-FAKE_CAM-video-index0'))),
        teleop=dict(type='omx_leader', port='/dev/serial/by-id/usb-FAKE_LEADER-if00'))))
    manifest = dict(schema='rosy.omx-collection-session.v1', state='CLOSED', mode='hardware',
                    source_mode='scripted_teacher', robot_type='omx_follower', total_episodes=2, sealed_ns=1,
                    teacher_sha256=sha, teacher=dict(kind='replay_trajectory', file='teacher/trajectory.json',
                                                     schema='rosy.omx-replay-trajectory.v1', segments=segments,
                                                     source=source))
    if revisions:
        (root/'calibration').mkdir()
        (root/'calibration'/'arm_s_follower.json').write_text('{"shoulder_pan": {"homing_offset": 0}}')
        rows = sorted((k, v) for k, v in _hashes(root).items() if k.startswith('calibration/'))
        manifest.update(session_id=name, rig_revision=OPERATOR['rig_revision'],
                        calibration_revision=hashlib.sha256(json.dumps(rows).encode('utf-8')).hexdigest())
    manifest['teacher'].update(teacher or {})
    write_manifest(root, manifest)
    return root


def teacher_dataset(root, *, marker=None):
    """A real single-arm omx_follower LeRobot v3 recording with episodes A and B (requires lerobot 0.4.4)."""
    import numpy as np
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    features = {key: dict(dtype='float32', shape=(6,), names=NAMES) for key in ('observation.state', 'action')}
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
