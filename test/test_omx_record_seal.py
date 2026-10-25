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
    return run, dataset


@pytest.mark.parametrize('robot_type', ['omx_follower', 'bi_omx_follower'])
def test_sealed_recording_passes_the_transfer_verifier(seal, transfer, tmp_path, robot_type):
    run, dataset = recording(tmp_path, robot_type)
    result = seal.seal(run, 'arm2-001', tmp_path/'collections')
    target = tmp_path/'collections'/'arm2-001'
    manifest = json.loads((target/'manifest.json').read_text())
    assert manifest['source_mode'] == 'leader_native' and manifest['robot_type'] == robot_type
    assert set(manifest['files']) == {'dataset/meta/info.json', 'dataset/data/chunk-000/file-000.parquet',
                                      'session.json', 'record-config.json'}
    assert transfer.verify_tree(target)['file_count'] == result['file_count'] == 4
    assert (dataset/'meta'/'info.json').exists()  # the recording itself is left in place


@pytest.mark.parametrize('session', [dict(safe_end=False), dict(teleop_only=True), dict(exit_code=1),
                                     dict(interrupted=True)])
def test_unsafe_or_incomplete_recording_is_refused(seal, tmp_path, session):
    run, _ = recording(tmp_path, **session)
    with pytest.raises(ValueError, match='safe, completed'):
        seal.seal(run, 'arm2-001', tmp_path/'collections')
    assert not (tmp_path/'collections'/'arm2-001').exists()


def test_existing_name_non_native_dataset_and_links_are_refused(seal, tmp_path):
    run, dataset = recording(tmp_path)
    seal.seal(run, 'arm2-001', tmp_path/'collections')
    with pytest.raises(ValueError, match='choose a new name'):
        seal.seal(run, 'arm2-001', tmp_path/'collections')
    (dataset/'link').symlink_to(dataset/'meta'/'info.json')
    with pytest.raises(ValueError, match='links'):
        seal.seal(run, 'arm2-002', tmp_path/'collections')
    assert not list((tmp_path/'collections').glob('.*'))  # staging removed after a refusal
    (dataset/'link').unlink()
    (dataset/'meta'/'info.json').write_text(json.dumps(dict(codebase_version='v3.0', robot_type='rosy_sim')))
    with pytest.raises(ValueError, match='native OMX'):
        seal.seal(run, 'arm2-003', tmp_path/'collections')


def test_transfer_still_refuses_simulation_sources(transfer, tmp_path):
    root = tmp_path/'raw'
    root.mkdir()
    (root/'manifest.json').write_text(json.dumps(dict(
        schema='rosy.omx-collection-session.v1', state='CLOSED', mode='hardware',
        source_mode='simulation', files={'a': '0'*64})))
    with pytest.raises(ValueError, match='closed hardware'):
        transfer.verify_tree(root)


def scripted(tmp_path, *, tamper=False):
    trajectory = tmp_path/'cycle.json'
    trajectory.write_text(json.dumps(dict(schema='rosy.omx-replay-trajectory.v1', frames=[[0.0] * 6],
                                          source=dict(planner='grasp_planner.py top-down v1'))))
    sha = load('record_seal', 'deploy/robot/omx/record_seal.py')._hash(trajectory)
    if tamper:
        trajectory.write_text('{}')
    segments = dict(A=[0, 1], reset=[1, 2], B=[2, 3])
    return recording(tmp_path, robot_type='omx_follower', source_mode='scripted_teacher',
                     replay=dict(path=str(trajectory), sha256=sha, segments=segments))


def test_a_scripted_teacher_recording_carries_its_trajectory_and_passes_the_transfer(seal, transfer, tmp_path):
    run, _ = scripted(tmp_path)
    result = seal.seal(run, 'arm-s-replay-1', tmp_path/'collections')
    collection = Path(result['collection'])
    manifest = json.loads((collection/'manifest.json').read_text())
    assert manifest['source_mode'] == 'scripted_teacher'
    assert manifest['teacher_sha256'] == seal._hash(collection/'teacher'/'trajectory.json')
    assert manifest['teacher']['kind'] == 'replay_trajectory' and manifest['teacher']['segments']['B'] == [2, 3]
    assert manifest['teacher']['source'] == {'planner': 'grasp_planner.py top-down v1'}
    assert transfer.verify_tree(collection)['file_count'] == result['file_count']  # teacher file included


@pytest.mark.parametrize('case', ['tampered', 'no_replay', 'unknown_mode'])
def test_a_teacher_recording_without_its_exact_trajectory_is_refused(seal, tmp_path, case):
    if case == 'tampered':
        run, _ = scripted(tmp_path, tamper=True)
    else:
        mode = 'scripted_teacher' if case == 'no_replay' else 'sim_teacher'
        run, _ = recording(tmp_path, source_mode=mode)
    with pytest.raises(ValueError, match='replay|differs|leader_native'):
        seal.seal(run, 'refused', tmp_path/'collections')
    assert not (tmp_path/'collections'/'refused').exists()
