"""Persistent UI setup uses real Accounts/SQLite and normal archive jobs."""
import base64
import copy
import hashlib
import importlib
import json
import uuid
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


def test_preparation_retry_uses_the_same_verified_archive(setup_case):
    from storage_prepare import StoragePrepare
    build, actor, body, now, artifact, remote = setup_case
    for quota in body['quotas'].values(): quota['remaining_bytes'] = 1048576
    build().save(actor, body); build().verify(actor, 1); build().activate(actor, 1)
    _, config = build().configuration()
    root = Path(next(row['path'] for row in config['roots'] if row['id'] == 'exports'))
    folder = root / 'episode'; folder.mkdir(); (folder / 'frame.json').write_text('{}')
    request = dict(kind='folder', artifact_id='episode', profile='dataset', provenance={}, confirm_completed=True, archive=True)
    first = StoragePrepare(build()).prepare(actor, request)
    second = StoragePrepare(build()).prepare(actor, request)
    assert first['id'] == second['id'] and first['bytes_verified'] and remote.commits == 3


def test_activation_rechecks_remote_privacy(setup_case):
    build, actor, body, now, artifact, remote = setup_case
    for quota in body['quotas'].values(): quota['remaining_bytes'] = 1048576
    build().save(actor, body); build().verify(actor, 1)
    remote.private = False
    with pytest.raises(ValueError, match='private'): build().activate(actor, 1)
    assert build().snapshot(actor)['enabled'] is False


def test_isaac_preparation_reads_final_owner_artifacts_without_starting_sdk(setup_case, monkeypatch, tmp_path):
    from storage_prepare import StoragePrepare
    build, actor, body, now, artifact, remote = setup_case
    for quota in body['quotas'].values(): quota['remaining_bytes'] = 1048576
    build().save(actor, body); build().verify(actor, 1); build().activate(actor, 1)
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'learning/envs/isaac'))
    from run_store import RunStore
    store = RunStore(tmp_path / 'owner')
    row = store.create(uuid.uuid4().hex, 'omx-f-import', {'seed': 42}, 'c' * 40)
    calls, fail = [], [True]
    class Runs:
        def call(self, request):
            calls.append(request['action'])
            if request['action'] == 'list': return store.list()
            if request['action'] == 'status': return store.get(request['run_id'])
            assert request['action'] == 'artifact'
            if fail[0]:
                fail[0] = False
                raise OSError('owner artifact temporarily unavailable')
            result = store.artifact(request['run_id'], request['artifact_id'])
            return dict(result, data_base64=base64.b64encode(result['data']).decode())
    prepare = StoragePrepare(build(), Runs())
    request = dict(kind='isaac', run_id=row['run_id'], confirm_completed=True, archive=True)
    with pytest.raises(ValueError, match='final'): prepare.prepare(actor, request)
    row = store.update(row['run_id'], 0, dict(status='RUNNING'))
    raw = b'{"completed_frames":120}'
    (store.root / 'runs' / row['run_id'] / 'import-report.json').write_bytes(raw)
    store.finish(row['run_id'], row['revision'], dict(status='SUCCEEDED', stage='model_import', import_verified=True,
        completed_frames=120, task_success=None, cleanup='OWNED_PROCESSES_EXITED_GPU_RELEASED'),
        [dict(id='import-report', name='import-report.json', media_type='application/json',
              bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())])
    assert prepare.sim_sources(actor)['runs'][0]['run_id'] == row['run_id']
    with pytest.raises(OSError): prepare.prepare(actor, request)
    _, config = build().configuration()
    export_root = Path(next(item['path'] for item in config['roots'] if item['id'] == 'exports'))
    exported = export_root / ('isaac-' + row['run_id']) / 'import-report.json'
    exported.write_bytes(raw[:6])
    result = prepare.prepare(actor, request)
    assert exported.read_bytes() == raw
    assert result['bytes_verified'] and result['provenance']['seed'] == 42
    assert set(calls) == {'list', 'status', 'artifact'}


def test_removing_all_targets_retains_historic_job_recovery(setup_case):
    build, actor, body, now, artifact, remote = setup_case
    for quota in body['quotas'].values(): quota['remaining_bytes'] = 1048576
    build().save(actor, body); build().verify(actor, 1); build().activate(actor, 1)
    service = build().jobs()
    job = service.create(actor, dict(source_id='raw', artifact_id='run-one', profile='isaac'))
    service.run(actor, job['id']); service.reclaim(actor, job['id'], job['id'])
    build().save(actor, dict(body, revision=2, targets=[], quotas={}))
    assert build().jobs().get(actor, job['id'])['bytes_verified']
    assert build().jobs().restore(actor, job['id'])['local_present'] is True


def test_cancelled_preparation_can_start_a_fresh_confirmed_allocation(setup_case, monkeypatch):
    from storage_prepare import StoragePrepare
    build, actor, body, now, artifact, remote = setup_case
    for quota in body['quotas'].values(): quota['remaining_bytes'] = 1048576
    build().save(actor, body); build().verify(actor, 1); build().activate(actor, 1)
    _, config = build().configuration()
    root = Path(next(row['path'] for row in config['roots'] if row['id'] == 'exports'))
    folder = root / 'episode'; folder.mkdir(); (folder / 'frame.json').write_text('{}')
    request = dict(kind='folder', artifact_id='episode', profile='dataset', provenance={}, confirm_completed=True, archive=True)
    info = remote.info
    def unavailable(*args): raise OSError('temporary provider failure')
    monkeypatch.setattr(remote, 'info', unavailable)
    first = StoragePrepare(build()).prepare(actor, request)
    assert first['status'] == 'failed'
    build().jobs().cancel(actor, first['id'])
    monkeypatch.setattr(remote, 'info', info)
    second = StoragePrepare(build()).prepare(actor, request)
    assert second['id'] != first['id'] and second['bytes_verified'] and remote.commits == 3


def test_cancelled_probe_can_be_verified_again_after_repair(setup_case, monkeypatch):
    build, actor, body, now, artifact, remote = setup_case
    for quota in body['quotas'].values(): quota['remaining_bytes'] = 1048576
    build().save(actor, body)
    info = remote.info
    def unavailable(*args): raise OSError('temporary provider failure')
    monkeypatch.setattr(remote, 'info', unavailable)
    first = build().verify(actor, 1)
    for job in first['jobs']: build().jobs().cancel(actor, job['id'])
    monkeypatch.setattr(remote, 'info', info)
    assert build().verify(actor, 1)['status'] == 'verified'
    assert build().activate(actor, 1)['enabled']
    assert remote.commits == 2


def test_other_members_personal_target_is_redacted_and_preserved(setup_case, accounts):
    from test_learning_repos import identified
    build, actor, body, now, artifact, remote = setup_case
    config = json.loads(accounts.config_path.read_text())
    config['users'][1]['memberships']['one'] += ['publish', 'manage']
    accounts.config_path.write_text(json.dumps(config))
    _, bob = sign_in(accounts, 'bob')
    connection = accounts.connect_token(bob, 'hf_x', transport=identified('write'))
    service = build()
    service.base['pool']['targets'].append(dict(id='private-bob', connection_id=connection['connection_id'],
        repo_id='account-x/private', repo_type='dataset', quota_owner='account-x', priority=3, enabled=True))
    service.base['pool']['quotas']['account-x'] = copy.deepcopy(body['quotas']['first'])
    snapshot = service.snapshot(actor)
    assert 'account-x' not in json.dumps(snapshot) and 'private-bob' in json.dumps(snapshot)
    saved = service.save(actor, body)
    _, current = service.configuration()
    assert next(row for row in current['pool']['targets'] if row['id'] == 'private-bob')['enabled'] is True
    body['revision'] = saved['revision']; body['targets'].append(dict(id='private-bob', enabled=False))
    service.save(actor, body)
    _, current = service.configuration()
    assert next(row for row in current['pool']['targets'] if row['id'] == 'private-bob')['enabled'] is False


@pytest.mark.parametrize('field,value', [('id', {}), ('connection_id', [])])
def test_invalid_json_target_types_are_validation_errors(setup_case, field, value):
    build, actor, body, now, artifact, remote = setup_case
    body['targets'][0][field] = value
    with pytest.raises(ValueError): build().save(actor, body)
