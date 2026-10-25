"""Real file/SQLite lifecycle; only the remote HF bytes are substituted."""
from contextlib import contextmanager
import hashlib
import importlib
import json
import shutil

import pytest

from storage_inventory import StorageInventory
from test_learning_accounts import accounts  # noqa: F401
from test_storage_pool import pool_setup  # noqa: F401


class Remote:
    def __init__(self):
        self.revisions = {}
        self.commits = 0
        self.break_read = False
        self.unknown_commit = False
        self.corrupt = False
        self.private = True

    def info(self, assignment, token):
        return dict(private=self.private, sha='a' * 40)

    def commit(self, assignment, streams, token):
        self.commits += 1
        self.revisions['b' * 40] = {name: stream.read() for name, stream in streams.items()}
        if self.unknown_commit:
            raise TimeoutError('secret hf_token must not enter job error')
        return 'b' * 40

    def chunks(self, assignment, name, token):
        if self.break_read:
            raise OSError('HTTP429 secret hf_token')
        data = self.revisions[assignment['revision']][name]
        yield b'wrong' if self.corrupt else data


@pytest.fixture
def jobs_setup(tmp_path, pool_setup, accounts):
    pool_build, actor, config, now = pool_setup
    for value in config['quotas'].values(): value['remaining_bytes'] = 1024 ** 2
    source = tmp_path / 'raw'; source.mkdir()
    cache = tmp_path / 'cache'; cache.mkdir()
    artifact = source / 'run-one'; artifact.mkdir()
    (artifact / 'images').mkdir()
    (artifact / 'images/frame.png').write_bytes(b'frame-bytes')
    (artifact / 'result.json').write_text('{"status":"SUCCEEDED","seed":42}')
    files = {name: dict(bytes=len((artifact / name).read_bytes()),
                       sha256=hashlib.sha256((artifact / name).read_bytes()).hexdigest())
             for name in ('images/frame.png', 'result.json')}
    manifest = dict(schema='rosy.storage-source/1', status='completed', profile='isaac', files=files,
                    provenance=dict(run_id='run-one', seed=42, source_revision='c' * 40))
    (artifact / 'storage-source.json').write_text(json.dumps(manifest))
    cfg = dict(project_id='one', reserve_bytes=0, pool=dict(managed_root_id='cache'), roots=[
        dict(id='raw', label='Completed outputs', role='raw', path=str(source), reclaimable=True),
        dict(id='cache', label='Working cache', role='cache', path=str(cache))])
    inventory = StorageInventory(tmp_path / 'jobs.db', cfg, 'one')
    remote = Remote()
    def build():
        assert importlib.util.find_spec('storage_jobs'), 'durable storage jobs are missing'
        return importlib.import_module('storage_jobs').StorageJobs(inventory, pool_build(), accounts, transport=remote)
    return build, actor, remote, artifact, cache, inventory


def create(build, actor):
    return build().create(actor, dict(source_id='raw', artifact_id='run-one', profile='isaac'))


def test_upload_reclaims_and_restores_same_revision_after_restart(jobs_setup):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    queued = create(build, actor)
    assert queued['status'] == 'queued'
    verified = build().run(actor, queued['id'])
    assert verified['status'] == 'verified' and verified['revision'] == 'b' * 40
    assert verified['bytes_verified'] is True and verified['provenance']['seed'] == 42
    assert not list(cache.iterdir()), 'upload readback must not duplicate the dataset on disk'
    reclaimed = build().reclaim(actor, queued['id'], queued['id'])
    assert reclaimed['local_present'] is False and not artifact.exists()
    restored = build().restore(actor, queued['id'])
    assert restored['local_present'] is True and restored['status'] == 'verified'
    with build().use(actor, queued['id']) as local:
        assert (local / 'images/frame.png').read_bytes() == b'frame-bytes'
        assert json.loads((local / 'result.json').read_text())['seed'] == 42
    assert remote.commits == 1


def test_post_commit_failure_retries_only_readback(jobs_setup):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    job = create(build, actor)
    remote.break_read = True
    failed = build().run(actor, job['id'])
    assert failed['status'] == 'failed' and failed['revision'] == 'b' * 40
    assert 'hf_token' not in json.dumps(failed)
    assert artifact.exists()
    remote.break_read = False
    assert build().run(actor, job['id'])['status'] == 'verified'
    assert remote.commits == 1


def test_uncertain_commit_never_reuploads_or_releases_local_source(jobs_setup):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    job = create(build, actor)
    remote.unknown_commit = True
    result = build().run(actor, job['id'])
    assert result['status'] == 'hold' and result['error'] == 'upload_outcome_unknown'
    assert build().run(actor, job['id'])['status'] == 'hold'
    with pytest.raises(ValueError): build().reclaim(actor, job['id'], job['id'])
    assert artifact.exists() and remote.commits == 1


@pytest.mark.parametrize('mutation', ['changed', 'extra', 'symlink', 'incomplete', 'usd', 'missing'])
def test_source_manifest_is_exact_and_completion_required(jobs_setup, mutation):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    if mutation == 'changed': (artifact / 'images/frame.png').write_bytes(b'changed')
    if mutation == 'extra': (artifact / 'extra.json').write_text('{}')
    if mutation == 'symlink':
        (artifact / 'images/frame.png').unlink()
        (artifact / 'images/frame.png').symlink_to(artifact / 'result.json')
    if mutation == 'missing': (artifact / 'images/frame.png').unlink()
    if mutation in ('incomplete', 'usd'):
        data = json.loads((artifact / 'storage-source.json').read_text())
        if mutation == 'incomplete': data['status'] = 'running'
        else:
            (artifact / 'asset.usd').write_bytes(b'asset')
            data['files']['asset.usd'] = dict(bytes=5, sha256=hashlib.sha256(b'asset').hexdigest())
        (artifact / 'storage-source.json').write_text(json.dumps(data))
    with pytest.raises(ValueError): create(build, actor)
    assert remote.commits == 0


def test_modified_or_additional_local_bytes_block_reclaim(jobs_setup):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    job = create(build, actor); build().run(actor, job['id'])
    (artifact / 'unuploaded.json').write_text('{}')
    with pytest.raises(ValueError): build().reclaim(actor, job['id'], job['id'])
    assert (artifact / 'images/frame.png').read_bytes() == b'frame-bytes'


def test_live_consumer_and_pin_block_reclaim(jobs_setup):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    service = build(); job = service.create(actor, dict(source_id='raw', artifact_id='run-one', profile='isaac'))
    service.run(actor, job['id'])
    with service.use(actor, job['id']):
        with pytest.raises(ValueError, match='use'): build().reclaim(actor, job['id'], job['id'])
    service.pin(actor, job['id'], True)
    with pytest.raises(ValueError, match='pin'): build().reclaim(actor, job['id'], job['id'])
    assert artifact.exists()


def test_wrong_confirmation_and_disabled_source_reclaim_keep_data(jobs_setup):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    job = create(build, actor); build().run(actor, job['id'])
    with pytest.raises(ValueError): build().reclaim(actor, job['id'], 'different')
    inventory.config['roots'][0]['reclaimable'] = False
    with pytest.raises(ValueError): build().reclaim(actor, job['id'], job['id'])
    assert artifact.exists()


def test_revocation_after_upload_forbids_remote_reads_and_cleanup(jobs_setup, accounts):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    job = create(build, actor); build().run(actor, job['id'])
    assigned = build().pool.assignment(actor, job['id'])
    accounts.disconnect(actor, assigned['connection_id'])
    with pytest.raises(PermissionError): build().reclaim(actor, job['id'], job['id'])
    assert artifact.exists()


def test_remote_corruption_and_public_visibility_never_verify(jobs_setup):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    job = create(build, actor)
    remote.corrupt = True
    assert build().run(actor, job['id'])['bytes_verified'] is False
    remote.corrupt = False; remote.private = False
    assert build().run(actor, job['id'])['bytes_verified'] is False
    assert artifact.exists()


def test_restore_enospc_never_publishes_partial_data(jobs_setup, monkeypatch):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    job = create(build, actor); build().run(actor, job['id']); build().reclaim(actor, job['id'], job['id'])
    monkeypatch.setattr('storage_files.free_space', lambda fd: 0)
    with pytest.raises(ValueError, match='space'): build().restore(actor, job['id'])
    assert build().get(actor, job['id'])['local_present'] is False


@pytest.mark.parametrize('relative', ['/etc', '../raw', 'run-one/../run-one', '.hidden', 'run-one\\child'])
def test_archive_rejects_absolute_and_escaping_source_paths(jobs_setup, relative):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    with pytest.raises(ValueError):
        build().create(actor, dict(source_id='raw', artifact_id=relative, profile='isaac'))


def test_replaced_directory_is_not_the_registered_local_source(jobs_setup):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    job = create(build, actor); build().run(actor, job['id'])
    preserved = artifact.with_name('preserved-original')
    artifact.rename(preserved); shutil.copytree(preserved, artifact)
    with pytest.raises(ValueError, match='identity'):
        build().reclaim(actor, job['id'], job['id'])
    assert artifact.exists() and preserved.exists()


def test_cleanup_restart_after_directory_removal_commits_missing_local_state(jobs_setup, monkeypatch):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    service = build(); job = create(build, actor); service.run(actor, job['id'])
    save = service._save
    def crash(record, **changes):
        if changes.get('local', 'unchanged') is None:
            raise OSError('process failed after directory removal')
        return save(record, **changes)
    monkeypatch.setattr(service, '_save', crash)
    with pytest.raises(OSError): service.reclaim(actor, job['id'], job['id'])
    assert not artifact.exists()
    assert build().reclaim(actor, job['id'], job['id'])['local_present'] is False


def test_restore_restart_recognizes_already_published_verified_directory(jobs_setup, monkeypatch):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    job = create(build, actor); service = build()
    service.run(actor, job['id']); service.reclaim(actor, job['id'], job['id'])
    save = service._save
    def crash(record, **changes):
        if changes.get('local'): raise OSError('process failed after restoration publish')
        return save(record, **changes)
    monkeypatch.setattr(service, '_save', crash)
    with pytest.raises(OSError): service.restore(actor, job['id'])
    assert (cache / job['id'] / 'images/frame.png').read_bytes() == b'frame-bytes'
    assert build().restore(actor, job['id'])['local_present'] is True


def test_cache_policy_reclaims_only_unpinned_managed_cache_copies(jobs_setup):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    job = create(build, actor); build().run(actor, job['id'])
    inventory.config['pool']['cache_policy'] = dict(enabled=True, max_bytes=0)
    assert build().reclaim_cache(actor)['reclaimed_bytes'] == 0
    assert artifact.exists(), 'automatic policy must never delete source outputs'
    inventory.config['pool']['cache_policy']['enabled'] = False
    build().reclaim(actor, job['id'], job['id']); build().restore(actor, job['id'])
    inventory.config['pool']['cache_policy']['enabled'] = True
    build().pin(actor, job['id'], True)
    assert build().reclaim_cache(actor)['reclaimed_bytes'] == 0
    build().pin(actor, job['id'], False)
    result = build().reclaim_cache(actor)
    assert result['reclaimed_bytes'] > 0 and not (cache / job['id']).exists()


def test_consumer_lease_survives_other_service_startup(jobs_setup):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    job = create(build, actor); build().run(actor, job['id'])
    with build().use(actor, job['id']):
        with pytest.raises(ValueError, match='use'):
            build().reclaim(actor, job['id'], job['id'])
    assert artifact.exists()
