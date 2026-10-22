"""Learning references persist without conferring device or execution authority."""
import copy
import hashlib
import json
import uuid

import pytest

from learning_tasks import Tasks


ACTOR = {'user_id': 'alice'}


def uid():
    return str(uuid.uuid4())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def robot_body(**changes):
    return dict(dict(request_id=uid(), name='Bench arm', kind='omx',
        model_revision='omx-r1', device_id=uid()), **changes)


def setup(store, mode='cooperative', same_robot=False):
    first = store.robot(robot_body(), ACTOR)
    second = first if same_robot else store.robot(robot_body(), ACTOR)
    profile = {'mode': mode, 'arms': [{'id': 'arm_a'}, {'id': 'arm_b'}]}
    saved = dict(id=uid(), revision=digest(profile), profile=profile)
    body = dict(request_id=uid(), name='Transfer', objective='Move block',
        success='Block at target', failure='Dropped block', reset='Return to start',
        mode=mode, participants=[dict(robot_id=first['id'], component_id='arm_a', role='pick'),
            dict(robot_id=second['id'], component_id='arm_b', role='hold')],
        adapter='omx', profile_id=saved['id'])
    return body, saved


@pytest.fixture
def store(tmp_path):
    return Tasks(tmp_path / 'review.sqlite', 'project-a')


def test_durable_immutable_references_and_actor_bound_retries(store, tmp_path):
    body = robot_body()
    first = store.robot(body, ACTOR)
    assert first['id'] == body['request_id']
    assert first['device_verified'] is False
    assert first['project_id'] == 'project-a'
    assert first['created_by'] == {'kind': 'authenticated', 'id': 'alice'}
    assert store.robot(copy.deepcopy(body), ACTOR) == first
    for changed, actor in [(dict(body, name='Changed'), ACTOR), (body, {'user_id': 'bob'})]:
        with pytest.raises(ValueError):
            store.robot(changed, actor)
    task_body, profile = setup(store)
    task = store.task(task_body, ACTOR, profile)
    assert task['runnable'] is True and task['profile_revision'] == profile['revision']
    assert store.task(copy.deepcopy(task_body), ACTOR, profile) == task
    with pytest.raises(ValueError):
        store.task(task_body, {'user_id': 'bob'}, profile)
    first['name'] = 'Client mutation'
    reopened = Tasks(tmp_path / 'review.sqlite', 'project-a')
    assert reopened.snapshot() == store.snapshot()
    assert reopened.snapshot()['robots'][0]['name'] == body['name']
    assert len(task['revision']) == 64
    with pytest.raises(ValueError):
        Tasks(tmp_path / 'review.sqlite', 'project-b')


@pytest.mark.parametrize('mode,components', [('independent', ['arm_b']),
    ('cooperative', ['arm_a', 'arm_b'])])
def test_two_robots_bind_dataset_durably_and_allow_same_task_methods(store, tmp_path, mode, components):
    body, profile = setup(store, mode)
    task = store.task(body, ACTOR, profile)
    args = (task['id'], 'dataset-a', 'a' * 64, profile['revision'], components, 'model')
    binding = store.resolve(*args)
    assert binding['task_revision'] == task['revision']
    assert binding['participants'] == [p for p in body['participants'] if p['component_id'] in components]
    assert binding['component_ids'] == components and binding['compute_host'] == 'model'
    assert Tasks(tmp_path / 'review.sqlite', 'project-a').resolve(*args) == binding
    other = store.task(dict(body, request_id=uid()), ACTOR, profile)
    for dataset_id, revision in [('dataset-a', 'b' * 64), ('dataset-b', 'a' * 64)]:
        with pytest.raises(ValueError):
            store.resolve(other['id'], dataset_id, revision, profile['revision'], components, 'model')
    with pytest.raises(ValueError):
        store.resolve(task['id'], 'dataset-a', 'b' * 64, profile['revision'], components, 'model')


def test_one_robot_can_expose_two_distinct_components(store):
    body, profile = setup(store, same_robot=True)
    assert store.task(body, ACTOR, profile)['runnable'] is True


@pytest.mark.parametrize('change', ['host', 'profile', 'reverse', 'subset', 'unknown'])
def test_resolve_refuses_host_signature_or_group_mismatch(store, change):
    body, profile = setup(store)
    task = store.task(body, ACTOR, profile)
    revision, components, host = profile['revision'], ['arm_a', 'arm_b'], 'model'
    if change == 'host':
        host = None
    elif change == 'profile':
        revision = 'b' * 64
    elif change == 'reverse':
        components.reverse()
    elif change == 'subset':
        components = ['arm_a']
    else:
        components = ['unknown']
    with pytest.raises(ValueError):
        store.resolve(task['id'], 'dataset', 'a' * 64, revision, components, host)


@pytest.mark.parametrize('change', ['unknown_robot', 'duplicate_component', 'duplicate_role',
    'mode', 'profile_order', 'profile_content', 'one_cooperative', 'unknown_field'])
def test_task_refuses_invalid_participants_and_profile(store, change):
    body, profile = setup(store)
    if change == 'unknown_robot':
        body['participants'][0]['robot_id'] = uid()
    elif change == 'duplicate_component':
        body['participants'][1]['component_id'] = 'arm_a'
    elif change == 'duplicate_role':
        body['participants'][1]['role'] = 'pick'
    elif change == 'mode':
        body['mode'] = 'independent'
    elif change == 'profile_order':
        body['participants'].reverse()
    elif change == 'profile_content':
        profile['profile']['arms'][0]['id'] = 'changed'
    elif change == 'one_cooperative':
        body['participants'].pop()
    else:
        body['command'] = 'run'
    with pytest.raises(ValueError):
        store.task(body, ACTOR, profile)
    assert store.snapshot()['tasks'] == []


def test_duplicate_device_references_and_request_namespace_collisions(store):
    body = robot_body()
    store.robot(body, ACTOR)
    with pytest.raises(ValueError):
        store.robot(dict(body, request_id=uid()), ACTOR)
    task, profile = setup(store)
    task['request_id'] = body['request_id']
    with pytest.raises(ValueError):
        store.task(task, ACTOR, profile)


@pytest.mark.parametrize('changes', [dict(path='/tmp/input'), dict(request_id='bad'),
    dict(name='unsafe\ntext'), dict(name='x' * 1025), dict(device_id=''), dict(created_by='alice')])
def test_robot_rejects_untrusted_or_oversized_fields(store, changes):
    with pytest.raises(ValueError):
        store.robot(robot_body(**changes), ACTOR)
    assert store.snapshot()['robots'] == []


def test_cross_project_robot_is_rejected_even_if_database_contains_it(store, tmp_path):
    body, profile = setup(store)
    # Separate project registries cannot resolve each other's reference IDs.
    other = Tasks(tmp_path / 'other.sqlite', 'project-b')
    with pytest.raises(ValueError):
        other.task(body, ACTOR, profile)


def test_unsupported_adapter_or_robot_is_registered_as_blocked(store):
    robot = store.robot(robot_body(kind='mobile'), ACTOR)
    body = dict(request_id=uid(), name='Navigate', objective='Reach target',
        success='Arrived', failure='Blocked', reset='Return', mode='independent',
        participants=[dict(robot_id=robot['id'], component_id='base', role='navigate')],
        adapter='navigation')
    task = store.task(body, ACTOR)
    assert task['runnable'] is False and task['blocked_reason']
    with pytest.raises(ValueError):
        store.resolve(task['id'], 'dataset', 'a' * 64, 'b' * 64, ['base'], 'ai')


def test_task_transfer_keeps_semantic_identity_and_local_attribution(store, tmp_path):
    body, profile = setup(store)
    task = store.task(body, ACTOR, profile)
    package = store.export_task(task['id'])
    other = Tasks(tmp_path / 'ai.sqlite', 'project-a')
    imported = other.import_task(package, {'user_id': 'bob'})
    assert imported['id'] == task['id'] and imported['revision'] == task['revision']
    assert imported['created_by'] == {'kind': 'authenticated', 'id': 'bob'}
    assert other.import_task(package, ACTOR) == imported
    model = store.resolve(task['id'], 'data', 'a' * 64, profile['revision'], ['arm_a', 'arm_b'], 'model')
    ai = other.resolve(task['id'], 'data', 'a' * 64, profile['revision'], ['arm_a', 'arm_b'], 'ai')
    assert model['participants'] == ai['participants']
    assert model['task_revision'] == ai['task_revision']
    assert model['compute_host'] == 'model' and ai['compute_host'] == 'ai'
    clean = Tasks(tmp_path / 'clean.sqlite', 'project-a')
    for changes in [dict(project_id='other'), dict(task_revision='b' * 64),
                    dict(task=dict(package['task'], objective='Tampered'))]:
        with pytest.raises(ValueError):
            clean.import_task(dict(package, **changes), ACTOR)
        assert clean.snapshot() == {'robots': [], 'tasks': []}
