"""Quota belongs to an HF namespace, not to each token or repository."""
from concurrent.futures import ThreadPoolExecutor
import importlib
import json

import pytest

from test_learning_accounts import accounts, sign_in  # noqa: F401
from test_learning_repos import identified, publisher


@pytest.fixture
def pool_setup(tmp_path, accounts):
    assert importlib.util.find_spec('storage_pool'), 'capacity-aware storage pool is missing'
    pool_type = importlib.import_module('storage_pool').StoragePool
    _, actor = publisher(accounts)
    targets = []
    for n, owner in enumerate(('first', 'second')):
        repo = owner + '/episodes'
        connection = accounts.connect_token(actor, 'hf_' + str(n), sharing='project',
            resources=['dataset:' + repo, 'dataset:' + owner + '/other'], transport=identified('write'))
        targets.append(dict(id=owner, connection_id=connection['connection_id'], repo_id=repo,
                            repo_type='dataset', quota_owner=owner, priority=n, enabled=True))
    now = [100]
    config = dict(project_id='one', targets=targets, quotas={owner: dict(remaining_bytes=100,
        reserve_bytes=10, source='admin measurement', measured_at=90, expires_at=200)
        for owner in ('first', 'second')})
    db = tmp_path / 'pool.db'
    build = lambda: pool_type(db, config, accounts, clock=lambda: now[0])
    return build, actor, config, now


def test_full_first_target_assigns_second_and_survives_restart(pool_setup):
    build, actor, config, now = pool_setup
    config['quotas']['first']['remaining_bytes'] = 20
    assigned = build().reserve(actor, 'job-one', 50)
    assert assigned['target_id'] == 'second'
    assert build().assignment(actor, 'job-one')['repo_id'] == 'second/episodes'
    assert 'token' not in json.dumps(assigned)


def test_repositories_and_tokens_in_same_namespace_share_quota(pool_setup):
    build, actor, config, now = pool_setup
    duplicate = dict(config['targets'][0], id='first-other', repo_id='first/other')
    config['targets'].insert(1, duplicate)
    pool = build()
    assert pool.reserve(actor, 'one', 60)['quota_owner'] == 'first'
    assert pool.reserve(actor, 'two', 60)['quota_owner'] == 'second'
    rows = pool.snapshot(actor)['targets']
    assert [row['available_bytes'] for row in rows if row['quota_owner'] == 'first'] == [30, 30]


def test_concurrent_allocators_cannot_spend_same_remaining_bytes(pool_setup):
    build, actor, config, now = pool_setup
    pool = build()
    with ThreadPoolExecutor(max_workers=2) as executor:
        jobs = list(executor.map(lambda name: build().reserve(actor, name, 80), ('one', 'two')))
    assert {job['quota_owner'] for job in jobs} == {'first', 'second'}
    with pytest.raises(ValueError, match='capacity'):
        pool.reserve(actor, 'three', 80)


@pytest.mark.parametrize('measured,expires', [(101, 200), (90, 100)])
def test_stale_or_future_quota_never_allocates(pool_setup, measured, expires):
    build, actor, config, now = pool_setup
    for value in config['quotas'].values():
        value.update(measured_at=measured, expires_at=expires)
    assert {row['status'] for row in build().snapshot(actor)['targets']} == {'unknown'}
    with pytest.raises(ValueError, match='capacity'):
        build().reserve(actor, 'one', 1)


def test_quota_refresh_counts_only_unreflected_commits_and_pending_reservations(pool_setup):
    build, actor, config, now = pool_setup
    pool = build()
    pool.reserve(actor, 'uploaded', 40)
    pool.start(actor, 'uploaded')
    pool.mark_uploaded(actor, 'uploaded', 'a' * 40)
    assert pool.snapshot(actor)['targets'][0]['available_bytes'] == 50
    now[0] = 120
    config['quotas']['first'].update(remaining_bytes=60, measured_at=110)
    assert build().snapshot(actor)['targets'][0]['available_bytes'] == 50
    build().reserve(actor, 'pending', 30)
    assert build().snapshot(actor)['targets'][0]['available_bytes'] == 20
    with pytest.raises(ValueError, match='started'):
        build().release(actor, 'uploaded')


def test_uncertain_upload_reservation_is_not_released_on_restart(pool_setup):
    build, actor, config, now = pool_setup
    build().reserve(actor, 'unknown-outcome', 80)
    build().start(actor, 'unknown-outcome')
    assert build().snapshot(actor)['targets'][0]['available_bytes'] == 10
    with pytest.raises(ValueError, match='started'):
        build().release(actor, 'unknown-outcome')


def test_generation_revocation_and_requester_fences(pool_setup, accounts):
    build, actor, config, now = pool_setup
    pool = build()
    assigned = pool.reserve(actor, 'one', 10)
    _, bob = sign_in(accounts, 'bob')
    with pytest.raises(PermissionError):
        pool.assignment(bob, 'one')
    accounts.disconnect(actor, assigned['connection_id'])
    with pytest.raises(PermissionError):
        pool.assignment(actor, 'one')


def test_repeated_job_id_cannot_change_amount_or_requester(pool_setup):
    build, actor, config, now = pool_setup
    first = build().reserve(actor, 'one', 10)
    assert build().reserve(actor, 'one', 10) == first
    with pytest.raises(ValueError, match='different'):
        build().reserve(actor, 'one', 11)


@pytest.mark.parametrize('mutation', ['duplicate', 'namespace', 'boolean', 'bad-source'])
def test_invalid_configuration_is_rejected(pool_setup, mutation):
    build, actor, config, now = pool_setup
    if mutation == 'duplicate': config['targets'].append(dict(config['targets'][0]))
    if mutation == 'namespace': config['targets'][0]['quota_owner'] = 'second'
    if mutation == 'boolean': config['quotas']['first']['remaining_bytes'] = True
    if mutation == 'bad-source': config['quotas']['first']['source'] = ''
    with pytest.raises(ValueError): build()


def test_project_and_connection_visibility_are_not_bypassed(pool_setup, accounts):
    build, actor, config, now = pool_setup
    config['targets'][0]['connection_id'] = 'not-a-connection'
    assert build().reserve(actor, 'one', 30)['target_id'] == 'second'
    assert build().snapshot(actor)['targets'][0]['status'] == 'unavailable'
    config['project_id'] = 'two'
    with pytest.raises(ValueError, match='project'): build()
