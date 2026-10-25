import copy
import json
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


@pytest.mark.parametrize('linked_worktree', [False, True])
def test_outputs_stay_outside_checkouts_and_preserve_source(module, tmp_path, linked_worktree):
    checkout, source = tmp_path / 'checkout', tmp_path / 'source'
    checkout.mkdir()
    marker = checkout / '.git'
    if linked_worktree:
        marker.write_text('gitdir: elsewhere', encoding='utf-8')
    else:
        marker.mkdir()
    output = checkout / 'new' / 'output'
    assert module._in_checkout(output)
    with pytest.raises(ValueError, match='checkout'):
        module._new_output(output, source)
    assert not output.exists()
    for overlap in (source, source / 'nested', tmp_path):
        with pytest.raises(ValueError, match='separate'):
            module._new_output(overlap, source)
    external = tmp_path / 'external'
    assert not module._in_checkout(external)
    assert module._new_output(external, source) == external.resolve()
    external.mkdir()
    with pytest.raises(ValueError, match='already exists'):
        module._new_output(external, source)


def test_reader_tuple_shapes_are_supported(module, recording):
    info, rows = recording
    for feature in info['features'].values():
        feature['shape'] = tuple(feature['shape'])
    assert module.inspect_frames(info, rows)['frame_count'] == 4


@pytest.mark.parametrize('fault', [None, 'arm_order', 'state_order', 'short_frame', 'wrong_type'])
def test_bimanual_native_layout_is_explicit_and_ordered(module, recording, fault):
    info, rows = recording
    names = [f'{arm}.{joint}' for arm in ('arm_a', 'arm_b') for joint in module.JOINTS]
    info['robot_type'] = 'bi_omx_follower'
    for key in ('action', 'observation.state'):
        info['features'][key].update(names=names[:], shape=[12])
        for row in rows:
            row[key] = row[key] * 2
    if fault == 'arm_order':
        info['features']['action']['names'] = names[6:] + names[:6]
    if fault == 'state_order':
        info['features']['observation.state']['names'] = list(reversed(names))
    if fault == 'short_frame':
        rows[0]['action'].pop()
    if fault == 'wrong_type':
        info['robot_type'] = 'omx_follower'
    if fault:
        with pytest.raises(ValueError):
            module.inspect_frames(info, rows)
    else:
        report = module.inspect_frames(info, rows)
        assert report['robot_type'] == 'bi_omx_follower'
        assert report['joint_names'] == names
        assert report['frame_count'] == 4


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


def test_object_result_is_a_bounded_label_and_not_a_split_rule(module, recording):
    report = module.inspect_frames(*recording)
    assert all(e['object_result'] == 'unknown' for e in report['episodes'])
    decisions = copy.deepcopy(report['episodes'])
    for episode, split in zip(decisions, ('train', 'eval')):
        episode.update(outcome='success', split=split, reviewer='operator', reason='verified')
    decisions[0]['object_result'] = 'moved_as_intended'
    del decisions[1]['object_result']
    assert module.reviewed_splits(report, decisions) == {'train': [0], 'eval': [1]}
    decisions[1]['object_result'] = 'slipped a bit'
    with pytest.raises(ValueError, match='object_result'):
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


def test_inspection_does_not_invent_leader_source(module, recording, monkeypatch, tmp_path):
    from types import SimpleNamespace
    info, rows = recording
    class Dataset(list):
        meta = SimpleNamespace(info=info)
    monkeypatch.setattr(module, 'dataset_files', lambda root: {'meta/info.json': 'a' * 64})
    monkeypatch.setattr(module, 'load_dataset', lambda *args: Dataset(rows))
    report = module.inspect_dataset(tmp_path, 'local/data', body_units='normalized_-100_100',
                                    rig_revision='rig', calibration_revision='cal')
    assert report['source_mode'] == 'unverified_native'


def test_unknown_capture_is_not_eligible_for_reviewed_training(module, recording):
    report = module.inspect_frames(*recording)
    report['source_mode'] = 'unverified_native'
    decisions = copy.deepcopy(report['episodes'])
    for episode, split in zip(decisions, ('train', 'eval')):
        episode.update(outcome='success', split=split, reviewer='operator', reason='verified')
    with pytest.raises(ValueError, match='source'):
        module.reviewed_splits(report, decisions)


def test_collection_session_cannot_cross_reviewed_splits(module, recording):
    report = module.inspect_frames(*recording)
    for episode in report['episodes']:
        episode.update(session_id='same-session', cycle_id=f"cycle-{episode['episode_index']}")
    decisions = copy.deepcopy(report['episodes'])
    for episode, split in zip(decisions, ('train', 'eval')):
        episode.update(outcome='success', split=split, reviewer='operator', reason='verified')
    with pytest.raises(ValueError, match='session_id'):
        module.reviewed_splits(report, decisions)


def test_optional_final_test_split_stays_separate(module, recording):
    report = module.inspect_frames(*recording)
    third = copy.deepcopy(report['episodes'][1])
    third.update(episode_index=2, content_sha256='c' * 64)
    report['episodes'].append(third)
    decisions = copy.deepcopy(report['episodes'])
    for episode, split in zip(decisions, ('train', 'eval', 'test')):
        episode.update(outcome='success', split=split, reviewer='operator', reason='verified')
    assert module.reviewed_splits(report, decisions) == {'train': [0], 'eval': [1], 'test': [2]}


def test_source_changed_during_split_cannot_receive_a_success_receipt(module, recording, monkeypatch, tmp_path):
    import sys
    from types import SimpleNamespace
    info, rows = recording
    report = module.inspect_frames(info, rows)
    report.update(repo_id='local/source', body_units='normalized_-100_100', rig_revision='rig',
                  calibration_revision='cal', source_mode='leader_native', files={'meta/info.json': 'a' * 64})
    decisions = copy.deepcopy(report['episodes'])
    for decision, name in zip(decisions, ('train', 'eval')):
        decision.update(split=name, outcome='success', reviewer='operator', reason='checked')
    source, output = tmp_path/'source', tmp_path/'output'
    changed = []
    class Dataset(list):
        meta = SimpleNamespace(info=info)
    def split_dataset(*args, **kwargs):
        changed.append(True)
        return {name: SimpleNamespace(repo_id=f'local/source_{name}') for name in ('train', 'eval')}
    monkeypatch.setitem(sys.modules, 'lerobot.datasets.dataset_tools', SimpleNamespace(split_dataset=split_dataset))
    monkeypatch.setattr(module, 'inspect_dataset', lambda *args, **kwargs: report)
    monkeypatch.setattr(module, 'load_dataset', lambda *args: Dataset(rows))
    monkeypatch.setattr(module, 'dataset_files', lambda root: {'meta/info.json': ('b' if changed else 'a') * 64})
    with pytest.raises(ValueError, match='changed'):
        module.split_reviewed(source, report, decisions, output)
    assert not (output/'split-receipt.json').exists()


def test_legacy_inspection_can_split_with_explicit_unknown_environment(module, recording, monkeypatch, tmp_path):
    import json
    import sys
    from types import SimpleNamespace
    info, rows = recording
    class Dataset(list):
        meta = SimpleNamespace(info=info)
    monkeypatch.setattr(module, 'load_dataset', lambda *args: Dataset(rows))
    monkeypatch.setattr(module, 'dataset_files', lambda root: {'meta/info.json': 'a'*64})
    source, output = tmp_path/'source', tmp_path/'output'
    report = module.inspect_dataset(source, 'local/source', body_units='normalized_-100_100',
                                    rig_revision='rig', calibration_revision='cal', source_mode='leader_native')
    del report['environment_summary']  # Report produced before environment binding existed.
    decisions = copy.deepcopy(report['episodes'])
    for decision, name in zip(decisions, ('train', 'eval')):
        decision.update(split=name, outcome='success', reviewer='operator', reason='checked')
    def splitter(*args, **kwargs):
        return {name: SimpleNamespace(repo_id=f'local/source_{name}') for name in ('train', 'eval')}
    monkeypatch.setitem(sys.modules, 'lerobot.datasets.dataset_tools', SimpleNamespace(split_dataset=splitter))
    module.split_reviewed(source, report, decisions, output)
    receipt = json.loads((output/'split-receipt.json').read_text())
    assert receipt['source']['environment_summary']['status'] == 'unrecorded'
    assert receipt['environment_coverage']['eval']['unobserved_episodes'] == 1
    assert 'environment_summary' not in report


def _calibration(tmp_path, name, lo=1024):
    motors = ['shoulder_pan', 'shoulder_lift', 'elbow_flex', 'wrist_flex', 'wrist_roll', 'gripper']
    path = tmp_path / f'{name}.json'
    path.write_text(json.dumps({m: {'id': i, 'drive_mode': 0, 'homing_offset': 0, 'range_min': lo,
                                    'range_max': 3072} for i, m in enumerate(motors)}), encoding='utf-8')
    return path


def test_action_space_is_declared_from_calibration_and_kept_on_recheck(module, recording, monkeypatch, tmp_path):
    from types import SimpleNamespace
    info, rows = recording
    class Dataset(list):
        meta = SimpleNamespace(info=info)
    monkeypatch.setattr(module, 'dataset_files', lambda root: {'meta/info.json': 'a' * 64})
    monkeypatch.setattr(module, 'load_dataset', lambda *args: Dataset(rows))
    declared = module.declaration_from_calibration([str(_calibration(tmp_path, 'follower'))])
    report = module.inspect_dataset(tmp_path, 'local/data', body_units='normalized_-100_100',
                                    rig_revision='rig', calibration_revision='cal', action_space=declared)
    assert report['action_space']['unit'] == 'lerobot_norm_v1'
    assert report['action_space']['calibration_sha256'] == declared['calibration_sha256']
    undeclared = module.inspect_dataset(tmp_path, 'local/data', body_units='normalized_-100_100',
                                        rig_revision='rig', calibration_revision='cal')
    assert 'action_space' not in undeclared
    with pytest.raises(ValueError):
        module.inspect_dataset(tmp_path, 'local/data', body_units='degrees', rig_revision='rig',
                               calibration_revision='cal', action_space=declared)


def test_bimanual_action_space_needs_one_declaration_per_arm(module, recording, tmp_path):
    info, _ = recording
    names = [f'{arm}.{joint}' for arm in ('arm_a', 'arm_b') for joint in module.JOINTS]
    info = copy.deepcopy(info)
    info['robot_type'] = 'bi_omx_follower'
    for key in ('action', 'observation.state'):
        info['features'][key] = {'dtype': 'float32', 'shape': [12], 'names': names}
    both = module.declaration_from_calibration([f'arm_a={_calibration(tmp_path, "a")}',
                                                f'arm_b={_calibration(tmp_path, "b", lo=1000)}'])
    bound = module.bind_action_space(info, 'normalized_-100_100', both)
    assert set(bound) == {'arm_a', 'arm_b'} and bound['arm_a'] != bound['arm_b']
    for bad in ({'arm_a': both['arm_a']}, both['arm_a'],
                {**both, 'arm_b': {**both['arm_b'], 'unit': 'dynamixel_rad_v1'}}):
        with pytest.raises(ValueError):
            module.bind_action_space(info, 'normalized_-100_100', bad)
