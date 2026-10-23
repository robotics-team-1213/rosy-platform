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


@pytest.mark.parametrize('bimanual', [False, True])
def test_evaluation_requires_same_explicit_joint_layout(module, bimanual):
    names = ([f'{arm}.{joint}' for arm in ('arm_a', 'arm_b') for joint in module.native.JOINTS]
             if bimanual else module.native.JOINTS)
    info = dict(robot_type='bi_omx_follower' if bimanual else 'omx_follower', codebase_version='v3.0',
                features={key: dict(names=names[:], shape=[len(names)])
                          for key in ('action', 'observation.state')})
    assert module.evaluation_joints(info, copy.deepcopy(info)) == names
    invalid = copy.deepcopy(info)
    invalid['features']['action']['names'].reverse()
    with pytest.raises(ValueError, match='joint'):
        module.evaluation_joints(info, invalid)


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


def environment_receipt(module, receipt):
    import native_environment as env
    events, windows = [], []
    for i in range(3):
        stamp = 100+i*100
        events.append(dict(policy='omx-photometric-v3', run_id=f'run-{i}', profile_sha256='d'*64,
                           recorded_ns=stamp, physical_acceptance=False, motion_admitted=False,
                           photometric_ready=False, observations={}, environment={r: dict(
                               condition=None, state='STALE', environment_epoch=0, control_generation=0)
                               for r in ('top', 'front')}))
        windows.append(dict(episode_index=i, start_ns=stamp, end_ns=stamp+50,
                            run_id=f'run-{i}', profile_sha256='d'*64))
    source = receipt['source']
    source['environment_evidence'] = env.seal_environment(
        ''.join(json.dumps(e)+'\n' for e in events).encode(), windows,
        source['files'], rig_revision='rig', calibration_revision='cal')
    source['environment_summary'] = env.bind_environment(
        source['episodes'], source['files'], rig_revision='rig', calibration_revision='cal',
        evidence=source['environment_evidence'])
    receipt['environment_coverage'] = env.split_coverage(source['environment_summary'], receipt['decisions'])


@pytest.mark.parametrize('fault', [None, 'bytes', 'summary', 'coverage', 'missing_evidence', 'missing_summary'])
def test_trainer_checks_original_environment_even_when_split_bytes_are_unchanged(module, splits, fault):
    root, receipt = splits
    environment_receipt(module, receipt)
    if fault == 'bytes': receipt['source']['environment_evidence']['log_utf8'] += ' '
    if fault == 'summary': receipt['source']['environment_summary']['status'] = 'normal'
    if fault == 'coverage': receipt['environment_coverage']['train']['unobserved_episodes'] = 99
    if fault == 'missing_evidence': del receipt['source']['environment_evidence']
    if fault == 'missing_summary': del receipt['source']['environment_summary']
    (root/'split-receipt.json').write_text(json.dumps(receipt))
    if fault is None:
        assert module.validate_split(root) == receipt
    else:
        with pytest.raises(ValueError, match='environment'):
            module.validate_split(root)


def test_verify_entrypoint_refuses_tampered_environment_before_loading_model(module, splits, tmp_path):
    root, receipt = splits
    environment_receipt(module, receipt)
    receipt['source']['environment_evidence']['log_sha256'] = 'f'*64
    (root/'split-receipt.json').write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match='environment'):
        module._evaluate(tmp_path/'no-model', root, 'local/source', tmp_path/'evaluation.json')
    assert not (tmp_path/'evaluation.json').exists()
