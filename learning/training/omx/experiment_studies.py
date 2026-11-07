"""Project-owned uploaded studies reuse the Center's job and artifact authority."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import uuid

from experiment_io import identifier, read_json, write_json, sync_directory
from experiment_jobs import launch
from experiment_process import process_stamp
import experiment_lerobot_source as source
import experiment_study_upload as upload

ACTIVE = {'launching', 'running', 'stopping'}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def sha(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


RECIPE = ('optimizer_lr', 'chunk_size')


def fields(body, names):
    if not isinstance(body, dict) or set(body) != set(names):
        raise ValueError('fixed uploaded study fields required')


def creator(actor):
    if actor is None:
        return {'kind': 'local_unverified', 'id': 'local'}
    value = actor.get('user_id') if isinstance(actor, dict) else None
    if not isinstance(value, str) or not 1 <= len(value) <= 256 or any(ord(c) < 32 for c in value):
        raise ValueError('authenticated study creator required')
    return {'kind': 'authenticated', 'id': value}


class Studies:
    def __init__(self, center):
        self.center = center
        with center.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS lerobot_studies (id TEXT PRIMARY KEY, document TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS lerobot_splits '
                       '(request_id TEXT PRIMARY KEY, study_id TEXT NOT NULL, body TEXT NOT NULL, document TEXT NOT NULL)')

    @contextmanager
    def _db(self):
        with self.center.lock, self.center.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self.center._refresh(db)
            yield db

    def _project(self, db):
        try:
            row = db.execute('SELECT project_id FROM workspace_binding WHERE singleton=1').fetchone()
        except sqlite3.OperationalError as exc:
            raise ValueError('study requires a bound workspace project') from exc
        if not row:
            raise ValueError('study requires a bound workspace project')
        return row[0]

    def _save(self, db, row):
        db.execute('INSERT INTO lerobot_studies VALUES (?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document',
                   (row['id'], canonical(row)))

    def _load(self, db, uid):
        identifier(uid)
        found = db.execute('SELECT document FROM lerobot_studies WHERE id=?', (uid,)).fetchone()
        if not found:
            raise ValueError('uploaded study not found in this project')
        row = json.loads(found[0])
        expected = dict(request_id=uid, name=row['name'], files=row['files'],
                        creator=row['created_by'], project_id=row['project_id'])
        if (row['id'] != uid or row['project_id'] != self._project(db)
                or source.manifest_revision(row['files']) != row['manifest_revision']
                or row['creation'] != expected or row['revision'] != sha(expected)):
            raise ValueError('uploaded study project or manifest changed')
        return row

    def _runs(self, db, uid):
        return [json.loads(row[0]) for row in db.execute(
            "SELECT document FROM runs WHERE json_extract(document,'$.study_id')=? ORDER BY rowid DESC", (uid,))]

    def _sync(self, db, row):
        inspections = [run for run in self._runs(db, row['id']) if run['execution_mode'] == 'lerobot_inspect']
        if inspections:
            run = inspections[0]
            if run['status'] == 'succeeded':
                result = run['result']
                row.update(status='ready', error=None, source_revision=result['source_revision'],
                           inspection=result['inspection'])
            elif run['status'] in ACTIVE:
                row.update(status='inspecting', error=None)
            else:
                row.update(status='failed', error=run.get('error') or '자료 검사가 중단됐습니다. 같은 자료로 다시 검사하세요.')
            self._save(db, row)
        return row

    def _public(self, db, row, *, detail=True):
        result = {key: row.get(key) for key in ('id', 'name', 'project_id', 'revision', 'created_at',
            'created_by', 'status', 'error', 'source_revision', 'inspection', 'split')}
        if detail:
            root = upload.source_root(self.center.root, row['id'])
            files = upload.status(root, row['files'])
            result['upload'] = dict(files=files, total_bytes=sum(f['size'] for f in files),
                uploaded_bytes=sum(f['offset'] for f in files), locked=row['locked'],
                manifest_revision=row['manifest_revision'])
            result['runs'] = self._runs(db, row['id'])
        return result

    def snapshot(self):
        with self._db() as db:
            self._project(db)
            rows = [json.loads(row[0]) for row in db.execute('SELECT document FROM lerobot_studies ORDER BY rowid DESC LIMIT 200')]
            runs = [json.loads(row[0]) for row in db.execute('SELECT document FROM runs ORDER BY rowid DESC')]
            active = next((run for run in runs if run['status'] in ACTIVE), None)
            return dict(configured=True, host_id=self.center.host_id, methods=self.center.methods,
                studies=[self._public(db, self._sync(db, row), detail=False) for row in rows],
                busy=active is not None, active_run=active)

    def get(self, uid):
        with self._db() as db:
            return self._public(db, self._sync(db, self._load(db, uid)))

    def create(self, body, actor=None):
        fields(body, ('request_id', 'name', 'files'))
        uid = identifier(body['request_id'])
        name = body['name']
        if (not isinstance(name, str) or not 1 <= len(name.strip()) <= 128
                or any(ord(c) < 32 for c in name)):
            raise ValueError('bounded study display name required')
        files = source.validate_files(body['files'])
        who = creator(actor)
        with self._db() as db:
            project = self._project(db)
            binding = dict(request_id=uid, name=name.strip(), files=files, creator=who, project_id=project)
            prior = db.execute('SELECT document FROM lerobot_studies WHERE id=?', (uid,)).fetchone()
            if prior:
                row = self._load(db, uid)
                if row['creation'] != binding:
                    raise ValueError('study request identity reused with different content or actor')
                return self._public(db, self._sync(db, row))
            if shutil.disk_usage(self.center.root).free < sum(f['size'] for f in files)+upload.MARGIN:
                raise ValueError('insufficient study upload free space')
            root = upload.source_root(self.center.root, uid, create=True)
            proof = root.parent/'creation.json'
            if proof.exists():
                saved = read_json(proof, max_bytes=4*1024**2)
                if saved['creation'] != binding:
                    raise ValueError('study creation evidence differs')
                created = saved['created_at']
            else:
                created = datetime.now(timezone.utc).isoformat()
                write_json(proof, dict(creation=binding, created_at=created))
                with proof.open('rb') as stream:
                    import os
                    os.fsync(stream.fileno())
                sync_directory(root.parent)
                sync_directory(root.parent.parent)
            for item in files:
                if item['size'] == 0:
                    file = upload.path(root, item['name'], create=True)
                    if not file.exists():
                        file.touch(exist_ok=False)
            row = dict(id=uid, name=name.strip(), project_id=project, revision=sha(binding),
                created_at=created, created_by=who, creation=binding, files=files,
                manifest_revision=source.manifest_revision(files), locked=False, status='uploading',
                error=None, source_revision=None, inspection=None, split=None)
            self._save(db, row)
            return self._public(db, row)

    def upload(self, body):
        fields(body, ('study_id', 'name', 'offset', 'data'))
        with self._db() as db:
            row = self._load(db, body['study_id'])
            if row['locked']:
                raise ValueError('sealed study upload is immutable and locked')
            item = next((item for item in row['files'] if item['name'] == body['name']), None)
            if item is None:
                raise ValueError('file not in immutable upload manifest')
            root = upload.source_root(self.center.root, row['id'])
            offset = upload.write(root, item, body['offset'], body['data'])
            return dict(study_id=row['id'], name=item['name'], offset=offset)

    def _prior_run(self, db, request_id, binding):
        found = db.execute('SELECT document,request FROM runs WHERE request_id=?', (request_id,)).fetchone()
        if found:
            if found[1] != binding:
                raise ValueError('run request identity reused with different inputs')
            return json.loads(found[0])

    def _available(self, db):
        if self.center.host_id not in ('model', 'ai'):
            raise ValueError('configured trusted learning host required')
        if not self.center.methods['act']['available']:
            raise ValueError('pinned ACT learner environment unavailable')
        if any(json.loads(r[0])['status'] in ACTIVE for r in db.execute('SELECT document FROM runs')):
            raise ValueError('one owned learning job may run at a time')

    def _launch(self, db, row, body, request, mode):
        rid = str(uuid.uuid4())
        root = self.center.root/'runs'/rid
        root.mkdir()
        write_json(root/'request.json', request)
        run = dict(id=rid, status='launching', created_at=datetime.now(timezone.utc).timestamp(),
            method='act', device='cpu', execution_mode=mode, study_id=row['id'],
            project_id=row['project_id'], study_revision=row['revision'],
            compute_host=self.center.host_id,
            manifest_revision=row['manifest_revision'],
            request_sha256=hashlib.sha256((root/'request.json').read_bytes()).hexdigest(),
            physical_learning_verified=False)
        run.update({key: request[key] for key in ('source_revision', 'steps', 'batch_size', 'seed', *RECIPE) if key in request})
        if 'split' in request:
            run['split_revision'] = request['split']['revision']
        return launch(self.center, db, body['request_id'], canonical(body), run, process_stamp)

    def inspect(self, body):
        fields(body, ('study_id', 'request_id'))
        identifier(body['request_id'])
        with self._db() as db:
            row = self._sync(db, self._load(db, body['study_id']))
            prior = self._prior_run(db, body['request_id'], canonical(body))
            if prior:
                return prior
            self._available(db)
            root = upload.source_root(self.center.root, row['id'])
            if any(item['offset'] != item['size'] for item in upload.status(root, row['files'])):
                raise ValueError('complete manifest files required before inspection')
            row.update(locked=True, status='inspecting', error=None)
            self._save(db, row)
            request = dict(schema='rosy.lerobot-inspect-request/1', study_id=row['id'],
                compute_host=self.center.host_id,
                project_id=row['project_id'], source_root=str(root), files=row['files'],
                manifest_revision=row['manifest_revision'])
            return self._launch(db, row, body, request, 'lerobot_inspect')

    def split(self, body):
        fields(body, ('study_id', 'source_revision', 'train', 'validation', 'eval', 'request_id'))
        identifier(body['request_id'])
        binding = canonical(body)
        with self._db() as db:
            row = self._sync(db, self._load(db, body['study_id']))
            prior = db.execute('SELECT body,document FROM lerobot_splits WHERE request_id=?', (body['request_id'],)).fetchone()
            if prior:
                if prior[0] != binding:
                    raise ValueError('split request identity reused with different content')
                return self._public(db, row)
            if row['status'] != 'ready' or body['source_revision'] != row['source_revision']:
                raise ValueError('current verified source revision required')
            if any(run['status'] in ACTIVE for run in self._runs(db, row['id'])):
                raise ValueError('cannot change split during an owned study job')
            checked = source.validate_split({key: body[key] for key in ('train', 'validation', 'eval')}, row['inspection'])
            db.execute('INSERT INTO lerobot_splits VALUES (?,?,?,?)',
                       (body['request_id'], row['id'], binding, canonical(checked)))
            row['split'] = checked
            self._save(db, row)
            return self._public(db, row)

    def start(self, body):
        # A page opened before these values existed still sends the old body after an update.
        recipe = [key for key in RECIPE if isinstance(body, dict) and key in body]
        fields(body, ('study_id', 'split_revision', 'steps', 'batch_size', 'seed', 'request_id', *recipe))
        identifier(body['request_id'])
        for key, low, high in [('steps',1,100000),('batch_size',1,8),('seed',0,2147483647)]:
            if type(body[key]) is not int or not low <= body[key] <= high:
                raise ValueError('study training integer outside allowed range: '+key)
        source.check_recipe(body)
        with self._db() as db:
            row = self._sync(db, self._load(db, body['study_id']))
            prior = self._prior_run(db, body['request_id'], canonical(body))
            if prior:
                return prior
            self._available(db)
            if (row['status'] != 'ready' or not row['split']
                    or row['split']['revision'] != body['split_revision']):
                raise ValueError('current confirmed study split required')
            selected = set(row['split']['train']+row['split']['validation']+row['split']['eval'])
            frames = sum(e['frames'] for e in row['inspection']['episodes'] if e['index'] in selected)
            needed = frames*len(row['inspection']['cameras'])*(3*128*128+8192)*4+512*1024**2
            if shutil.disk_usage(self.center.root).free < needed+upload.MARGIN:
                raise ValueError('insufficient free space for selected study derivatives')
            root = upload.source_root(self.center.root, row['id'])
            request = dict(schema='rosy.lerobot-train-request/1', study_id=row['id'],
                compute_host=self.center.host_id,
                project_id=row['project_id'], source_root=str(root), files=row['files'],
                manifest_revision=row['manifest_revision'], source_revision=row['source_revision'],
                inspection=row['inspection'], split=row['split'],
                **{key: body[key] for key in ('steps', 'batch_size', 'seed', *recipe)})
            return self._launch(db, row, body, request, 'lerobot_train')

    def check_run(self, row, root, result):
        file = root/'request.json'
        if file.is_symlink() or hashlib.sha256(file.read_bytes()).hexdigest() != row.get('request_sha256'):
            raise ValueError('owned study worker request bytes changed')
        request = read_json(file, max_bytes=32*1024**2)
        if request['source_root'] != str(upload.source_root(self.center.root, row['study_id'])):
            raise ValueError('owned study source location differs')
        for key in ('study_id', 'project_id', 'compute_host', 'manifest_revision', 'source_revision', 'steps', 'batch_size', 'seed', *RECIPE):
            if key in row and request.get(key) != row[key]:
                raise ValueError('owned study worker binding differs')
        if row.get('split_revision') and request['split']['revision'] != row['split_revision']:
            raise ValueError('owned study split differs')
        from experiment_lerobot_worker import check_result
        check_result(root/'output', result, request)
        return request
