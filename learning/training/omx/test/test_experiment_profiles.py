"""Immutable, workspace-scoped profile records preserve explicitly supplied setups."""
import copy
import json
from pathlib import Path
import sqlite3
import sys
import threading
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiment_profile import profile_revision
from test_experiment_profile import profile


@pytest.fixture
def store(tmp_path):
    from experiment_profiles import Profiles
    connect = lambda: sqlite3.connect(tmp_path / 'profiles.sqlite')
    profiles = Profiles(connect, threading.RLock())
    with connect() as db:
        profiles.schema(db)
    return profiles


def request(setup=None):
    return dict(profile=profile() if setup is None else setup, request_id=str(uuid.uuid4()))


def test_save_get_list_and_clone_keep_parent_and_explicit_setup_immutable(store):
    body = request()
    before = copy.deepcopy(body)
    first = store.save(body)
    assert body == before and first['profile'] == body['profile']
    assert first['revision'] == profile_revision(body['profile']) and first['parent_id'] is None
    assert first['created_by'] == {'kind': 'local_unverified', 'id': 'local'}
    assert first['physical_setup_verified'] is first['policy_activation'] is False
    assert first['created_at'] and str(uuid.UUID(first['id'])) == first['id']
    changed = copy.deepcopy(first['profile'])
    changed['arms'].reverse()
    changed['cameras'].reverse()
    changed['cameras'][0]['placement'] = 'operator-selected-placement-r3'
    child = store.save(dict(request(changed), parent_id=first['id']), actor={'user_id': 'alice'})
    assert child['parent_id'] == first['id'] and child['profile'] == changed
    assert child['created_by'] == {'kind': 'authenticated', 'id': 'alice'}
    assert store.get(first['id']) == first and store.get(child['id']) == child
    assert store.list() == [child, first]
    same_content = store.save(request(body['profile']))
    assert same_content['revision'] == first['revision'] and same_content['id'] != first['id']


def test_request_uuid_is_bound_to_exact_body_and_server_actor(store):
    body = request()
    first = store.save(body, actor={'user_id': 'alice'})
    assert store.save(copy.deepcopy(body), actor={'user_id': 'alice'}) == first
    with pytest.raises(ValueError, match='request'):
        store.save(body, actor={'user_id': 'bob'})
    changed = copy.deepcopy(body)
    changed['profile']['task'] = 'A different requested task'
    with pytest.raises(ValueError, match='request'):
        store.save(changed, actor={'user_id': 'alice'})
    assert len(store.list()) == 1


@pytest.mark.parametrize('field', ['path', 'argv', 'actor', 'created_by'])
def test_browser_cannot_supply_paths_commands_or_identity(store, field):
    body = request()
    body[field] = 'untrusted'
    with pytest.raises(ValueError):
        store.save(body)
    assert store.list() == []


def test_missing_parent_bad_ids_and_oversized_request_are_rejected(store):
    with pytest.raises(ValueError, match='parent'):
        store.save(dict(request(), parent_id=str(uuid.uuid4())))
    body = request()
    body['request_id'] = uuid.uuid4().hex
    with pytest.raises(ValueError):
        store.save(body)
    with pytest.raises(ValueError):
        store.get('not-a-profile-id')
    body = request()
    body['profile']['task'] = 'x' * (1024 * 1024)
    with pytest.raises(ValueError, match='bounded|1 MiB'):
        store.save(body)
    assert store.list() == []


def test_schema2_maximum_arm_camera_setup_keeps_declared_bounds_and_order(store):
    setup = profile()
    setup['schema'] = 'rosy.omx.learning-profile/2'
    arm = setup['arms'][0]
    setup['arms'] = [dict(copy.deepcopy(arm), id=f'arm_{index}', action_limits=[[-1, 1]] * 3)
                     for index in range(32)]
    camera = setup['cameras'][0]
    setup['cameras'] = [dict(copy.deepcopy(camera), id=f'camera_{index}',
        input_key=f'observation.images.view_{index}', source_identity=f'camera-stable-{index}',
        arm_id=None if index == 0 else f'arm_{index % 32}') for index in range(64)]
    saved = store.save(request(setup))
    assert saved['profile'] == setup and store.get(saved['id'])['profile'] == setup
    del setup['arms'][0]['action_limits']
    with pytest.raises(ValueError):
        store.save(request(setup))


@pytest.mark.parametrize('fault', ['revision', 'invalid_profile'])
def test_stored_profile_tampering_is_refused_by_get_and_list(store, fault):
    saved = store.save(request())
    changed = copy.deepcopy(saved)
    if fault == 'revision':
        changed['profile']['cameras'][0]['placement'] = 'tampered-placement'
    else:
        changed['profile']['arms'] = []
    with store.connect() as db:
        db.execute('UPDATE learning_profiles SET document=? WHERE id=?', (json.dumps(changed), saved['id']))
    with pytest.raises(ValueError):
        store.get(saved['id'])
    with pytest.raises(ValueError):
        store.list()


def test_resolve_accepts_numeric_roundtrip_and_returns_exact_stored_document(store):
    setup = profile()
    setup['schema'] = 'rosy.omx.learning-profile/2'
    for arm in setup['arms']:
        arm['action_limits'] = [[-1.0, 1.0] for _ in arm['joint_names']]
    saved = store.save(request(setup))
    submitted = copy.deepcopy(setup)
    for arm in submitted['arms']:
        arm['action_limits'] = [[-1, 1] for _ in arm['joint_names']]
    resolved = store.resolve(saved['id'], submitted)
    assert json.dumps(resolved, sort_keys=True) == json.dumps(saved, sort_keys=True)
    assert type(resolved['profile']['arms'][0]['action_limits'][0][0]) is float
    assert store.get(saved['id']) == saved
    submitted['arms'][0]['action_limits'][0][0] = False
    with pytest.raises(ValueError):
        store.resolve(saved['id'], submitted)


@pytest.mark.parametrize('change', ['placement', 'arm_order', 'camera_order'])
def test_resolve_rejects_changed_setup_and_preserves_stored_record(store, change):
    saved = store.save(request())
    submitted = copy.deepcopy(saved['profile'])
    if change == 'placement':
        submitted['cameras'][0]['placement'] = 'different-placement-r4'
    elif change == 'arm_order':
        submitted['arms'].reverse()
    else:
        submitted['cameras'].reverse()
    with pytest.raises(ValueError, match='profile'):
        store.resolve(saved['id'], submitted)
    assert store.get(saved['id']) == saved
