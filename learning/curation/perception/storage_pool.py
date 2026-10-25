"""Project HF destinations with namespace-wide, durable capacity reservations."""
from contextlib import closing, contextmanager, nullcontext
import copy
import json
from pathlib import Path
import re
import sqlite3
import time

from learning_repos import REPO_ID
from storage_inventory import size


IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}')
SHA = re.compile(r'[0-9a-f]{40}')


class StoragePool:
    def __init__(self, db, config, accounts, *, clock=time.time):
        if not isinstance(config, dict) or config.get('project_id') != accounts.project_id:
            raise ValueError('storage pool project mismatch')
        self.config, self.accounts = copy.deepcopy(config), accounts
        self.project_id, self.db, self.clock = accounts.project_id, Path(db), clock
        self._validate()
        if self.db.is_symlink():
            raise ValueError('storage pool DB must not be linked')
        with self.connect() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS storage_allocations
                (project TEXT,id TEXT,document TEXT NOT NULL,PRIMARY KEY(project,id))''')

    def _validate(self):
        targets, quotas = self.config.get('targets'), self.config.get('quotas')
        if (not isinstance(targets, list) or not 1 <= len(targets) <= 64
                or not isinstance(quotas, dict) or not 1 <= len(quotas) <= 64):
            raise ValueError('register 1..64 targets and quota owners')
        seen = set()
        for row in targets:
            if (not isinstance(row, dict) or not isinstance(row.get('id'), str)
                    or not IDENTIFIER.fullmatch(row['id']) or row['id'] in seen
                    or not isinstance(row.get('repo_id'), str) or not REPO_ID.fullmatch(row['repo_id'])
                    or row.get('repo_type') not in ('dataset', 'model')
                    or not isinstance(row.get('connection_id'), str) or not row['connection_id']
                    or type(row.get('priority', 0)) is not int or type(row.get('enabled', True)) is not bool):
                raise ValueError('invalid storage target')
            namespace = row['repo_id'].split('/')[0].casefold()
            if row.get('quota_owner') != namespace or namespace not in quotas:
                raise ValueError('quota owner must match repository namespace')
            seen.add(row['id'])
        for owner, quota in quotas.items():
            if (not isinstance(owner, str) or owner != owner.casefold() or not isinstance(quota, dict)
                    or not isinstance(quota.get('source'), str) or not 1 <= len(quota['source']) <= 160):
                raise ValueError('quota needs a bounded measurement source')
            for key in ('remaining_bytes', 'reserve_bytes', 'measured_at', 'expires_at'):
                size(quota.get(key))
            if quota['expires_at'] <= quota['measured_at']:
                raise ValueError('quota expiry must follow measurement')

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.db, timeout=30)) as conn, conn:
            conn.row_factory = sqlite3.Row
            yield conn

    def _load(self, conn, job_id):
        row = conn.execute('SELECT document FROM storage_allocations WHERE project=? AND id=?',
                           (self.project_id, job_id)).fetchone()
        if row is None:
            raise ValueError('storage allocation not found')
        return json.loads(row[0])

    def _write(self, conn, job):
        conn.execute('INSERT OR REPLACE INTO storage_allocations VALUES(?,?,?)',
                     (self.project_id, job['id'], json.dumps(job, allow_nan=False)))

    def _credential(self, actor, target, generation=None, scope='write-repos'):
        cred = self.accounts.management_credential(actor, target['connection_id'], scope=scope,
            resource=target['repo_type'] + ':' + target['repo_id'])
        if generation is not None and cred['generation'] != generation:
            raise PermissionError('storage connection generation changed')
        namespace = target['repo_id'].split('/')[0]
        if cred['sharing'] == 'personal' and namespace.casefold() != cred['username'].casefold():
            raise PermissionError('personal connection cannot allocate another namespace')
        return cred

    def _available(self, conn, owner):
        quota, now = self.config['quotas'][owner], self.clock()
        if not quota['measured_at'] <= now < quota['expires_at']:
            return None
        charged = 0
        for row in conn.execute('SELECT document FROM storage_allocations WHERE project=?', (self.project_id,)):
            job = json.loads(row[0])
            if job['quota_owner'] != owner or job['status'] == 'released':
                continue
            # A fresh external measurement already includes commits confirmed before it.
            if job.get('confirmed_at') is None or job['confirmed_at'] >= quota['measured_at']:
                charged += job['upload_bytes']
        return max(0, quota['remaining_bytes'] - quota['reserve_bytes'] - charged)

    def snapshot(self, actor):
        self.accounts.require(actor, 'view')
        rows = []
        with self.connect() as conn:
            for target in self.config['targets']:
                row = dict(target)
                row.pop('connection_id')
                row.update(status='disabled', available_bytes=None)
                if target.get('enabled', True):
                    try:
                        self._credential(actor, target)
                    except PermissionError:
                        row = dict(id=target['id'], status='unavailable', available_bytes=None)
                    else:
                        available = self._available(conn, target['quota_owner'])
                        row.update(available_bytes=available, status='unknown' if available is None else 'ready',
                                   quota=dict(self.config['quotas'][target['quota_owner']]))
                rows.append(row)
        return dict(project_id=self.project_id, targets=rows)

    def reserve(self, actor, job_id, upload_bytes, *, connection=None, repo_type=None):
        self.accounts.require(actor, 'publish')
        if not isinstance(job_id, str) or not IDENTIFIER.fullmatch(job_id):
            raise ValueError('invalid storage job ID')
        size(upload_bytes)
        if repo_type not in (None, 'dataset', 'model'): raise ValueError('invalid repository type')
        if upload_bytes == 0:
            raise ValueError('upload must contain bytes')
        with (self.connect() if connection is None else nullcontext(connection)) as conn:
            if not conn.in_transaction: conn.execute('BEGIN IMMEDIATE')
            existing = conn.execute('SELECT document FROM storage_allocations WHERE project=? AND id=?',
                                    (self.project_id, job_id)).fetchone()
            if existing:
                job = json.loads(existing[0])
                self._authorize(actor, job)
                if (job['upload_bytes'] != upload_bytes or job['status'] == 'released'
                        or repo_type is not None and job['repo_type'] != repo_type):
                    raise ValueError('job already has a different allocation')
                return job
            ordered = sorted(self.config['targets'], key=lambda row: (row.get('priority', 0), row['id']))
            for target in ordered:
                if repo_type is not None and target['repo_type'] != repo_type: continue
                if not target.get('enabled', True):
                    continue
                try:
                    cred = self._credential(actor, target)
                except PermissionError:
                    continue
                available = self._available(conn, target['quota_owner'])
                if available is None or available < upload_bytes:
                    continue
                job = dict(id=job_id, project_id=self.project_id, requester_id=actor['user_id'],
                    target_id=target['id'], connection_id=target['connection_id'], generation=cred['generation'],
                    repo_id=target['repo_id'], repo_type=target['repo_type'], quota_owner=target['quota_owner'],
                    upload_bytes=upload_bytes, status='reserved', allocated_at=self.clock(), confirmed_at=None)
                self._write(conn, job)
                return job
        raise ValueError('no authorized storage capacity; inspect target status and quota')

    def _authorize(self, actor, job, scope='write-repos'):
        self.accounts.require(actor, 'publish')
        if job['requester_id'] != actor['user_id'] or job['project_id'] != self.project_id:
            raise PermissionError('storage requester required')
        return self._credential(actor, job, job['generation'], scope)

    def assignment(self, actor, job_id):
        with self.connect() as conn:
            job = self._load(conn, job_id)
        self._authorize(actor, job)
        return job

    def credential(self, actor, job_id, *, scope='write-repos'):
        with self.connect() as conn:
            job = self._load(conn, job_id)
        return self._authorize(actor, job, scope)

    def _transition(self, actor, job_id, status, revision=None, *, connection=None):
        with (self.connect() if connection is None else nullcontext(connection)) as conn:
            if connection is None: conn.execute('BEGIN IMMEDIATE')
            job = self._load(conn, job_id)
            self._authorize(actor, job)
            if status == 'released' and job['status'] != 'reserved':
                raise ValueError('started upload cannot release its reservation')
            if status == 'uploading' and job['status'] != 'reserved':
                raise ValueError('upload already started; reconcile existing outcome')
            if status == 'uploaded':
                if not isinstance(revision, str) or not SHA.fullmatch(revision):
                    raise ValueError('immutable revision required')
                if job['status'] == 'uploaded' and job['revision'] == revision:
                    return job
                if job['status'] != 'uploading':
                    raise ValueError('upload was not started')
                job.update(revision=revision, confirmed_at=self.clock())
            job['status'] = status
            self._write(conn, job)
            return job

    def start(self, actor, job_id):
        return self._transition(actor, job_id, 'uploading')

    def mark_uploaded(self, actor, job_id, revision):
        return self._transition(actor, job_id, 'uploaded', revision)

    def release(self, actor, job_id, *, connection=None):
        return self._transition(actor, job_id, 'released', connection=connection)
