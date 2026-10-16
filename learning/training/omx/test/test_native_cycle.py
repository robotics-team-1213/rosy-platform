"""The training bridge refuses mutable, unreviewed or overlapping split inputs."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def module():
    path = Path(__file__).resolve().parents[1] / 'native_cycle.py'
    spec = importlib.util.spec_from_file_location('omx_native_cycle', path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.fixture
def splits(module, tmp_path):
    root = tmp_path/'splits'
    episodes = [dict(episode_index=i, content_sha256=str(i)*64, frames=4,
                     session_id=f'session-{i}', cycle_id=f'cycle-{i}') for i in range(3)]
    decisions = copy.deepcopy(episodes)
    outputs = {}
    for i, name in enumerate(('train', 'eval', 'test')):
        (root/name/'meta').mkdir(parents=True)
        (root/name/'data').mkdir()
        (root/name/'meta/info.json').write_text('{}')
        (root/name/'data/part.parquet').write_bytes(name.encode())
        outputs[name] = module.native.dataset_files(root/name)
        decisions[i].update(outcome='success', split=name, reviewer='reviewer', reason='checked')
    files = {'meta/info.json': 'a' * 64, 'data/part.parquet': 'b' * 64}
    provenance = dict(schema='rosy.omx-native-capture.v1', source_mode='scripted_teacher',
                       teacher_sha256='c' * 64, action_semantics='absolute_joint_position_target_normalized',
                       body_units='normalized_-100_100', gripper_units='normalized_0_100',
                       rig_revision='rig', calibration_revision='cal', files=files.copy(),
                       episodes=[dict(episode_index=i, session_id=f'session-{i}', cycle_id=f'cycle-{i}')
                                 for i in range(3)])
    receipt = dict(source=dict(source_mode='scripted_teacher', episodes=episodes, repo_id='local/source',
                               files=files, body_units='normalized_-100_100', rig_revision='rig',
                               calibration_revision='cal', capture_provenance=provenance),
                   reader_verified=True, decisions=decisions,
                   splits=dict(train=[0], eval=[1], test=[2]), outputs=outputs)
    (root/'split-receipt.json').write_text(json.dumps(receipt))
    return root, receipt


def test_split_bytes_and_review_groups_are_bound_before_training(module, splits):
    root, receipt = splits
    assert module.validate_split(root) == receipt
    (root/'train/data/part.parquet').write_bytes(b'changed')
    with pytest.raises(ValueError, match='bytes'):
        module.validate_split(root)


@pytest.mark.parametrize('fault', ['unknown_source', 'unreviewed', 'missing_hash', 'split_ids', 'cycle'])
def test_invalid_split_receipts_cannot_start_trainer(module, splits, fault):
    root, receipt = splits
    if fault == 'unknown_source': receipt['source']['source_mode'] = 'unverified_native'
    if fault == 'unreviewed': receipt['decisions'][0]['outcome'] = 'unknown'
    if fault == 'missing_hash': del receipt['outputs']
    if fault == 'split_ids': receipt['splits']['train'] = [2]
    if fault == 'cycle':
        receipt['source']['episodes'][1]['cycle_id'] = 'cycle-0'
        receipt['decisions'][1]['cycle_id'] = 'cycle-0'
    (root/'split-receipt.json').write_text(json.dumps(receipt))
    with pytest.raises(ValueError):
        module.validate_split(root)


def test_training_output_cannot_overlap_input_or_overwrite_prior_run(module, splits, tmp_path):
    root, _ = splits
    for output in (root/'new-run', root.parent, tmp_path/'previous'):
        if output.name == 'previous': output.mkdir()
        with pytest.raises(ValueError):
            module.run_cycle(root, output, steps=2, batch_size=2, device='cpu')


@pytest.mark.parametrize('fault', ['missing', 'teacher', 'files', 'semantics', 'groups'])
def test_trainer_revalidates_capture_provenance_even_with_unchanged_split_bytes(module, splits, fault):
    root, receipt = splits
    source = receipt['source']
    if fault == 'missing': del source['capture_provenance']
    if fault == 'teacher': source['capture_provenance']['teacher_sha256'] = 'not-a-hash'
    if fault == 'files': source['capture_provenance']['files']['data/part.parquet'] = 'e' * 64
    if fault == 'semantics': source['capture_provenance']['action_semantics'] = 'joint_velocity'
    if fault == 'groups':
        for episode in source['episodes']:
            del episode['session_id']
            del episode['cycle_id']
    (root/'split-receipt.json').write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match='capture'):
        module.validate_split(root)
