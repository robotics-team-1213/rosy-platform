"""Optional, account-bound storage routes using a bounded background worker."""
from concurrent.futures import ThreadPoolExecutor
import re
import threading

PREFIX = '/api/learning/storage/'


class StorageWeb:
    def __init__(self, storage, accounts, jobs, db, *, sim_runs=None):
        self.setup, self.prepare, self.inventory = None, None, storage
        self.settings_revision, self.enabled = 0, jobs is not None
        if accounts:
            from storage_setup import StorageSetup
            from storage_prepare import StoragePrepare
            self.setup = StorageSetup(db, accounts, storage)
            self.prepare = StoragePrepare(self.setup, sim_runs)
        config = storage.config.get('pool') if storage else None
        if config is not None and (not isinstance(config, dict) or type(config.get('enabled', True)) is not bool):
            raise ValueError('invalid optional storage pool configuration')
        if jobs is None and config is not None and config.get('enabled', True):
            if accounts is None: raise ValueError('storage pool requires collaboration accounts')
            from storage_jobs import StorageJobs
            from storage_pool import StoragePool
            pool = StoragePool(db, dict(config, project_id=storage.project_id), accounts)
            jobs = StorageJobs(storage, pool, accounts)
        if jobs is not None and (accounts is None or jobs.project_id != accounts.project_id
                or jobs.inventory is not storage or jobs.accounts is not accounts):
            raise ValueError('storage jobs must match the account and storage project')
        self.jobs, self.accounts = jobs, accounts
        self.enabled = jobs is not None
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='storage') if jobs or accounts else None
        self.lock, self.pending, self.errors, self.results = threading.RLock(), {}, {}, {}
        self.closing = False
        self._refresh()

    def _refresh(self):
        if self.setup is None: return
        revision, config = self.setup.configuration()
        with self.lock:
            if revision == self.settings_revision or self.pending: return
            from storage_inventory import StorageInventory
            self.inventory = StorageInventory(self.setup.db, config, self.setup.project_id)
            self.jobs = self.setup.jobs()
            self.enabled, self.settings_revision = config['pool']['enabled'], revision

    def _actor(self, handler, capability='view'):
        actor = handler.learning_principal
        self.accounts.require(actor, capability)
        return actor

    def get(self, handler, path):
        if self._get_setup(handler, path): return True
        if path not in (PREFIX + 'pool', PREFIX + 'jobs'): return False
        self._refresh()
        if not self.jobs:
            handler.send(dict(status='not_configured', targets=[], jobs=[]))
            return True
        actor = self._actor(handler)
        with self.lock:
            operations = {key: value[0] for key, value in self.pending.items()}
            errors, results = dict(self.errors), dict(self.results)
        if path.endswith('/jobs'):
            rows = self.jobs.list(actor)
            for job in rows:
                job.update(operation=operations.get(job['id']), operation_error=errors.get(job['id']))
            handler.send(dict(status='ready', jobs=rows))
        else:
            result = self.jobs.pool.snapshot(actor)
            result.update(status='ready', enabled=self.enabled, sources=[{key: root[key] for key in ('id', 'label', 'role')}
                for root in self.jobs.files.roots.values()],
                capabilities=dict(publish='publish' in actor['capabilities'],
                                  manage=all(key in actor['capabilities'] for key in ('publish', 'manage'))),
                cache_operation=operations.get('cache'), cache_error=errors.get('cache'),
                cache_result=results.get('cache'))
            handler.send(result)
        return True

    def _get_setup(self, handler, path):
        if path not in (PREFIX + 'settings', PREFIX + 'sources', PREFIX + 'sim-sources'): return False
        if self.setup is None:
            handler.send(dict(status='not_configured', can_manage=False, enabled=False, revision=0)); return True
        actor = self._actor(handler)
        self._refresh()
        if path.endswith('/settings'):
            result = self.setup.snapshot(actor)
            if result['can_manage']:
                key = 'setup:' + actor['user_id']
                with self.lock:
                    result.update(operation=self.pending.get(key, (None,))[0],
                                  error=self.errors.get(key), result=self.results.get(key),
                                  busy=bool(self.pending), sim_configured=self.prepare.sim_runs is not None)
            handler.send(result)
        elif path.endswith('/sim-sources'): handler.send(self.prepare.sim_sources(actor))
        else: handler.send(self.prepare.sources(actor))
        return True

    def _submit(self, key, action, call):
        with self.lock:
            if self.closing: raise ValueError('storage service is stopping')
            if key in self.pending:
                if self.pending[key][0] != action: raise ValueError('another storage operation is in progress')
                return
            if len(self.pending) >= 4: raise ValueError('storage queue is full; retry after a job finishes')
            self.errors.pop(key, None)
            self.results.pop(key, None)
            future = self.executor.submit(call)
            self.pending[key] = (action, future)
            def done(completed):
                with self.lock:
                    if completed.cancelled() or completed.exception() is not None:
                        self.errors[key] = 'storage_operation_failed'
                    elif key == 'cache' or key.startswith('setup:'):
                        self.results[key] = completed.result()
                    self.pending.pop(key, None)
            future.add_done_callback(done)

    def post(self, handler, path, body):
        try:
            if self._post_setup(handler, path, body): return True
        except OSError:
            raise ValueError('storage setup files are unavailable; existing data was retained') from None
        if not (path == PREFIX + 'jobs' or path == PREFIX + 'cache/reclaim'
                or path.startswith(PREFIX + 'jobs/')):
            return False
        self._refresh()
        if not self.jobs: raise ValueError('storage pool is not configured')
        actor = self._actor(handler, 'publish')
        try:
            if path == PREFIX + 'jobs':
                if not self.enabled: raise ValueError('new archive assignments are paused; activate storage settings')
                return self._created(handler, actor, body)
            if path == PREFIX + 'cache/reclaim':
                self.accounts.require(actor, 'manage')
                if body: raise ValueError('cache reclaim accepts an empty object')
                self._submit('cache', 'cache_reclaim', lambda: self.jobs.reclaim_cache(actor))
                handler.send(dict(accepted=True, operation='cache_reclaim'), 202)
                return True
            match = re.fullmatch(PREFIX + r'jobs/([0-9a-f]{32})/(run|restore|reclaim|pin|cancel|reconcile)', path)
            if not match: raise ValueError('invalid storage action')
            job_id, action = match.groups()
            job = self.jobs.get(actor, job_id)
            if action in ('reclaim', 'pin'): self.accounts.require(actor, 'manage')
            if action == 'pin':
                if set(body) != {'pinned'}: raise ValueError('pin accepts only a boolean')
                handler.send(self.jobs.pin(actor, job_id, body['pinned']))
                return True
            self.jobs.pool.credential(actor, job_id, scope='read-repos' if action in ('restore', 'reclaim', 'reconcile') else 'write-repos')
            if action == 'cancel':
                if body: raise ValueError('cancel accepts an empty object')
                with self.lock:
                    if job_id in self.pending: raise ValueError('storage operation is still in progress')
                    handler.send(self.jobs.cancel(actor, job_id))
                return True
            if action == 'reconcile':
                if (set(body) != {'revision'} or not isinstance(body['revision'], str)
                        or not re.fullmatch(r'[0-9a-f]{40}', body['revision']) or job['status'] != 'hold'):
                    raise ValueError('held upload and full existing commit required')
                call = lambda: self.jobs.reconcile(actor, job_id, body['revision'])
            elif action == 'reclaim':
                if set(body) != {'confirm'} or body['confirm'] != job_id:
                    raise ValueError('confirm the exact storage job ID')
                call = lambda: self.jobs.reclaim(actor, job_id, body['confirm'])
            else:
                if body: raise ValueError('storage action accepts an empty object')
                call = lambda: getattr(self.jobs, action)(actor, job_id)
            self._submit(job_id, action, call)
            handler.send(dict(accepted=True, id=job_id, operation=action), 202)
            return True
        except OSError:
            raise ValueError('storage files are unavailable; existing data was retained') from None

    def _created(self, handler, actor, body):
        handler.send(self.jobs.create(actor, body), 201)
        return True

    def _post_setup(self, handler, path, body):
        actions = {PREFIX + 'settings': 'save', PREFIX + 'settings/verify': 'verify',
                   PREFIX + 'settings/activate': 'activate', PREFIX + 'sources/prepare': 'prepare'}
        if path not in actions: return False
        if self.setup is None: raise ValueError('collaboration accounts required for storage setup')
        actor = self._actor(handler, 'publish'); self.accounts.require(actor, 'manage')
        action = actions[path]
        if action == 'prepare': self.prepare.validate(body)
        elif action != 'save':
            required = {'revision', 'confirm'} if action == 'verify' else {'revision'}
            if set(body) != required or action == 'verify' and body['confirm'] is not True:
                raise ValueError('confirm private test upload and the current settings revision')
            self.setup._current(body['revision'])
        with self.lock:
            if self.pending: raise ValueError('storage work is in progress; retry when it finishes')
            if action in ('save', 'activate'):
                result = self.setup.save(actor, body) if action == 'save' else self.setup.activate(actor, body['revision'])
                self._refresh()
                handler.send(result)
            else:
                call = (lambda: self.setup.verify(actor, body['revision'])) if action == 'verify' else (lambda: self.prepare.prepare(actor, body))
                self._submit('setup:' + actor['user_id'], action, call)
                handler.send(dict(accepted=True, operation=action), 202)
        return True

    def close(self):
        with self.lock: self.closing = True
        if self.executor: self.executor.shutdown(wait=True, cancel_futures=True)
