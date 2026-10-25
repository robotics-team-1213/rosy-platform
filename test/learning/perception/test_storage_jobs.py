"""Real file/SQLite lifecycle; only the remote HF bytes are substituted."""
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib
import json
import os
import shutil
import threading
from pathlib import Path

import pytest

from storage_inventory import StorageInventory
from test_learning_accounts import accounts, sign_in  # noqa: F401
from test_storage_pool import pool_setup  # noqa: F401


class Remote:
    def __init__(self):
        self.revisions = {}
        self.commits = 0
        self.break_read = False
        self.unknown_commit = False
        self.corrupt = False
        self.private = True
        self.fail_on_commit = None
        self.latest = None

    def info(self, assignment, token):
        return dict(private=self.private, sha='a' * 40)

    def commit(self, assignment, streams, token):
        self.commits += 1
        revision = 'b' * 40 if self.commits == 1 else f'{self.commits:040x}'
        content = dict(self.revisions[self.latest]) if self.latest else {}
        content.update({name: stream.read() for name, stream in streams.items()})
        self.revisions[revision] = content
        self.latest = revision
        if self.unknown_commit or self.fail_on_commit == self.commits:
            raise TimeoutError('secret hf_token must not enter job error')
        return revision

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


def test_native_training_consumer_prevents_reclaim(jobs_setup, tmp_path, monkeypatch):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    job = create(build, actor); build().run(actor, job['id'])
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'learning/training/omx'))
    import experiment_train
    monkeypatch.setattr(experiment_train, 'load_dataset', lambda *args, **kwargs: object())
    def fitting(*args, **kwargs):
        with pytest.raises(ValueError, match='use'):
            build().reclaim(actor, job['id'], job['id'])
    monkeypatch.setattr(experiment_train, 'train_dataset', fitting)
    experiment_train.train(artifact, tmp_path / 'new-training-output')
    assert artifact.exists()


def test_cache_budget_is_rechecked_after_worker_admission(jobs_setup, monkeypatch):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    first, second = create(build, actor), create(build, actor)
    build().run(actor, first['id']); build().run(actor, second['id'])
    build().reclaim(actor, first['id'], first['id'])
    inventory.config['pool']['cache_policy'] = dict(enabled=True, max_bytes=first['upload_bytes'])
    waiting, proceed = threading.Event(), threading.Event()
    service = build(); reclaim = service.reclaim_cache
    def previous_snapshot(*args, **kwargs):
        value = reclaim(*args, **kwargs)
        waiting.set()
        assert proceed.wait(10)
        return value
    monkeypatch.setattr(service, 'reclaim_cache', previous_snapshot)
    with ThreadPoolExecutor(max_workers=1) as executor:
        later = executor.submit(service.restore, actor, second['id'])
        assert waiting.wait(10)
        try: build().restore(actor, first['id'])
        finally: proceed.set()
        try: later.result()
        except ValueError: pass
    assert sum(1 for path in cache.iterdir() if not path.name.startswith('.')) <= 1


def test_process_death_cannot_leave_reservation_without_its_job(jobs_setup):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    service = build()
    before = service.pool.snapshot(actor)['targets'][0]['available_bytes']
    pid = os.fork()
    if pid == 0:
        service._save = lambda *args, **kwargs: os._exit(23)
        service.create(actor, dict(source_id='raw', artifact_id='run-one', profile='isaac'))
        os._exit(99)
    _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 23
    assert build().pool.snapshot(actor)['targets'][0]['available_bytes'] == before
    assert build().list(actor) == []


def test_file_added_after_cleanup_verification_is_never_deleted(jobs_setup, monkeypatch):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    service = build(); job = create(build, actor); service.run(actor, job['id'])
    verify = service.files.verify
    def inserted(location, expected, **kwargs):
        verify(location, expected, **kwargs)
        if kwargs.get('subset'):
            (service.files.path(location) / 'unuploaded.json').write_bytes(b'keep-late-data')
    monkeypatch.setattr(service.files, 'verify', inserted)
    with pytest.raises(ValueError): service.reclaim(actor, job['id'], job['id'])
    kept = list(artifact.parent.rglob('unuploaded.json'))
    assert len(kept) == 1 and kept[0].read_bytes() == b'keep-late-data'


def test_cancel_unstarted_job_returns_capacity_but_keeps_source(jobs_setup):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    service = build(); before = service.pool.snapshot(actor)['targets'][0]['available_bytes']
    job = create(build, actor)
    assert service.cancel(actor, job['id'])['status'] == 'cancelled'
    assert build().pool.snapshot(actor)['targets'][0]['available_bytes'] == before
    assert build().run(actor, job['id'])['status'] == 'cancelled'
    assert artifact.exists() and remote.commits == 0


def test_known_commit_reconciles_unknown_outcome_without_reupload(jobs_setup):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    job = create(build, actor); remote.unknown_commit = True
    assert build().run(actor, job['id'])['status'] == 'hold'
    with pytest.raises(ValueError): build().cancel(actor, job['id'])
    with pytest.raises(ValueError): build().reconcile(actor, job['id'], 'c' * 40)
    verified = build().reconcile(actor, job['id'], 'b' * 40)
    assert verified['bytes_verified'] is True and verified['status'] == 'verified'
    assert remote.commits == 1 and artifact.exists()


@pytest.mark.parametrize('bad_id', [None, [], {}, 1])
def test_non_string_source_id_is_a_validation_error(jobs_setup, bad_id):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    with pytest.raises(ValueError):
        build().create(actor, dict(source_id=bad_id, artifact_id='run-one', profile='isaac'))


def many_files(artifact):
    source = json.loads((artifact / 'storage-source.json').read_text())
    for number in range(96):
        name = f'images/extra-{number:03}.png'
        raw = f'frame-{number}'.encode(); (artifact / name).write_bytes(raw)
        source['files'][name] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    (artifact / 'storage-source.json').write_text(json.dumps(source))


def test_many_files_upload_in_bounded_descriptor_batches(jobs_setup, monkeypatch):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    many_files(artifact); baseline = len(os.listdir('/proc/self/fd')); commit = remote.commit
    def bounded(assignment, streams, token):
        if len(os.listdir('/proc/self/fd')) > baseline + 48:
            raise ValueError('all source files were opened at once')
        return commit(assignment, streams, token)
    monkeypatch.setattr(remote, 'commit', bounded)
    job = create(build, actor)
    verified = build().run(actor, job['id'])
    assert verified['status'] == 'verified' and remote.commits == 4
    assert verified['files_uploaded'] == verified['files_total'] == 99


def test_restart_continues_confirmed_batches_without_rewriting_them(jobs_setup, monkeypatch):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    many_files(artifact); service = build(); job = create(build, actor); save = service._save
    def interrupted(record, **changes):
        save(record, **changes)
        if len(changes.get('uploaded_files', [])) == 32:
            raise KeyboardInterrupt('worker exited after a confirmed batch')
    monkeypatch.setattr(service, '_save', interrupted)
    with pytest.raises(KeyboardInterrupt): service.run(actor, job['id'])
    assert build().get(actor, job['id'])['files_uploaded'] == 32
    assert build().run(actor, job['id'])['status'] == 'verified'
    assert remote.commits == 4


def test_uncertain_middle_batch_reconciles_then_finishes_same_target(jobs_setup):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    many_files(artifact); remote.fail_on_commit = 2
    job = create(build, actor)
    assert build().run(actor, job['id'])['status'] == 'hold'
    partial = build().reconcile(actor, job['id'], f'{2:040x}')
    assert partial['files_uploaded'] == 64 and partial['bytes_verified'] is False
    verified = build().run(actor, job['id'])
    assert verified['status'] == 'verified' and verified['target_id'] == job['target_id']
    assert remote.commits == 4


def test_revoked_connection_stops_later_upload_source_reads(jobs_setup, accounts, monkeypatch):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    job = create(build, actor); service = build()
    connection = service.pool.assignment(actor, job['id'])['connection_id']; sent = []
    def upload(assignment, streams, token):
        first, *later = list(streams.values())
        sent.append(first.read())
        accounts.disconnect(actor, connection)
        for stream in later: sent.append(stream.read())
        return 'b' * 40
    monkeypatch.setattr(remote, 'commit', upload)
    outcome = service.run(actor, job['id'])
    assert len(sent) == 1 and outcome['bytes_verified'] is False
    assert artifact.exists()


def test_project_cache_limit_counts_other_members_copies(jobs_setup, accounts):
    build, alice, remote, artifact, cache, inventory = jobs_setup
    config = json.loads(accounts.config_path.read_text())
    config['users'][1]['memberships']['one'] += ['publish', 'manage']
    accounts.config_path.write_text(json.dumps(config))
    _, bob = sign_in(accounts, 'bob')
    first, second = create(build, alice), create(build, bob)
    build().run(alice, first['id']); build().run(bob, second['id'])
    build().reclaim(alice, first['id'], first['id']); build().restore(alice, first['id'])
    inventory.config['pool']['cache_policy'] = dict(enabled=True, max_bytes=first['upload_bytes'])
    with pytest.raises(ValueError, match='space'): build().restore(bob, second['id'])
    assert (cache / first['id']).is_dir() and not (cache / second['id']).exists()


def test_cancel_process_death_keeps_job_and_reservation_consistent(jobs_setup):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    service = build(); job = create(build, actor)
    pid = os.fork()
    if pid == 0:
        service._save = lambda *args, **kwargs: os._exit(23)
        service.cancel(actor, job['id'])
        os._exit(99)
    _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 23
    assert build().pool.assignment(actor, job['id'])['status'] == 'reserved'
    assert build().run(actor, job['id'])['bytes_verified'] is True


def test_released_allocation_never_writes_remote_bytes(jobs_setup):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    job = create(build, actor); build().pool.release(actor, job['id'])
    assert build().run(actor, job['id'])['bytes_verified'] is False
    assert remote.commits == 0


def test_publish_only_restore_with_cache_policy_and_sufficient_space(jobs_setup, accounts):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    job = create(build, actor); build().run(actor, job['id'])
    build().reclaim(actor, job['id'], job['id'])
    config = json.loads(accounts.config_path.read_text())
    config['users'][0]['memberships']['one'].remove('manage')
    accounts.config_path.write_text(json.dumps(config))
    inventory.config['pool']['cache_policy'] = dict(enabled=True, max_bytes=job['upload_bytes'])
    assert build().restore(actor, job['id'])['local_present'] is True


def test_cache_reclaim_skips_busy_oldest_copy(jobs_setup):
    from storage_files import consumer
    build, actor, remote, artifact, cache, inventory = jobs_setup
    first, second = create(build, actor), create(build, actor)
    build().run(actor, first['id']); build().run(actor, second['id'])
    build().reclaim(actor, first['id'], first['id'])
    build().restore(actor, first['id']); build().restore(actor, second['id'])
    inventory.config['pool']['cache_policy'] = dict(enabled=True, max_bytes=first['upload_bytes'])
    with consumer(cache / first['id']):
        result = build().reclaim_cache(actor)
    assert result == dict(status='ready', reclaimed_bytes=second['upload_bytes'])
    assert (cache / first['id']).exists() and not (cache / second['id']).exists()


def test_job_listing_limits_only_requesters_history(jobs_setup):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    service = build(); job = create(build, actor)
    other = service._load(job['id'])
    for index in range(201):
        service._save(dict(other, id=f'{index:032x}', requester_id='bob'))
    assert [row['id'] for row in service.list(actor)] == [job['id']]


def test_official_native_cycle_holds_managed_inputs(jobs_setup, monkeypatch, tmp_path):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    job = create(build, actor); build().run(actor, job['id'])
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'learning/training/omx'))
    import native_cycle
    def validate(root):
        with pytest.raises(ValueError, match='use'):
            build().reclaim(actor, job['id'], job['id'])
        raise RuntimeError('stop before training')
    monkeypatch.setattr(native_cycle, 'validate_split', validate)
    with pytest.raises(RuntimeError, match='stop before training'):
        native_cycle.run_cycle(artifact, tmp_path / 'cycle')
