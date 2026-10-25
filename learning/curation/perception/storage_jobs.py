"""Pinned archive/restore jobs; explicit reclaim requires verified, unused local data."""
from contextlib import contextmanager, ExitStack, nullcontext
import errno
import json
import os
import re
import uuid

from storage_files import Files, consume, parts
from storage_hub import StorageHub
from storage_inventory import size


class StorageJobs:
    def __init__(self, inventory, pool, accounts, *, transport=None):
        if inventory.project_id != pool.project_id or inventory.project_id != accounts.project_id:
            raise ValueError('storage services must share a project')
        self.inventory, self.pool, self.accounts = inventory, pool, accounts
        self.project_id, self.files = inventory.project_id, Files(inventory)
        self.policy = inventory.config['pool'].get('cache_policy', dict(enabled=False, max_bytes=0))
        if (not isinstance(self.policy, dict) or set(self.policy) != {'enabled', 'max_bytes'}
                or type(self.policy['enabled']) is not bool):
            raise ValueError('cache policy needs enabled and max_bytes')
        size(self.policy['max_bytes'])
        self.transport = transport or StorageHub()
        self.lock_path = pool.db.with_suffix('.storage.lock')
        with pool.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS storage_jobs
                (project TEXT,id TEXT,document TEXT NOT NULL,PRIMARY KEY(project,id))''')

    @contextmanager
    def _lease(self, *, shared=False):
        if os.name != 'posix': raise ValueError('managed storage operations require POSIX')
        import fcntl
        with os.fdopen(os.open(self.lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600), 'r+b') as stream:
            try:
                fcntl.flock(stream, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
            except OSError as error:
                if error.errno not in (errno.EAGAIN, errno.EACCES): raise
                raise ValueError('managed storage is in use; retry when its owner finishes') from None
            # shortcut: one volume-wide lease serializes transfers and cleanup; split by volume if throughput needs it.
            yield

    def _load(self, job_id):
        if not isinstance(job_id, str) or not re.fullmatch(r'[0-9a-f]{32}', job_id):
            raise ValueError('invalid storage job ID')
        with self.pool.connect() as db:
            row = db.execute('SELECT document FROM storage_jobs WHERE project=? AND id=?',
                             (self.project_id, job_id)).fetchone()
        if row is None: raise ValueError('storage job not found')
        return json.loads(row[0])

    def _save(self, job, *, connection=None, **changes):
        job.update(changes, updated_at=self.pool.clock())
        with (self.pool.connect() if connection is None else nullcontext(connection)) as db:
            db.execute('INSERT OR REPLACE INTO storage_jobs VALUES(?,?,?)',
                       (self.project_id, job['id'], json.dumps(job, allow_nan=False)))

    def _actor(self, actor, job, capability='publish'):
        self.accounts.require(actor, capability)
        if job['project_id'] != self.project_id or job['requester_id'] != actor['user_id']:
            raise PermissionError('storage requester required')

    def _check(self, actor, job, scope='write-repos'):
        self._actor(actor, job)
        return self.pool.credential(actor, job['id'], scope=scope)

    def _public(self, job):
        result = {key: job.get(key) for key in ('id', 'project_id', 'requester_id', 'profile', 'status',
            'revision', 'bytes_verified', 'provenance', 'error', 'pinned', 'created_at', 'updated_at', 'upload_bytes')}
        result.update({key: job.get('assignment', {}).get(key) for key in ('target_id', 'repo_id', 'repo_type')})
        try: present = bool(job.get('local')) and self.files.exists(job['local'])
        except (OSError, ValueError): present = None
        root = self.files.roots.get(job.get('local', {}).get('root_id'), {}) if job.get('local') else {}
        result.update(local_present=present, reclaimable=bool(present and job['bytes_verified']
            and job['status'] == 'verified' and not job['pinned']
            and (root.get('role') == 'cache' or root.get('reclaimable') is True)))
        return result

    def get(self, actor, job_id):
        job = self._load(job_id)
        self._actor(actor, job, 'view')
        return self._public(job)

    def list(self, actor):
        self.accounts.require(actor, 'view')
        with self.pool.connect() as db:
            rows = db.execute('SELECT document FROM storage_jobs WHERE project=? ORDER BY rowid DESC LIMIT 200',
                              (self.project_id,)).fetchall()
        return [self._public(job) for row in rows if (job := json.loads(row[0]))['requester_id'] == actor['user_id']]

    def create(self, actor, body):
        self.accounts.require(actor, 'publish')
        if not isinstance(body, dict) or set(body) != {'source_id', 'artifact_id', 'profile'}:
            raise ValueError('source ID, relative artifact ID and profile required')
        parts(body['artifact_id'])
        if body['source_id'] not in self.files.roots: raise ValueError('unknown source root')
        location = dict(root_id=body['source_id'], relative=body['artifact_id'])
        with self._lease():
            try: manifest = self.files.manifest(location, body['profile'])
            except (OSError, KeyError, TypeError, UnicodeError):
                raise ValueError('completed source manifest is unavailable') from None
            location['identity'] = manifest['identity']
            job = dict(id=uuid.uuid4().hex, project_id=self.project_id, requester_id=actor['user_id'],
                profile=body['profile'], status='queued', local=location, files=manifest['files'],
                provenance=manifest['provenance'], revision=None, bytes_verified=False, pinned=False,
                error=None, created_at=self.pool.clock(), upload_bytes=sum(v['bytes'] for v in manifest['files'].values()))
            with self.pool.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                job['assignment'] = self.pool.reserve(actor, job['id'], job['upload_bytes'], connection=db)
                self._save(job, connection=db)
            return self._public(job)

    def _assignment(self, actor, job, scope='read-repos'):
        cred = self._check(actor, job, scope)
        assigned = dict(job['assignment'])
        if job['revision']: assigned['revision'] = job['revision']
        return assigned, cred['token']

    def _verify_remote(self, actor, job):
        assigned, token = self._assignment(actor, job)
        info = self.transport.info(assigned, token)
        if info.get('private') is not True: raise ValueError('private destination required')
        for name, expected in job['files'].items():
            assigned, token = self._assignment(actor, job)
            consume(self.transport.chunks(assigned, name, token), expected,
                    lambda: self._check(actor, job, 'read-repos'))
        assigned, token = self._assignment(actor, job)
        if self.transport.info(assigned, token).get('private') is not True:
            raise ValueError('destination visibility changed')

    def run(self, actor, job_id):
        with self._lease():
            job = self._load(job_id)
            self._check(actor, job)
            if job['status'] in ('hold', 'reclaiming') or job['bytes_verified']:
                return self._public(job)
            try:
                allocation = self.pool.assignment(actor, job_id)
                if not job['revision'] and allocation['status'] == 'uploading':
                    self._save(job, status='hold', error='upload_outcome_unknown')
                    return self._public(job)
                if not job['revision']:
                    assigned, token = self._assignment(actor, job, 'write-repos')
                    if self.transport.info(assigned, token).get('private') is not True:
                        raise ValueError('private destination required')
                    with self.files.streams(job['local'], job['files']) as streams:
                        self.pool.start(actor, job_id)
                        self._save(job, status='uploading', error=None)
                        revision = self.transport.commit(assigned, streams, token)
                    if not isinstance(revision, str) or not re.fullmatch(r'[0-9a-f]{40}', revision):
                        raise ValueError('immutable destination revision required')
                    self._save(job, revision=revision, status='uploaded')
                self.pool.mark_uploaded(actor, job_id, job['revision'])
                self._save(job, status='verifying', error=None)
                self._verify_remote(actor, job)
                self.files.verify(job['local'], job['files'])
                self._save(job, status='verified', bytes_verified=True)
            except Exception:
                unknown = job['status'] == 'uploading' and not job['revision']
                self._save(job, status='hold' if unknown else 'failed', bytes_verified=False,
                           error='upload_outcome_unknown' if unknown else 'transfer_failed')
            return self._public(job)

    def pin(self, actor, job_id, value):
        if type(value) is not bool: raise ValueError('pinned must be boolean')
        with self._lease():
            job = self._load(job_id)
            self._actor(actor, job, 'manage')
            self._save(job, pinned=value)
            return self._public(job)

    @contextmanager
    def use(self, actor, job_id):
        with self._lease(shared=True):
            job = self._load(job_id)
            self._actor(actor, job, 'view')
            if not job.get('local') or job['status'] != 'verified':
                raise ValueError('verified local managed data is required')
            self.files.verify(job['local'], job['files'])
            self._save(job, last_used_at=self.pool.clock())
            yield self.files.path(job['local'])

    def reclaim(self, actor, job_id, confirmation):
        if confirmation != job_id: raise ValueError('confirm the exact storage job ID')
        with self._lease(), ExitStack() as locks:
            job = self._load(job_id)
            self._actor(actor, job, 'manage')
            self._check(actor, job)
            if job['pinned']: raise ValueError('pinned data cannot be reclaimed')
            if not job['bytes_verified'] or job['status'] not in ('verified', 'reclaiming'):
                raise ValueError('verified remote archive required before reclaim')
            if not job.get('local'): return self._public(job)
            root = self.files.roots[job['local']['root_id']]
            if root['role'] != 'cache' and root.get('reclaimable') is not True:
                raise ValueError('source root is not enabled for explicit reclaim')
            self._verify_remote(actor, job)
            cleanup = job.get('cleanup_location')
            if cleanup and not self.files.exists(cleanup) and not self.files.exists(job['local']):
                self._save(job, status='verified', local=None, cleanup_location=None, error=None)
                return self._public(job)
            locks.enter_context(self.files.exclusive(cleanup if cleanup and self.files.exists(cleanup) else job['local']))
            if cleanup and self.files.exists(cleanup):
                if self.files.exists(job['local']) and job['local'] != cleanup:
                    raise ValueError('original path was recreated during cleanup')
            else:
                self.files.verify(job['local'], job['files'])
                relative = parts(job['local']['relative'], internal=True)
                cleanup = dict(job['local'],
                    relative='/'.join([*relative[:-1], '.reclaim-' + job_id]))
                self._save(job, status='reclaiming', cleanup_location=cleanup)
                self.files.quarantine(job['local'], job_id)
            self.files.delete(cleanup, job['files'])
            self._save(job, status='verified', local=None, cleanup_location=None, error=None)
            return self._public(job)

    def restore(self, actor, job_id):
        pending = self._load(job_id)
        self._check(actor, pending, 'read-repos')
        if self.policy['enabled'] and not self._public(pending)['local_present']:
            result = self.reclaim_cache(actor, required_bytes=pending['upload_bytes'])
            if result['status'] == 'blocked': raise ValueError('cache policy has insufficient space')
        with self._lease():
            job = self._load(job_id)
            self._check(actor, job, 'read-repos')
            if not job['bytes_verified'] or job['status'] != 'verified':
                raise ValueError('verified archive required for restoration')
            if job.get('local') and self.files.exists(job['local']):
                self.files.verify(job['local'], job['files'])
                return self._public(job)
            if self.policy['enabled'] and sum(row['upload_bytes'] for row in self._cached(actor)) + job['upload_bytes'] > self.policy['max_bytes']:
                raise ValueError('cache space changed during admission; retry after reclaim')
            def chunks(name):
                assigned, token = self._assignment(actor, job)
                if self.transport.info(assigned, token).get('private') is not True:
                    raise ValueError('private archive required for restoration')
                return self.transport.chunks(assigned, name, token)
            try:
                location = self.files.restore(job, chunks, lambda: self._check(actor, job, 'read-repos'))
            except OSError:
                raise ValueError('local restoration failed; partial data is not published') from None
            self._save(job, local=location, error=None)
            return self._public(job)

    def reclaim_cache(self, actor, *, required_bytes=0):
        size(required_bytes)
        if not self.policy['enabled']: return dict(status='disabled', reclaimed_bytes=0)
        self.accounts.require(actor, 'manage')
        cached = self._cached(actor)
        total = sum(job['upload_bytes'] for job in cached)
        reclaimed = 0
        def enough():
            return (total + required_bytes <= self.policy['max_bytes']
                    and self.files.available() >= required_bytes + self.inventory.reserve)
        for job in sorted(cached, key=lambda row: (row.get('last_used_at', row['created_at']), row['id'])):
            if enough(): break
            if job['pinned'] or not job['bytes_verified'] or job['status'] != 'verified': continue
            result = self.reclaim(actor, job['id'], job['id'])
            if result['local_present'] is False:
                total -= job['upload_bytes']; reclaimed += job['upload_bytes']
        return dict(status='ready' if enough() else 'blocked', reclaimed_bytes=reclaimed)

    def _cached(self, actor):
        with self.pool.connect() as db:
            records = [json.loads(row[0]) for row in db.execute(
                'SELECT document FROM storage_jobs WHERE project=?', (self.project_id,))]
        return [job for job in records if job['requester_id'] == actor['user_id'] and job.get('local')
                and job['local']['root_id'] == self.files.cache_id and self.files.exists(job['local'])]
