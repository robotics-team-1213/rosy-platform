"""Project-local setup, revision fencing and real private roundtrip admission."""
from contextlib import closing
import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid

from storage_inventory import StorageInventory, open_root, size


class StorageSetup:
    def __init__(self, db, accounts, storage=None, *, clock=time.time, transport=None):
        self.db, self.accounts, self.clock, self.transport = Path(db), accounts, clock, transport
        self.project_id = accounts.project_id
        self.base = copy.deepcopy(storage.config) if storage else dict(
            project_id=self.project_id, reserve_bytes=1024 ** 3, roots=[])
        if self.base['project_id'] != self.project_id: raise ValueError('storage project mismatch')
        self.data_root = self.db.parent / 'storage-data'
        roots = self.base['roots']
        for identifier, label, role in [('exports', '보관할 완료 자료', 'derived'), ('cache', '복원한 작업 사본', 'cache')]:
            if not any(row['id'] == identifier for row in roots):
                roots.append(dict(id=identifier, label=label, role=role,
                                  path=str(self.data_root / identifier), reclaimable=identifier == 'exports'))
        pool = self.base.setdefault('pool', {})
        pool.setdefault('managed_root_id', 'cache')
        pool.setdefault('enabled', False)
        pool.setdefault('targets', [])
        pool.setdefault('quotas', {})
        pool.setdefault('cache_policy', dict(enabled=False, max_bytes=10 * 1024 ** 3))
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS storage_settings
                (project TEXT PRIMARY KEY,revision INTEGER NOT NULL,document TEXT NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS storage_checks
                (project TEXT,requester TEXT,target TEXT,proof TEXT,job_id TEXT NOT NULL,
                 PRIMARY KEY(project,requester,target,proof))''')

    def connect(self):
        return closing(sqlite3.connect(self.db, timeout=30))

    def _manager(self, actor):
        self.accounts.require(actor, 'publish')
        return self.accounts.require(actor, 'manage')

    def configuration(self):
        with self.connect() as db:
            row = db.execute('SELECT revision,document FROM storage_settings WHERE project=?',
                             (self.project_id,)).fetchone()
        return (row[0], json.loads(row[1])) if row else (0, copy.deepcopy(self.base))

    def _current(self, revision):
        current, config = self.configuration()
        if type(revision) is not int or revision != current:
            raise ValueError('storage settings revision changed; reload before retrying')
        return config

    def _write(self, revision, config):
        with self.connect() as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT revision FROM storage_settings WHERE project=?', (self.project_id,)).fetchone()
            if (row[0] if row else 0) != revision: raise ValueError('storage settings revision changed')
            db.execute('INSERT OR REPLACE INTO storage_settings VALUES(?,?,?)',
                       (self.project_id, revision + 1, json.dumps(config, allow_nan=False)))

    def _directories(self, config):
        if any((parent / '.git').exists() for parent in (self.data_root, *self.data_root.parents)):
            raise ValueError('managed data must be outside a source checkout')
        fd = open_root(str(self.db.parent))
        try:
            try: os.mkdir('storage-data', 0o700, dir_fd=fd)
            except FileExistsError: pass
            parent = os.open('storage-data', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            try:
                for root in config['roots']:
                    path = Path(root['path'])
                    if path.parent == self.data_root:
                        try: os.mkdir(path.name, 0o700, dir_fd=parent)
                        except FileExistsError: pass
                    opened = open_root(root['path']); os.close(opened)
            finally: os.close(parent)
        finally: os.close(fd)

    def save(self, actor, body):
        self._manager(actor)
        if not isinstance(body, dict) or set(body) != {'revision', 'targets', 'quotas', 'reserve_bytes', 'cache_policy'}:
            raise ValueError('settings need revision, targets, quotas, reserve_bytes and cache_policy')
        config = self._current(body['revision'])
        visible = {row['connection_id'] for row in self.accounts.connections(actor)}
        hidden = {row['id']: row for row in config['pool']['targets'] if row['connection_id'] not in visible}
        targets = []
        if not isinstance(body['targets'], list) or not isinstance(body['quotas'], dict):
            raise ValueError('storage targets and quotas must be a list and object')
        for target in body['targets']:
            if isinstance(target, dict) and isinstance(target.get('id'), str) and target['id'] in hidden:
                if set(target) != {'id', 'enabled'} or target['enabled'] is not False:
                    raise PermissionError('unavailable target can only be disabled')
                hidden[target['id']] = dict(hidden[target['id']], enabled=False)
                continue
            if (not isinstance(target, dict) or set(target) != {'id', 'connection_id', 'repo_id', 'repo_type',
                    'quota_owner', 'priority', 'enabled'} or not isinstance(target['connection_id'], str)
                    or target['connection_id'] not in visible):
                raise ValueError('choose an available account connection and explicit repository target')
            targets.append(copy.deepcopy(target))
        targets.extend(hidden.values())
        quotas = {owner: copy.deepcopy(config['pool']['quotas'][owner]) for owner in
                  {row['quota_owner'] for row in hidden.values()}}
        for owner, quota in body['quotas'].items():
            if (not isinstance(quota, dict) or set(quota) != {'remaining_bytes', 'reserve_bytes',
                    'source', 'measured_at', 'expires_at'}): raise ValueError('invalid quota measurement')
            quotas[owner] = copy.deepcopy(quota)
        if set(quotas) != {row['quota_owner'] for row in targets}: raise ValueError('one quota per target namespace required')
        size(body['reserve_bytes'])
        policy = body['cache_policy']
        if not isinstance(policy, dict) or set(policy) != {'enabled', 'max_bytes'} or type(policy['enabled']) is not bool:
            raise ValueError('invalid cache policy')
        size(policy['max_bytes'])
        config.update(reserve_bytes=body['reserve_bytes'])
        config['pool'].update(targets=targets, quotas=quotas, cache_policy=copy.deepcopy(policy), enabled=False)
        StorageInventory(self.db, config, self.project_id, clock=self.clock)
        if targets:
            from storage_pool import StoragePool
            StoragePool(self.db, dict(config['pool'], project_id=self.project_id), self.accounts, clock=self.clock)
        self._directories(config)
        self._write(body['revision'], config)
        return self.snapshot(actor)

    def jobs(self, *, probe_target=None):
        from storage_pool import StoragePool
        from storage_jobs import StorageJobs
        revision, config = self.configuration()
        pool = dict(config['pool'], project_id=self.project_id, settings_revision=revision,
                    settings_probe=probe_target is not None)
        if probe_target is not None: pool['targets'] = [probe_target]
        return StorageJobs(StorageInventory(self.db, config, self.project_id, clock=self.clock),
            StoragePool(self.db, pool, self.accounts, clock=self.clock, allow_empty=True), self.accounts, transport=self.transport)

    def _proof(self, actor, target):
        from storage_pool import StoragePool
        _, config = self.configuration()
        pool = StoragePool(self.db, dict(config['pool'], project_id=self.project_id), self.accounts, clock=self.clock)
        credential = pool._credential(actor, target)
        data = [target[key] for key in ('id', 'connection_id', 'repo_id', 'repo_type', 'quota_owner')]
        data.append(credential['generation'])
        return hashlib.sha256(json.dumps(data).encode()).hexdigest()

    def _checked_job(self, actor, target, proof):
        with self.connect() as db:
            row = db.execute('SELECT job_id FROM storage_checks WHERE project=? AND requester=? AND target=? AND proof=?',
                (self.project_id, actor['user_id'], target['id'], proof)).fetchone()
        return row[0] if row else None

    def _targets(self, config):
        targets = [target for target in config['pool']['targets'] if target['enabled']]
        if not targets: raise ValueError('enable at least one storage target')
        now = self.clock()
        for target in targets:
            quota = config['pool']['quotas'][target['quota_owner']]
            if not quota['measured_at'] <= now < quota['expires_at']:
                raise ValueError('fresh quota measurement required')
        return targets

    def verify(self, actor, revision):
        self._manager(actor)
        config = self._current(revision)
        targets = self._targets(config)
        result = []
        for target in targets:
            self._manager(actor); self._current(revision)
            try:
                proof = self._proof(actor, target)
                service = self.jobs(probe_target=target)
                job_id = self._checked_job(actor, target, proof)
                if job_id is None:
                    from storage_source import seal
                    folder = 'connection-check-' + uuid.uuid4().hex
                    root = next(row for row in config['roots'] if row['id'] == 'exports')
                    path = Path(root['path']) / folder
                    parent = open_root(root['path'])
                    try: os.mkdir(folder, 0o700, dir_fd=parent)
                    finally: os.close(parent)
                    (path / 'connection-check.json').write_text(json.dumps(dict(purpose='storage-roundtrip', target=target['id'])))
                    profile = 'model' if target['repo_type'] == 'model' else 'dataset'
                    seal(path, profile, dict(purpose='connection_check', target_id=target['id']))
                    source_key = hashlib.sha256((actor['user_id'] + ':' + proof).encode()).hexdigest()
                    job = service.create(actor, dict(source_id='exports', artifact_id=folder, profile=profile), source_key=source_key)
                    job_id = job['id']
                    with self.connect() as db, db:
                        db.execute('INSERT OR IGNORE INTO storage_checks VALUES(?,?,?,?,?)',
                            (self.project_id, actor['user_id'], target['id'], proof, job_id))
                job = service.run(actor, job_id)
                if job['bytes_verified']:
                    service._verify_remote(actor, service._load(job_id))
                result.append(dict(job, target_id=target['id']))
            except (ValueError, OSError, PermissionError, ImportError):
                result.append(dict(target_id=target['id'], bytes_verified=False, error='verification_failed'))
        return dict(status='verified' if all(row['bytes_verified'] for row in result) else 'blocked', jobs=result)

    def activate(self, actor, revision):
        self._manager(actor)
        config = self._current(revision)
        for target in self._targets(config):
            proof = self._proof(actor, target)
            job_id = self._checked_job(actor, target, proof)
            if job_id is None: raise ValueError('private upload/readback verification required')
            service = self.jobs()
            job = service._load(job_id)
            if not job['bytes_verified']: raise ValueError('private upload/readback verification required')
            service._verify_remote(actor, job)
        config['pool']['enabled'] = True
        self._write(revision, config)
        return self.snapshot(actor)

    def snapshot(self, actor):
        actor = self.accounts.require(actor, 'view')
        revision, config = self.configuration()
        result = dict(revision=revision, enabled=config['pool']['enabled'],
                      can_manage=all(key in actor['capabilities'] for key in ('manage', 'publish')))
        if not result['can_manage']: return result
        connections = self.accounts.connections(actor)
        visible = {row['connection_id'] for row in connections}
        targets, owners = [], set()
        for target in config['pool']['targets']:
            if target['connection_id'] not in visible:
                targets.append(dict(id=target['id'], enabled=target['enabled'], status='unavailable'))
                continue
            row = dict(target, status='needs_verification')
            owners.add(target['quota_owner'])
            try:
                proof = self._proof(actor, target)
                job_id = self._checked_job(actor, target, proof)
                if job_id and self.jobs().get(actor, job_id)['bytes_verified']: row['status'] = 'verified'
            except (ValueError, OSError, PermissionError): row['status'] = 'unavailable'
            targets.append(row)
        result.update(targets=targets, quotas={key: config['pool']['quotas'][key] for key in owners},
            connections=connections, reserve_bytes=config['reserve_bytes'], cache_policy=config['pool']['cache_policy'],
            roots=[{key: row[key] for key in ('id', 'label', 'role')} for row in config['roots']])
        return result
