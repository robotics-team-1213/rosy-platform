"""Automatic demonstrations retain their source and collection groups."""
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def module():
    path = Path(__file__).resolve().parents[1] / 'native_capture.py'
    spec = importlib.util.spec_from_file_location('omx_native_capture', path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.fixture
def source():
    files = {'meta/info.json': 'a' * 64, 'data/part.parquet': 'b' * 64}
    episodes = [{'episode_index': i, 'frames': 20, 'content_sha256': str(i) * 64}
                for i in range(3)]
    provenance = {
        'schema': 'rosy.omx-native-capture.v1',
        'source_mode': 'scripted_teacher',
        'teacher_sha256': 'c' * 64,
        'action_semantics': 'absolute_joint_position_target_normalized',
        'body_units': 'normalized_-100_100', 'gripper_units': 'normalized_0_100',
        'rig_revision': 'rig-r1', 'calibration_revision': 'cal-r2',
        'files': files.copy(),
        'episodes': [{'episode_index': i, 'session_id': f'session-{i}',
                      'cycle_id': f'cycle-{i}'} for i in range(3)],
    }
    return files, episodes, provenance


def bind(module, source, **kwargs):
    files, episodes, provenance = source
    return module.bind_capture(episodes, files, source_mode='scripted_teacher',
                               body_units='normalized_-100_100', rig_revision='rig-r1',
                               calibration_revision='cal-r2', provenance=provenance, **kwargs)


def test_missing_source_is_unknown_instead_of_invented_leader(module, source):
    files, episodes, _ = source
    result = module.bind_capture(episodes, files, source_mode=None,
                                 body_units='normalized_-100_100', rig_revision='rig-r1',
                                 calibration_revision='cal-r2', provenance=None)
    assert result['source_mode'] == 'unverified_native'
    assert result['episodes'] == episodes


def test_scripted_source_binds_bytes_teacher_and_immutable_groups(module, source):
    result = bind(module, source)
    assert result['source_mode'] == 'scripted_teacher'
    assert result['capture_provenance'] == source[2]
    assert result['episodes'][0]['session_id'] == 'session-0'
    assert result['episodes'][0]['cycle_id'] == 'cycle-0'
    result['capture_provenance']['teacher_sha256'] = 'd' * 64
    assert source[2]['teacher_sha256'] == 'c' * 64
    assert 'cycle_id' not in source[1][0]


@pytest.mark.parametrize('fault', ['bytes', 'teacher', 'units', 'rig', 'calibration',
                                  'missing', 'duplicate', 'empty_group', 'mode', 'semantics'])
def test_automatic_source_rejects_inconsistent_provenance(module, source, fault):
    provenance = source[2]
    if fault == 'bytes': provenance['files']['data/part.parquet'] = 'e' * 64
    if fault == 'teacher': provenance['teacher_sha256'] = 'unversioned'
    if fault == 'units': provenance['body_units'] = 'degrees'
    if fault == 'rig': provenance['rig_revision'] = 'another-rig'
    if fault == 'calibration': provenance['calibration_revision'] = 'another-calibration'
    if fault == 'missing': provenance['episodes'].pop()
    if fault == 'duplicate': provenance['episodes'][1]['episode_index'] = 0
    if fault == 'empty_group': provenance['episodes'][0]['cycle_id'] = ''
    if fault == 'mode': provenance['source_mode'] = 'leader_native'
    if fault == 'semantics': provenance['action_semantics'] = 'absolute_joint_position_target_rad'
    with pytest.raises(ValueError):
        bind(module, source)


def test_automatic_source_requires_manifest_and_refuses_wrong_mode(module, source):
    files, episodes, provenance = source
    with pytest.raises(ValueError, match='provenance'):
        module.bind_capture(episodes, files, source_mode='scripted_teacher',
                            body_units='normalized_-100_100', rig_revision='rig-r1',
                            calibration_revision='cal-r2', provenance=None)
    with pytest.raises(ValueError, match='source'):
        module.bind_capture(episodes, files, source_mode='leader_native',
                            body_units='normalized_-100_100', rig_revision='rig-r1',
                            calibration_revision='cal-r2', provenance=provenance)


@pytest.mark.parametrize('group', ['session_id', 'cycle_id'])
def test_parent_groups_cannot_cross_splits(module, source, group):
    episodes = bind(module, source)['episodes']
    episodes[1][group] = episodes[0][group]
    decisions = [{'split': name} for name in ('train', 'eval', 'test')]
    with pytest.raises(ValueError, match=group):
        module.check_capture_groups(episodes, decisions)


def test_grouping_uses_source_instead_of_editable_review_values(module, source):
    episodes = bind(module, source)['episodes']
    episodes[1]['cycle_id'] = episodes[0]['cycle_id']
    decisions = [{'split': name, 'cycle_id': f'fake-{i}'}
                 for i, name in enumerate(('train', 'eval', 'test'))]
    with pytest.raises(ValueError, match='cycle_id'):
        module.check_capture_groups(episodes, decisions)


def test_excluded_attempts_do_not_leak_into_another_split(module, source):
    episodes = bind(module, source)['episodes']
    episodes[1]['cycle_id'] = episodes[0]['cycle_id']
    decisions = [{'split': name} for name in ('train', 'exclude', 'eval')]
    module.check_capture_groups(episodes, decisions)


def leader(source):
    provenance = dict(source[2], source_mode='leader_native', collection_manifest_sha256='f' * 64)
    del provenance['teacher_sha256']
    return provenance


def bind_leader(module, source, provenance):
    files, episodes, _ = source
    return module.bind_capture(episodes, files, source_mode='leader_native', body_units='normalized_-100_100',
                               rig_revision='rig-r1', calibration_revision='cal-r2', provenance=provenance)


def test_sealed_leader_recording_binds_session_and_cycle_lineage(module, source):
    result = bind_leader(module, source, leader(source))
    assert result['source_mode'] == 'leader_native'
    assert [e['session_id'] for e in result['episodes']] == ['session-0', 'session-1', 'session-2']


@pytest.mark.parametrize('fault', ['teacher', 'no_manifest', 'bytes', 'missing'])
def test_leader_lineage_must_name_its_sealed_manifest_and_cover_the_bytes(module, source, fault):
    provenance = leader(source)
    if fault == 'teacher': provenance['teacher_sha256'] = 'c' * 64
    if fault == 'no_manifest': del provenance['collection_manifest_sha256']
    if fault == 'bytes': provenance['files']['data/part.parquet'] = 'e' * 64
    if fault == 'missing': provenance['episodes'].pop()
    with pytest.raises(ValueError):
        bind_leader(module, source, provenance)


def test_leader_recording_without_lineage_stays_ungrouped(module, source):
    files, episodes, _ = source
    result = module.bind_capture(episodes, files, source_mode='leader_native', body_units='normalized_-100_100',
                                 rig_revision='rig-r1', calibration_revision='cal-r2', provenance=None)
    assert result == dict(source_mode='leader_native', episodes=episodes)
