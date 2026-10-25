"""Persistent UI setup uses real Accounts/SQLite and normal archive jobs."""
import copy
import importlib
import json
from pathlib import Path

import pytest

from storage_inventory import StorageInventory
from test_learning_accounts import accounts, sign_in  # noqa: F401
from test_storage_pool import pool_setup  # noqa: F401
from test_storage_jobs import jobs_setup, Remote  # noqa: F401


@pytest.fixture
def setup_case(jobs_setup, pool_setup, accounts):
    _, actor, remote, artifact, cache, inventory = jobs_setup
    _, _, pool_config, now = pool_setup
    config = copy.deepcopy(inventory.config)
    config['pool'].update(pool_config, enabled=False, cache_policy=dict(enabled=False, max_bytes=1048576))
    inventory = StorageInventory(inventory.db, config, 'one')
    def build():
        assert importlib.util.find_spec('storage_setup'), 'UI storage setup is missing'
        return importlib.import_module('storage_setup').StorageSetup(
            inventory.db, accounts, inventory, clock=lambda: now[0], transport=remote)
    body = dict(revision=0, targets=pool_config['targets'], quotas=pool_config['quotas'],
                reserve_bytes=0, cache_policy=dict(enabled=False, max_bytes=1048576))
    return build, actor, body, now, artifact, remote


def test_setup_survives_restart_without_rewriting_host_paths(setup_case):
    build, actor, body, now, artifact, remote = setup_case
    result = build().save(actor, body)
    assert result['revision'] == 1 and result['enabled'] is False
    again = build().snapshot(actor)
    assert again['targets'][0]['repo_id'] == 'first/episodes'
    assert 'hf_0' not in json.dumps(again) and str(artifact.parent) not in json.dumps(again)
    assert again['quotas']['first']['measured_at'] == 90
    with pytest.raises(ValueError, match='revision'): build().save(actor, body)


@pytest.mark.parametrize('field,value', [('roots', []), ('enabled', True), ('project_id', 'two'), ('command', 'pip install')])
def test_setup_rejects_host_and_activation_fields(setup_case, field, value):
    build, actor, body, now, artifact, remote = setup_case
    with pytest.raises(ValueError): build().save(actor, dict(body, **{field: value}))
    assert build().snapshot(actor)['revision'] == 0


def test_activation_requires_actual_private_roundtrip_and_fresh_capacity(setup_case):
    build, actor, body, now, artifact, remote = setup_case
    for quota in body['quotas'].values(): quota['remaining_bytes'] = 1048576
    saved = build().save(actor, body)
    with pytest.raises(ValueError, match='verif'): build().activate(actor, saved['revision'])
    checked = build().verify(actor, saved['revision'])
    assert checked['status'] == 'verified' and remote.commits == 2
    assert all(row['bytes_verified'] for row in checked['jobs'])
    active = build().activate(actor, saved['revision'])
    assert active['enabled'] is True and active['revision'] == 2
    assert len(build().jobs().list(actor)) == 2
    now[0] = 201
    with pytest.raises(ValueError, match='quota'): build().activate(actor, active['revision'])


def test_failed_probe_never_activates_or_reassigns_its_remote_outcome(setup_case):
    build, actor, body, now, artifact, remote = setup_case
    for quota in body['quotas'].values(): quota['remaining_bytes'] = 1048576
    build().save(actor, body); remote.unknown_commit = True
    checked = build().verify(actor, 1)
    assert checked['status'] == 'blocked'
    held = [job for job in build().jobs().list(actor) if job['status'] == 'hold']
    assert held and all(job['local_present'] for job in held)
    commits = remote.commits
    build().verify(actor, 1)
    assert remote.commits == commits, 'unknown probe outcomes must use normal reconcile, never a replacement upload'
    with pytest.raises(ValueError): build().activate(actor, 1)


def test_saved_edits_pause_new_assignments_but_preserve_old_recovery(setup_case):
    build, actor, body, now, artifact, remote = setup_case
    for quota in body['quotas'].values(): quota['remaining_bytes'] = 1048576
    build().save(actor, body); build().verify(actor, 1); build().activate(actor, 1)
    service = build().jobs()
    job = service.create(actor, dict(source_id='raw', artifact_id='run-one', profile='isaac'))
    assert service.run(actor, job['id'])['bytes_verified'] is True
    body['revision'] = 2
    assert build().save(actor, body)['enabled'] is False
    with pytest.raises(ValueError, match='settings'): service.create(actor, dict(source_id='raw', artifact_id='run-one', profile='isaac'))
    current = build().jobs()
    assert current.reclaim(actor, job['id'], job['id'])['local_present'] is False
    assert current.restore(actor, job['id'])['local_present'] is True


def test_setup_manager_permissions_are_live_and_other_roles_get_no_config(setup_case, accounts):
    build, actor, body, now, artifact, remote = setup_case
    _, bob = sign_in(accounts, 'bob')
    public = build().snapshot(bob)
    assert public['can_manage'] is False and 'targets' not in public and 'connections' not in public
    with pytest.raises(PermissionError): build().save(bob, body)
    config = json.loads(accounts.config_path.read_text())
    config['users'][0]['memberships']['one'].remove('manage')
    accounts.config_path.write_text(json.dumps(config))
    with pytest.raises(PermissionError): build().save(actor, body)


def test_unknown_quota_can_be_saved_but_not_activated(setup_case):
    build, actor, body, now, artifact, remote = setup_case
    for quota in body['quotas'].values(): quota['expires_at'] = 99
    build().save(actor, body)
    with pytest.raises(ValueError, match='quota'): build().verify(actor, 1)
    assert remote.commits == 0


def test_no_json_setup_uses_dedicated_workspace_roots_only(tmp_path, accounts, pool_setup):
    _, actor, pool_config, now = pool_setup
    assert importlib.util.find_spec('storage_setup'), 'UI storage setup is missing'
    module = importlib.import_module('storage_setup')
    db = tmp_path / 'workspace' / 'review.db'; db.parent.mkdir()
    service = module.StorageSetup(db, accounts, clock=lambda: now[0], transport=Remote())
    assert not (db.parent / 'storage-data').exists()
    body = dict(revision=0, targets=pool_config['targets'], quotas=pool_config['quotas'],
                reserve_bytes=0, cache_policy=dict(enabled=False, max_bytes=1048576))
    service.save(actor, body)
    _, config = service.configuration()
    assert {row['id'] for row in config['roots']} == {'exports', 'cache'}
    assert all(Path(row['path']).is_relative_to(db.parent / 'storage-data') for row in config['roots'])
    assert all(Path(row['path']).is_dir() for row in config['roots'])
