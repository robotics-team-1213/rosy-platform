"""A finished leader recording is sealed into a collection the transfer verifier accepts."""
import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, REPO/relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def seal():
    return load('record_seal', 'deploy/robot/omx/record_seal.py')


@pytest.fixture
def transfer():
    return load('omx_collection_transfer', 'tools/remote/omx_collection_transfer.py')


def recording(tmp_path, robot_type='bi_omx_follower', **session):
    dataset = tmp_path/'datasets'/'task-r1'
    (dataset/'meta').mkdir(parents=True)
    (dataset/'data'/'chunk-000').mkdir(parents=True)
    (dataset/'meta'/'info.json').write_text(json.dumps(
        dict(codebase_version='v3.0', robot_type=robot_type, total_episodes=1)))
    (dataset/'data'/'chunk-000'/'file-000.parquet').write_bytes(b'PAR1')
    run = tmp_path/'run'
    run.mkdir()
    (run/'record.json').write_text(json.dumps(dict(dataset=dict(root=str(dataset)))))
    record = dict(config='record.json', teleop_only=False, exit_code=0, safe_end=True)
    record.update(session)
    (run/'session.json').write_text(json.dumps(record))
    (tmp_path/'arm_a_follower.json').write_text('{}')
    return run, dataset


def sealed(seal, run, name, collections, **kwargs):
    kwargs.setdefault('rig_revision', 'bench-r1')
    kwargs.setdefault('calibrations', [run.parent/'arm_a_follower.json'])
    return seal.seal(run, name, collections, **kwargs)


@pytest.mark.parametrize('robot_type', ['omx_follower', 'bi_omx_follower'])
def test_sealed_recording_passes_the_transfer_verifier(seal, transfer, tmp_path, robot_type):
    run, dataset = recording(tmp_path, robot_type)
    result = sealed(seal, run, 'arm2-001', tmp_path/'collections')
    target = tmp_path/'collections'/'arm2-001'
    manifest = json.loads((target/'manifest.json').read_text())
    assert manifest['source_mode'] == 'leader_native' and manifest['robot_type'] == robot_type
    assert set(manifest['files']) == {'dataset/meta/info.json', 'dataset/data/chunk-000/file-000.parquet',
                                      'session.json', 'record-config.json', 'calibration/arm_a_follower.json'}
    assert manifest['session_id'] == 'arm2-001' and manifest['rig_revision'] == 'bench-r1'
    assert manifest['calibration_revision'] == seal.calibration_revision(manifest['files'])
    assert transfer.verify_tree(target)['file_count'] == result['file_count'] == 5
    assert (dataset/'meta'/'info.json').exists()  # the recording itself is left in place


@pytest.mark.parametrize('session', [dict(safe_end=False), dict(teleop_only=True), dict(exit_code=1),
                                     dict(interrupted=True)])
def test_unsafe_or_incomplete_recording_is_refused(seal, tmp_path, session):
    run, _ = recording(tmp_path, **session)
    with pytest.raises(ValueError, match='safe, completed'):
        sealed(seal, run, 'arm2-001', tmp_path/'collections')
    assert not (tmp_path/'collections'/'arm2-001').exists()


def test_existing_name_non_native_dataset_and_links_are_refused(seal, tmp_path):
    run, dataset = recording(tmp_path)
    sealed(seal, run, 'arm2-001', tmp_path/'collections')
    with pytest.raises(ValueError, match='choose a new name'):
        sealed(seal, run, 'arm2-001', tmp_path/'collections')
    (dataset/'link').symlink_to(dataset/'meta'/'info.json')
    with pytest.raises(ValueError, match='links'):
        sealed(seal, run, 'arm2-002', tmp_path/'collections')
    assert not list((tmp_path/'collections').glob('.*'))  # staging removed after a refusal
    (dataset/'link').unlink()
    (dataset/'meta'/'info.json').write_text(json.dumps(dict(codebase_version='v3.0', robot_type='rosy_sim')))
    with pytest.raises(ValueError, match='native OMX'):
        sealed(seal, run, 'arm2-003', tmp_path/'collections')


@pytest.mark.parametrize('kwargs', [dict(rig_revision=' '), dict(calibrations=[]),
                                    dict(calibrations=['missing.json'])])
def test_rig_and_calibration_must_be_named_explicitly(seal, tmp_path, kwargs):
    run, _ = recording(tmp_path)
    with pytest.raises(ValueError, match='explicit'):
        sealed(seal, run, 'arm2-001', tmp_path/'collections', **kwargs)


def test_transfer_still_refuses_simulation_sources(transfer, tmp_path):
    root = tmp_path/'raw'
    root.mkdir()
    (root/'manifest.json').write_text(json.dumps(dict(
        schema='rosy.omx-collection-session.v1', state='CLOSED', mode='hardware',
        source_mode='simulation', files={'a': '0'*64})))
    with pytest.raises(ValueError, match='closed hardware'):
        transfer.verify_tree(root)
