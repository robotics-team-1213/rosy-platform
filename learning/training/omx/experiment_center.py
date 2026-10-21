"""Persistent host-only OMX learning jobs; never dispatches or activates a policy."""
import json
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
from experiment_jobs import check_request, launch
from experiment_scope import select_dataset
from experiment_reviews import Reviews
from experiment_profiles import Profiles
from experiment_owner_status import OwnerStatus


class Center:
    def __init__(self, config):
        if (not isinstance(config, dict) or not {'schema', 'root', 'python'} <= set(config)
                or set(config) - {'schema', 'root', 'python', 'owner_status'}
                or config['schema'] != 'rosy.omx.center-config/1'
                or set(config['python']) != {'act', 'hilserl'}):
            raise ValueError('unsupported learning center configuration')
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
                    'assert m.version("lerobot")=="0.4.4"; print(torch.__version__)'],
                    capture_output=True, timeout=30, check=False)
                available = check.returncode == 0 and os.name == 'posix'
            except (OSError, subprocess.TimeoutExpired):
                available = False
            self.methods[method] = {'available': available, 'devices': ['cpu'],
                'execution_mode': 'offline_replay',
                'reason': None if available else 'Pinned LeRobot 0.4.4 Linux learner environment unavailable'}

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
                    row.update(status='succeeded', result=read_json(result))
                    if row.get('execution_mode') == 'native_export':
                        try:
                            row['result']['dataset_id'] = self.catalog.exported(db, row, root / 'output')
                        except (ValueError, OSError) as exc:
                            row.update(status='failed', error=str(exc))
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
                             for r in db.execute('SELECT document FROM runs ORDER BY rowid DESC')],
                    'methods': self.methods, 'physical_learning_verified': False,
                    'owner_status': self.owner_status.describe()}

    def read_owner_status(self, workcell_id):
        return self.owner_status.read(workcell_id)

    def start(self, body):
        return self._start(body, 'offline_replay')

    def start_online(self, body):
        if body.get('method') != 'hilserl':
            raise ValueError('continuous experience learning requires SAC')
        return self._start(body, 'online_experience')

    def _start(self, body, mode):
        check_request(body, self.methods)
        legacy_request = json.dumps(body, sort_keys=True)
        request = json.dumps(dict(body, execution_mode=mode), sort_keys=True)
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
            dataset_root = self.root / 'datasets' / body['dataset_id']
            checked = load_dataset(dataset_root, method=body['method'])
            if checked.revision != json.loads(dataset[0])['revision']:
                raise ValueError('published dataset changed')
            selected = self.profiles.resolve(body['profile_id'], checked.profile) if 'profile_id' in body else None
            _, scope = select_dataset(checked, body.get('arm_id'), method=body['method'])
            if mode == 'online_experience':
                check_action_space(checked)
            rid = str(uuid.uuid4())
            root = self.root / 'runs' / rid
            root.mkdir()
            if mode == 'online_experience':
                (root / 'inbox').mkdir()
            worker_request = {key: body[key] for key in ('method', 'steps', 'batch_size', 'device', 'seed', 'arm_id') if key in body}
            write_json(root / 'request.json', dict(worker_request, dataset_root=str(dataset_root)))
            row = dict(id=rid, status='launching', created_at=time.time(), dataset_id=body['dataset_id'],
                       dataset_revision=checked.revision, source=checked.source, execution_mode=mode,
                       training_scope=scope, **worker_request)
            if selected:
                row['selected_profile'] = {'id': selected['id'], 'revision': selected['revision']}
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
            return self.inbox.add(db, body)

    def artifact(self, rid):
        rid = identifier(rid)
        with self.lock, self.connect() as db:
            self._refresh(db)
            found = db.execute('SELECT document FROM runs WHERE id=?', (rid,)).fetchone()
            row = json.loads(found[0]) if found else {}
            if row.get('execution_mode') == 'native_export':
                raise ValueError('exported dataset is not a model learning artifact')
            online = row.get('execution_mode') == 'online_experience'
            if row.get('status') != 'succeeded' and not online:
                raise ValueError('completed learning run required')
            root = self.root / 'runs' / rid / 'output'
            if online:
                root = version_root(root, row)
                row['result'] = read_json(root / 'result.json')
            return model_archive(root, row['result'])

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
            if row['status'] in ('running', 'stopping'):
                if process_stamp(receipt['pid'], self.root / 'runs' / rid / 'request.json') != receipt:
                    raise ValueError('owned worker identity changed')
                os.killpg(receipt['pid'], signal.SIGTERM)
                row['status'] = 'stopping'
                row.setdefault('cancel_at', time.time())
                db.execute('UPDATE runs SET document=? WHERE id=?', (json.dumps(row), rid))
            return row
