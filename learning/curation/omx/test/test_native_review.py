import copy
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def module():
    path = Path(__file__).resolve().parents[1] / 'native_review.py'
    assert path.is_file(), 'native dataset review is not implemented'
    spec = importlib.util.spec_from_file_location('omx_native_review', path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.fixture
def recording():
    names = ['shoulder_pan.pos', 'shoulder_lift.pos', 'elbow_flex.pos',
             'wrist_flex.pos', 'wrist_roll.pos', 'gripper.pos']
    features = {name: {'dtype': 'float32', 'shape': [6], 'names': names}
                for name in ('action', 'observation.state')}
    features['observation.images.front'] = {'dtype': 'video', 'shape': [2, 2, 3]}
    info = {'robot_type': 'omx_follower', 'codebase_version': 'v3.0', 'fps': 30,
            'total_frames': 4, 'total_episodes': 2, 'features': features}
    rows = []
    for episode in range(2):
        for frame in range(2):
            rows.append({'episode_index': episode, 'frame_index': frame,
                         'timestamp': frame / 30, 'action': [episode] * 6,
                         'observation.state': [episode] * 6,
                         'observation.images.front': [[[0.0] * 2 for _ in range(2)] for _ in range(3)],
                         'task': 'Pick the cube'})
    return info, rows


def test_review_does_not_infer_task_success(module, recording):
    info, rows = recording
    report = module.inspect_frames(info, iter(rows))
    assert report['frame_count'] == 4
    assert [e['outcome'] for e in report['episodes']] == ['unknown', 'unknown']
    assert all(e['split'] == 'exclude' for e in report['episodes'])
    assert all(len(e['content_sha256']) == 64 for e in report['episodes'])


@pytest.mark.parametrize('fault', ['nan', 'missing_camera', 'time', 'order', 'length', 'sim'])
def test_review_rejects_incomplete_or_incompatible_data(module, recording, fault):
    info, rows = recording
    if fault == 'nan': rows[1]['action'][0] = float('nan')
    if fault == 'missing_camera': del rows[1]['observation.images.front']
    if fault == 'time': rows[1]['timestamp'] = 0
    if fault == 'order': info['features']['action']['names'] = list(reversed(info['features']['action']['names']))
    if fault == 'length': rows.pop()
    if fault == 'sim': info['robot_type'] = 'omx_sim_ros'
    with pytest.raises(ValueError):
        module.inspect_frames(info, iter(rows))


def test_reviewed_splits_require_success_and_independent_content(module, recording):
    report = module.inspect_frames(*recording)
    decisions = copy.deepcopy(report['episodes'])
    for episode, split in zip(decisions, ('train', 'eval')):
        episode.update(outcome='success', split=split, reviewer='operator', reason='verified')
    assert module.reviewed_splits(report, decisions) == {'train': [0], 'eval': [1]}
    decisions[1]['outcome'] = 'unknown'
    with pytest.raises(ValueError, match='success'):
        module.reviewed_splits(report, decisions)


def test_duplicate_episode_content_cannot_cross_splits(module, recording):
    info, rows = recording
    rows[2]['action'] = rows[0]['action'][:]
    rows[3]['action'] = rows[1]['action'][:]
    rows[2]['observation.state'] = rows[0]['observation.state'][:]
    rows[3]['observation.state'] = rows[1]['observation.state'][:]
    report = module.inspect_frames(info, rows)
    decisions = copy.deepcopy(report['episodes'])
    for episode, split in zip(decisions, ('train', 'eval')):
        episode.update(outcome='success', split=split, reviewer='operator', reason='verified')
    with pytest.raises(ValueError, match='duplicate'):
        module.reviewed_splits(report, decisions)


def test_modified_review_identity_is_rejected(module, recording):
    report = module.inspect_frames(*recording)
    decisions = copy.deepcopy(report['episodes'])
    decisions[0]['content_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='identity'):
        module.reviewed_splits(report, decisions)
