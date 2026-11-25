"""Persistent host-only OMX learning jobs; never dispatches or activates a policy."""
from contextlib import contextmanager
import json
import hashlib
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import threading
import time
import uuid

from experiment_dataset import load_dataset
from experiment_process import process_stamp
from experiment_io import identifier, read_json, write_json
from experiment_catalog import Catalog
from experiment_inbox import Inbox, check_action_space
from experiment_artifact import model_archive, version_root
from experiment_jobs import check_request, check_learning_task, launch
from experiment_profile import profile_revision
from experiment_scope import select_dataset
from experiment_reviews import Reviews
from experiment_profiles import Profiles
from experiment_owner_status import OwnerStatus
from experiment_studies import Studies
from experiment_hub import Hub
from experiment_collect_plans import CollectPlans
from canonical_pipeline import CanonicalService
import experiment_world


def _worker_log_tail(root, max_chars=240):
    log = root / 'worker.log'
    if log.is_symlink() or not log.is_file():
        return ''
    try:
        size = log.stat().st_size
        with log.open('rb') as stream:
            if size > 4096:
                stream.seek(size - 4096)
            raw = stream.read(4096)
    except OSError:
        return ''
    lines = [line.strip() for line in raw.decode('utf-8', errors='replace').splitlines() if line.strip()]
    if not lines:
        return ''
    tail = ''.join(ch if ord(ch) >= 32 else ' ' for ch in lines[-1]).strip()
    return tail[-max_chars:]


class Center:
    def __init__(self, config):
        if (not isinstance(config, dict) or not {'schema', 'root', 'python'} <= set(config)
                or set(config) - {'schema', 'root', 'python', 'owner_status', 'host_id', 'canonical', 'world_experiment'}
                or config['schema'] != 'rosy.omx.center-config/1'
                or set(config['python']) != {'act', 'hilserl'}):
            raise ValueError('unsupported learning center configuration')
        self.host_id = config.get('host_id')
        if self.host_id is not None and self.host_id not in ('model', 'ai'):
            raise ValueError('trusted learning host must be model or ai')
        self.world_preset = experiment_world.parse_preset(config.get('world_experiment'), self.host_id)
        self.tasks = None
        self.owner_status = OwnerStatus(config.get('owner_status'))
        self.root = Path(config['root'])
        if not self.root.is_absolute() or self.root.is_symlink():
            raise ValueError('absolute owned learning root required')
        self.python = config['python']
        if any(not Path(p).is_absolute() or not Path(p).is_file() for p in self.python.values()):
            raise ValueError('configured learner Python interpreter missing')
        self.root.mkdir(parents=True, exist_ok=True)
        self.root = self.root.resolve()
        for folder in ('uploads', 'datasets', 'runs'):
            (self.root / folder).mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.children = {}
        self.db = self.root / 'center.sqlite'
        self.catalog = Catalog(self.root, self.connect, self.lock)
        self.inbox = Inbox(self.root)
        self.reviews = Reviews(self.root, self.connect, self.lock)
        self.profiles = Profiles(self.connect, self.lock)
        self.hub = Hub(self)
        self.collect_plans = CollectPlans(self.root, self.lock)
        self.canonical = CanonicalService(
            self.root / 'canonical', config.get('canonical'),
            host_id=self.host_id, default_python=self.python.get('act'),
        )
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS datasets (id TEXT PRIMARY KEY, document TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL,'
                       ' document TEXT NOT NULL, request TEXT NOT NULL, process TEXT NOT NULL)')
            self.inbox.schema(db)
            self.reviews.schema(db)
            self.profiles.schema(db)
        self.methods = {}
        for method, python in self.python.items():
            try:
                check = subprocess.run([python, '-c',
                    'import importlib.metadata as m; import torch; import lerobot; '
                    'assert m.version("lerobot")=="0.4.4"; print(torch.cuda.is_available())'],
                    capture_output=True, timeout=30, check=False)
                available = check.returncode == 0 and os.name == 'posix'
                cuda = available and check.stdout.strip().endswith(b'True')
            except (OSError, subprocess.TimeoutExpired):
                available = cuda = False
            # SAC continuous learning stays CPU; a cuda run still needs the shared GPU lease at start.
            self.methods[method] = {'available': available, 'devices': ['cpu', 'cuda'] if cuda and method == 'act' else ['cpu'],
                'execution_mode': 'offline_replay',
                'reason': None if available else 'Pinned LeRobot 0.4.4 Linux learner environment unavailable'}
        self.studies = Studies(self)
        with self.connect() as db:
            if self.world_preset is not None or self._active_world_runs(db):
                self.canonical.world_admission = self._canonical_admission
                experiment_world.start_supervisor(self)

    def connect(self):
        return sqlite3.connect(self.db, timeout=10)

    def bind_workspace(self, project_id):
        if not isinstance(project_id, str) or not project_id.strip() or len(project_id) > 256:
            raise ValueError('review project identity required')
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS workspace_binding '
                       '(singleton INTEGER PRIMARY KEY CHECK(singleton=1), project_id TEXT NOT NULL)')
            prior = db.execute('SELECT project_id FROM workspace_binding WHERE singleton=1').fetchone()
            if prior and prior[0] != project_id:
                raise ValueError('learning center belongs to a different review project')
            db.execute('INSERT OR IGNORE INTO workspace_binding VALUES (1,?)', (project_id,))

    def upload(self, body):
        return self.catalog.upload(body)

    def publish(self, body):
        return self.catalog.publish(body)

    def _refresh(self, db):
        for rid, document, process in db.execute('SELECT id,document,process FROM runs').fetchall():
            row, receipt = json.loads(document), json.loads(process)
            if row['status'] not in ('launching', 'running', 'stopping'):
                continue
            if row.get('execution_mode') == experiment_world.MODE:
                self._refresh_world_experiment(db, row, receipt)
                continue
            root = self.root / 'runs' / rid
            self.inbox.materialize(db, row)
            if row['status'] == 'launching':
                launcher = receipt.get('launcher')
                if launcher and process_stamp(launcher['pid']) == launcher:
                    continue
                candidates = [process_stamp(int(p.name), root / 'request.json')
                              for p in Path('/proc').iterdir() if p.name.isdigit()]
                candidates = [p for p in candidates if p]
                if len(candidates) == 1:
                    receipt = candidates[0]
                    row['status'] = 'running'
                    db.execute('UPDATE runs SET process=? WHERE id=?', (json.dumps(receipt), rid))
            proof = process_stamp(receipt.get('pid', -1), root / 'request.json') if receipt else None
            child = self.children.get(rid)
            code = child.poll() if child else None
            progress = root / 'output/progress.json'
            if progress.exists():
                row['progress'] = read_json(progress)
            if row.get('execution_mode') == 'online_experience' and row.get('progress', {}).get('latest_version'):
                row['result'] = read_json(version_root(root / 'output', row) / 'result.json')
            if proof and proof == receipt:
                if row['status'] == 'stopping' and time.time() - row.get('cancel_at', time.time()) > 10:
                    os.killpg(receipt['pid'], signal.SIGKILL)
            else:
                result, error = root / 'output/result.json', root / 'output/error.json'
                if row['status'] == 'stopping':
                    row['status'] = 'cancelled'
                elif error.exists():
                    row.update(status='failed', error=read_json(error)['error'])
                elif row.get('execution_mode') == 'online_experience':
                    row.update(status='interrupted', error='Continuous learner exited; completed versions are preserved')
                elif result.exists() and code in (0, None):
                    study_mode = row.get('execution_mode') in ('lerobot_inspect', 'lerobot_train')
                    if study_mode:
                        try:
                            row.update(status='succeeded', result=read_json(result, max_bytes=32*1024**2))
                            self.studies.check_run(row, root, row['result'])
                        except (ValueError, OSError, KeyError, TypeError):
                            row.pop('result', None)
                            row.update(status='failed', error='Uploaded study evidence validation failed; inspect the owned worker log')
                    else:
                        row.update(status='succeeded', result=read_json(result))
                    if (row.get('execution_mode') == 'native_train'
                            and row['result'].get('learning_task') != row.get('learning_task')):
                        row.update(status='failed', error='Native worker task lineage differs from owned run')
                    if row.get('execution_mode') == 'native_export':
                        try:
                            row['result']['dataset_id'] = self.catalog.exported(db, row, root / 'output')
                        except (ValueError, OSError) as exc:
                            row.update(status='failed', error=str(exc))
                elif code not in (0, None):
                    tail = _worker_log_tail(root)
                    msg = f'Worker exited with code {code}: {tail}' if tail else f'Worker exited with code {code}'
                    row.update(status='failed', error=msg)
                else:
                    row.update(status='interrupted', error='Worker exited without a completed result')
                self.children.pop(rid, None)
            db.execute('UPDATE runs SET document=? WHERE id=?', (json.dumps(row), rid))

    def snapshot(self):
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._refresh(db)
            return {'datasets': [json.loads(r[0]) for r in db.execute('SELECT document FROM datasets ORDER BY rowid DESC')],
                    'runs': [self.inbox.decorate(db, json.loads(r[0]))
                             for r in db.execute("SELECT document FROM runs WHERE COALESCE("
                                                 "json_extract(document,'$.execution_mode'),'')<>? ORDER BY rowid DESC",
                                                 (experiment_world.MODE,))],
                    'methods': self.methods, 'physical_learning_verified': False,
                    'owner_status': self.owner_status.describe()}

    def read_owner_status(self, workcell_id):
        return self.owner_status.read(workcell_id)

    def start(self, body):
        return self._start(body, 'offline_replay')

    def world_experiment(self):
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self.refresh_world_experiments(db)
            runs = db.execute("SELECT document FROM runs WHERE json_extract(document,'$.execution_mode')=? "
                              'ORDER BY rowid DESC LIMIT 30', (experiment_world.MODE,))
            preset = (dict(id=experiment_world.PRESET_ID, label='MuJoCo 교사 데이터', kind='offline_act',
                           steps=self.world_preset['steps'])
                      if self.world_preset is not None and self.methods['act']['available'] else None)
            return dict(preset=preset, runs=[experiment_world.public(json.loads(row[0])) for row in runs])

    def start_world_experiment(self, body):
        if set(body) != {'preset_id', 'request_id'} or body['preset_id'] != experiment_world.PRESET_ID:
            raise ValueError('World preset and request identity required')
        request_id = identifier(body['request_id'])
        logical_request = json.dumps(dict(body, execution_mode=experiment_world.MODE), sort_keys=True)
        # Also allow an idempotent retry after a preset is disabled or rotated.
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self.refresh_world_experiments(db)
            prior = db.execute('SELECT document,request FROM runs WHERE request_id=?', (request_id,)).fetchone()
            if prior:
                if prior[1] != logical_request:
                    raise ValueError('request identity already used with different inputs')
                return experiment_world.public(json.loads(prior[0]))
        if self.world_preset is None:
            raise ValueError('World experiment preset unavailable')
        settings = {key: self.world_preset[key] for key in ('dataset_id', 'steps', 'batch_size', 'seed', 'arm_id')
                    if key in self.world_preset}
        run = self._start(dict(settings, method='act', device='cpu', request_id=request_id),
                          experiment_world.MODE, logical_request=logical_request)
        return experiment_world.public(run)

    def stop_world_experiment(self, body):
        if set(body) != {'id'}:
            raise ValueError('World run identity required')
        rid = identifier(body['id'])
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            found = db.execute('SELECT document,process FROM runs WHERE id=?', (rid,)).fetchone()
            if not found:
                raise ValueError('unknown World experiment')
            row, receipt = map(json.loads, found)
            if row.get('execution_mode') != experiment_world.MODE:
                raise ValueError('unknown World experiment')
            if row['status'] in experiment_world.ACTIVE:
                self._refresh_world_experiment(db, row, receipt)
            if row['status'] in experiment_world.ACTIVE and row['status'] != 'stopping':
                row['status'] = 'stopping'
                db.execute('UPDATE runs SET document=? WHERE id=?', (json.dumps(row), rid))
                db.commit()
                db.execute('BEGIN IMMEDIATE')
                document, process = db.execute('SELECT document,process FROM runs WHERE id=?', (rid,)).fetchone()
                row, receipt = json.loads(document), json.loads(process)
                if row['status'] == 'stopping':
                    self._refresh_world_experiment(db, row, receipt)
            return experiment_world.public(row)

    @staticmethod
    def _active_world_runs(db):
        return db.execute("SELECT document,process FROM runs WHERE json_extract(document,'$.execution_mode')=? "
                          "AND json_extract(document,'$.status') IN ('launching','running','stopping')",
                          (experiment_world.MODE,)).fetchall()

    def refresh_world_experiments(self, db):
        for document, process in self._active_world_runs(db):
            self._refresh_world_experiment(db, json.loads(document), json.loads(process))

    def _refresh_world_experiment(self, db, row, receipt):
        experiment_world.refresh(row, receipt, self.root / 'runs' / row['id'] / 'output')
        db.execute('UPDATE runs SET document=?,process=? WHERE id=?', (json.dumps(row), json.dumps(receipt), row['id']))

    @contextmanager
    def _canonical_admission(self):
        # Share the durable Center writer lock with Canonical admission. Acquire
        # Center before Canonical on both paths so each reservation sees the other.
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self.refresh_world_experiments(db)
            yield bool(self._active_world_runs(db))

    def start_cuda(self, body):
        from experiment_cuda_train import start_cuda
        return start_cuda(self, body)

    def run(self, rid):
        rid = identifier(rid)
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._refresh(db)
            found = db.execute('SELECT document FROM runs WHERE id=?', (rid,)).fetchone()
            if not found:
                raise ValueError('unknown learning run')
            row = json.loads(found[0])
            if row.get('execution_mode') == experiment_world.MODE:
                raise ValueError('unknown learning run')
            return self.inbox.decorate(db, row)

    def bundle_manifest(self, rid):
        from experiment_cuda_train import bundle_manifest
        rid = identifier(rid)
        return bundle_manifest(self.root / 'runs' / rid, rid, self.run(rid))

    def bundle_file(self, rid, relpath):
        from experiment_cuda_train import bundle_file
        rid = identifier(rid)
        return bundle_file(self.root / 'runs' / rid, self.run(rid), relpath)

    def start_online(self, body):
        if body.get('method') != 'hilserl':
            raise ValueError('continuous experience learning requires SAC')
        return self._start(body, 'online_experience')

    def _start(self, body, mode, *, logical_request=None):
        check_request(body, self.methods)
        legacy_request = json.dumps(body, sort_keys=True)
        request = logical_request or json.dumps(dict(body, execution_mode=mode), sort_keys=True)
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._refresh(db)
            old = db.execute('SELECT document,request FROM runs WHERE request_id=?', (body['request_id'],)).fetchone()
            if old:
                if old[1] != request and not (mode == 'offline_replay' and old[1] == legacy_request):
                    raise ValueError('request identity already used with different inputs')
                return json.loads(old[0])
            dataset = db.execute('SELECT document FROM datasets WHERE id=?', (body['dataset_id'],)).fetchone()
            if not dataset:
                raise ValueError('unknown dataset')
            if not self.methods[body['method']]['available']:
                raise ValueError('learner environment unavailable')
            if any(json.loads(r[0])['status'] in ('launching', 'running', 'stopping') for r in db.execute('SELECT document FROM runs')):
                raise ValueError('one owned learning job may run at a time')
            if mode == experiment_world.MODE:
                if self.canonical.has_active_runs():
                    raise ValueError('another Canonical Learning job is already running')
                experiment_world.check_resources(self.root, self.canonical.jobs_dir)
            dataset_root = self.root / 'datasets' / body['dataset_id']
            checked = load_dataset(dataset_root, method=body['method'])
            if checked.revision != json.loads(dataset[0])['revision']:
                raise ValueError('published dataset changed')
            if mode == experiment_world.MODE:
                experiment_world.check_dataset(self.world_preset, checked.source, checked.revision, dataset_root)
            selected = self.profiles.resolve(body['profile_id'], checked.profile) if 'profile_id' in body else None
            _, scope = select_dataset(checked, body.get('arm_id'), method=body['method'])
            if mode == 'online_experience':
                check_action_space(checked)
            binding = None
            if 'task_id' in body:
                if self.host_id is None or self.host_id != body['compute_host'] or self.tasks is None:
                    raise ValueError('registered task and matching trusted compute host required')
                binding = self.tasks.resolve(body['task_id'], body['dataset_id'], checked.revision,
                                             profile_revision(checked.profile), scope['arm_ids'], self.host_id)
                receipts = []
                for name in ('native-split-receipt.json', 'conversion-receipt.json'):
                    receipt = dataset_root / name
                    if receipt.exists() or receipt.is_symlink():
                        read_json(receipt)
                        receipts.append(dict(name=name, sha256=hashlib.sha256(receipt.read_bytes()).hexdigest()))
                binding = dict(binding, attachment_kind='historical_dataset_attachment', source_receipts=receipts)
                check_learning_task(binding, checked, scope)
            rid = str(uuid.uuid4())
            root = self.root / 'runs' / rid
            root.mkdir()
            if mode == 'online_experience':
                (root / 'inbox').mkdir()
            worker_request = {key: body[key] for key in ('method', 'steps', 'batch_size', 'device', 'seed', 'arm_id') if key in body}
            if binding is not None:
                worker_request['learning_task'] = binding
            worker_metadata = ({'expected_dataset_revision': checked.revision}
                               if mode == experiment_world.MODE else {})
            write_json(root / 'request.json', dict(worker_request, dataset_root=str(dataset_root), **worker_metadata))
            row = dict(id=rid, status='launching', created_at=time.time(), dataset_id=body['dataset_id'],
                       dataset_revision=checked.revision, source=checked.source, execution_mode=mode,
                       training_scope=scope, **worker_request)
            if selected:
                row['selected_profile'] = {'id': selected['id'], 'revision': selected['revision']}
            if mode == experiment_world.MODE:
                row['scene_sha256'] = self.world_preset['scene_sha256']
                return experiment_world.launch(self, db, body['request_id'], request, row)
            return launch(self, db, body['request_id'], request, row, process_stamp)

    def start_export(self, body, prepared):
        required = {'prepared_id', 'name', 'profile', 'request_id'}
        if not required <= body.keys() or set(body) - required - {'review_id', 'profile_id'}:
            raise ValueError('export request fields differ from schema')
        identifier(body['request_id'])
        if not prepared or prepared.get('id') != body['prepared_id'] or prepared.get('kind') != 'omx':
            raise ValueError('registered OMX prepared set required')
        if 'profile_id' in body:
            selected = self.profiles.resolve(body['profile_id'], body['profile'])
            body = dict(body, profile=selected['profile'])
        source = Path(prepared['path']).resolve()
        if source.is_relative_to(self.root) or self.root.is_relative_to(source):
            raise ValueError('registered source must be separate from the learning center')
        request = json.dumps(dict(body, registered_source=str(source), execution_mode='native_export'), sort_keys=True)
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._refresh(db)
            old = db.execute('SELECT document,request FROM runs WHERE request_id=?', (body['request_id'],)).fetchone()
            if old:
                if old[1] != request:
                    raise ValueError('request identity already used with different inputs')
                return json.loads(old[0])
            if any(json.loads(r[0])['status'] in ('launching', 'running', 'stopping') for r in db.execute('SELECT document FROM runs')):
                raise ValueError('one owned learning job may run at a time')
            if not self.methods['act']['available']:
                raise ValueError('learner environment unavailable')
            from experiment_export import prepare_export
            core = {k: v for k, v in body.items() if k not in ('review_id', 'profile_id')}
            if 'review_id' in body:
                review = self.reviews.for_export(body['review_id'], prepared)
                worker_request, fields = prepare_export(core, prepared, review=review)
            else:
                worker_request, fields = prepare_export(core, prepared)
            if 'profile_id' in body:
                fields.update(profile_id=selected['id'], profile_revision=selected['revision'])
            rid = str(uuid.uuid4())
            root = self.root / 'runs' / rid
            root.mkdir()
            write_json(root / 'request.json', worker_request)
            row = dict(id=rid, status='launching', created_at=time.time(), **fields)
            return launch(self, db, body['request_id'], request, row, process_stamp)

    def review(self, prepared):
        return self.reviews.describe(prepared)

    def start_native(self, body, prepared, segments=None):
        from experiment_native_train import start
        return start(self, body, prepared, segments)

    def save_review(self, body, prepared, actor=None):
        return self.reviews.save(body, prepared, actor)

    def review_frame(self, prepared, revision, episode, frame, camera):
        from experiment_preview import read_in_worker
        with self.lock:
            return read_in_worker(self.python['act'], prepared, revision, episode, frame, [camera])

    def review_frame_set(self, prepared, revision, episode, frame, cameras):
        from experiment_preview import read_in_worker
        with self.lock:
            return read_in_worker(self.python['act'], prepared, revision, episode, frame, cameras, grouped=True)

    def experience(self, body):
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._refresh(db)
            # Existing accepted identities keep Inbox's acknowledgement-loss retry behavior.
            if isinstance(body, dict) and set(body) == {'id', 'dataset_id', 'request_id'}:
                rid, did, request_id = (identifier(body[key]) for key in ('id', 'dataset_id', 'request_id'))
                prior = db.execute('SELECT 1 FROM inputs WHERE id=?', (request_id,)).fetchone()
                found = db.execute('SELECT document FROM runs WHERE id=?', (rid,)).fetchone()
                row = json.loads(found[0]) if found else {}
                if not prior and row.get('learning_task') is not None:
                    if row.get('execution_mode') != 'online_experience' or row.get('status') != 'running':
                        raise ValueError('active continuous learning run required')
                    binding = check_learning_task(row['learning_task'])
                    if self.tasks is None or self.host_id != binding['compute_host']:
                        raise ValueError('trusted task compute host changed')
                    registered = db.execute('SELECT document FROM datasets WHERE id=?', (did,)).fetchone()
                    if not registered:
                        raise ValueError('unknown registered task experience dataset')
                    checked = load_dataset(self.root / 'datasets' / did, method='hilserl')
                    if checked.revision != json.loads(registered[0])['revision']:
                        raise ValueError('registered task experience dataset changed')
                    _, scope = select_dataset(checked, row.get('arm_id'), method='hilserl')
                    if scope != row['training_scope']:
                        raise ValueError('task experience training scope differs')
                    resolved = self.tasks.resolve(binding['task_id'], did, checked.revision,
                        profile_revision(checked.profile), scope['arm_ids'], self.host_id)
                    check_learning_task(resolved, checked, scope)
                    for key in ('task_id', 'task_revision', 'project_id', 'profile_id', 'profile_revision',
                                'task_participants', 'compute_host', 'component_ids', 'participants', 'robots'):
                        if resolved[key] != binding[key]:
                            raise ValueError('experience task lineage differs from learning run')
            return self.inbox.add(db, body)

    def artifact(self, rid):
        rid = identifier(rid)
        with self.lock, self.connect() as db:
            self._refresh(db)
            found = db.execute('SELECT document FROM runs WHERE id=?', (rid,)).fetchone()
            row = json.loads(found[0]) if found else {}
            if row.get('execution_mode') == experiment_world.MODE:
                raise ValueError('World experiment checkpoints stay in the experiment workspace')
            if row.get('execution_mode') in ('native_export', 'lerobot_inspect'):
                raise ValueError('exported dataset is not a model learning artifact')
            online = row.get('execution_mode') == 'online_experience'
            if row.get('status') != 'succeeded' and not online:
                raise ValueError('completed learning run required')
            root = self.root / 'runs' / rid / 'output'
            if row.get('execution_mode') == 'lerobot_train':
                from experiment_lerobot_worker import archive
                request = self.studies.check_run(row, root.parent, row['result'])
                return archive(root, row['result'], request)
            if row.get('execution_mode') == 'native_train':
                from experiment_native_train import archive
                return archive(root, row['result'], learning_task=row.get('learning_task'))
            if online:
                root = version_root(root, row)
                row['result'] = read_json(root / 'result.json')
            return model_archive(root, row['result'], learning_task=row.get('learning_task'))

    def stop(self, body):
        if set(body) != {'id'}:
            raise ValueError('run identity required')
        rid = identifier(body['id'])
        with self.lock, self.connect() as db:
            self._refresh(db)
            found = db.execute('SELECT document,process FROM runs WHERE id=?', (rid,)).fetchone()
            if not found:
                raise ValueError('unknown learning run')
            row, receipt = map(json.loads, found)
            if row.get('execution_mode') == experiment_world.MODE:
                raise PermissionError('World experiment stop requires its dedicated route')
            if row['status'] in ('running', 'stopping'):
                if process_stamp(receipt['pid'], self.root / 'runs' / rid / 'request.json') != receipt:
                    raise ValueError('owned worker identity changed')
                os.killpg(receipt['pid'], signal.SIGTERM)
                row['status'] = 'stopping'
                row.setdefault('cancel_at', time.time())
                db.execute('UPDATE runs SET document=? WHERE id=?', (json.dumps(row), rid))
            return row
