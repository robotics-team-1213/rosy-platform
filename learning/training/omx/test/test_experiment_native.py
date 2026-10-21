"""Real sealing/mapping rules with only the optional official reader replaced."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import experiment_native as bridge
from experiment_dataset import load_dataset
from test_native_cycle import module, splits  # Existing sealed-receipt fixture.


@pytest.fixture
def capture(splits, monkeypatch):
    root, receipt = splits
    readers = {}
    for index, split in enumerate(('train', 'eval', 'test')):
        features = {key: {'names': bridge.native.JOINTS, 'shape': [6]}
                    for key in ('action', 'observation.state')}
        features.update({f'observation.images.{role}': {'shape': [2, 3, 3]}
                         for role in ('top', 'wrist')})
        info = dict(robot_type='omx_follower', codebase_version='v3.0', fps=10,
                    total_frames=4, total_episodes=1, features=features)
        rows = [dict(episode_index=0, frame_index=frame, timestamp=frame / 10,
                     task='Pick the block', **{
                         'action': np.arange(6, dtype=np.float32) + index + frame,
                         'observation.state': np.arange(6, dtype=np.float32) + index,
                         'observation.images.top': np.full((3, 2, 3), (index + frame) / 255, np.float32),
                         'observation.images.wrist': np.full((3, 2, 3), (index + frame + 7) / 255, np.float32)})
                for frame in range(4)]
        inspected = bridge.native.inspect_frames(info, rows)['episodes'][0]
        for row in (receipt['source']['episodes'][index], receipt['decisions'][index]):
            row['content_sha256'] = inspected['content_sha256']
        readers[split] = SimpleNamespace(meta=SimpleNamespace(info=info), rows=rows)
    receipt['source']['gripper_units'] = 'normalized_0_100'
    (root / 'split-receipt.json').write_text(json.dumps(receipt))

    class Reader:
        def __init__(self, data):
            self.meta, self.rows = data.meta, data.rows

        def __len__(self):
            return len(self.rows)

        def __getitem__(self, index):
            return self.rows[index]

    def reader(path, repo_id):
        assert repo_id == 'local/source_' + path.name
        return Reader(readers[path.name])

    monkeypatch.setattr(bridge.native, 'load_dataset', reader)
    profile = dict(schema='rosy.omx.learning-profile/1', name='Bench capture',
        mode='independent', task='Pick the block',
        arms=[dict(id='follower_1', joint_names=bridge.native.JOINTS[:], units='normalized_-100_100')],
        cameras=[dict(id=role, input_key='observation.images.' + role,
                      arm_id='follower_1' if role == 'wrist' else None, role=role,
                      source_identity='camera-by-id-' + role, placement=role + '-mount-r2',
                      shape=[3, 2, 3], purposes=['policy', 'record']) for role in ('top', 'wrist')])
    return root, receipt, profile, readers


def test_conversion_reads_actual_arrays_preserves_lineage_and_never_invents_transitions(capture, tmp_path):
    root, receipt, profile, readers = capture
    output = tmp_path / 'converted'
    result = bridge.convert_native(root, output, profile=profile)
    data = load_dataset(output)
    assert data.source == 'reviewed_demonstration'
    assert result['act_only'] and result['online_transitions'] is False
    assert result['dataset_revision'] == data.revision
    assert data.profile == profile
    for index, split in enumerate(('train', 'eval', 'test')):
        episode = data.split(split)[0]
        assert episode.metadata['session_id'] == f'session-{index}'
        assert episode.metadata['parent_id'] == f'cycle-{index}'
        assert result['episodes'][index]['original_episode_index'] == index
        assert set(episode.arrays) == {'action', 'observation.state',
                                    'observation.images.top', 'observation.images.wrist'}
        np.testing.assert_array_equal(episode.arrays['action'][2], readers[split].rows[2]['action'])
        np.testing.assert_array_equal(episode.arrays['observation.images.wrist'][2],
                                      np.full((3, 2, 3), index + 9, np.uint8))
    for relative, digest in result['files'].items():
        assert hashlib.sha256((output / relative).read_bytes()).hexdigest() == digest
    assert json.loads((output / 'native-split-receipt.json').read_text()) == receipt
    with pytest.raises(ValueError, match='array keys'):
        load_dataset(output, method='hilserl')
    with pytest.raises(ValueError, match='already exists'):
        bridge.convert_native(root, output, profile=profile)


@pytest.mark.parametrize('fault', ['arms', 'units', 'joints', 'camera_key', 'camera_shape',
                                  'placement', 'missing_lineage', 'reader_bytes', 'input_hash'])
def test_rejects_unsupported_mapping_missing_identity_or_mutable_source(capture, tmp_path, fault):
    root, receipt, profile, readers = capture
    if fault == 'arms':
        profile['arms'].append(dict(id='other', joint_names=bridge.native.JOINTS[:], units='normalized_-100_100'))
    elif fault == 'units':
        profile['arms'][0]['units'] = 'rad'
    elif fault == 'joints':
        profile['arms'][0]['joint_names'].reverse()
    elif fault == 'camera_key':
        profile['cameras'][1]['input_key'] = 'observation.images.front'
    elif fault == 'camera_shape':
        profile['cameras'][1]['shape'] = [3, 3, 3]
    elif fault == 'placement':
        del profile['cameras'][0]['placement']
    elif fault == 'missing_lineage':
        receipt['source']['source_mode'] = 'leader_native'
        receipt['source'].pop('capture_provenance')
        for row in receipt['source']['episodes'] + receipt['decisions']:
            row.pop('session_id')
            row.pop('cycle_id')
        (root / 'split-receipt.json').write_text(json.dumps(receipt))
    elif fault == 'reader_bytes':
        readers['train'].rows[0]['action'][0] += 1
    elif fault == 'input_hash':
        (root / 'train/data/part.parquet').write_bytes(b'changed')
    output = tmp_path / ('failed-' + fault)
    with pytest.raises(ValueError):
        bridge.convert_native(root, output, profile=profile)
    assert (output / 'failed.json').is_file()
    assert not (output / 'conversion-receipt.json').exists()


def test_conversion_refuses_input_overlap_and_source_checkout(capture, tmp_path):
    root, _, profile, _ = capture
    for output in (root / 'nested', root.parent,
                   Path(__file__).resolve().parents[1] / 'conversion-output'):
        with pytest.raises(ValueError, match='separate|checkout'):
            bridge.convert_native(root, output, profile=profile)


def test_conversion_preserves_three_explicit_camera_keys_and_placements(capture, tmp_path):
    root, receipt, profile, readers = capture
    profile['cameras'].append(dict(id='side', input_key='observation.images.side_left',
        arm_id=None, role='side', source_identity='camera-by-id-side',
        placement='cart-left-r3', shape=[3, 2, 3], purposes=['evaluation', 'record']))
    for index, split in enumerate(('train', 'eval', 'test')):
        reader = readers[split]
        reader.meta.info['features']['observation.images.side_left'] = {'shape': [2, 3, 3]}
        for frame, row in enumerate(reader.rows):
            row['observation.images.side_left'] = np.full((3, 2, 3), (index + frame + 70)/255, np.float32)
        inspected = bridge.native.inspect_frames(reader.meta.info, reader.rows)['episodes'][0]
        for original in (receipt['source']['episodes'][index], receipt['decisions'][index]):
            original['content_sha256'] = inspected['content_sha256']
    (root/'split-receipt.json').write_text(json.dumps(receipt))
    output = tmp_path/'three-cameras'
    bridge.convert_native(root, output, profile=profile)
    data = load_dataset(output)
    assert data.profile == profile
    for index, split in enumerate(('train', 'eval', 'test')):
        np.testing.assert_array_equal(data.split(split)[0].arrays['observation.images.side_left'][2],
                                      np.full((3, 2, 3), index + 72, np.uint8))


def test_native_wrist_camera_requires_explicit_arm_binding(capture, tmp_path):
    root, _, profile, _ = capture
    profile['cameras'][1]['arm_id'] = None
    with pytest.raises(ValueError, match='wrist'):
        bridge.convert_native(root, tmp_path/'unbound-wrist', profile=profile)
