"""Linux run records: immutable inputs, fenced state, bounded verified artifacts."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid

from model_checks import ASSETS, check_vendor_manifest
from run_catalog import normalize

RUN_BYTES = 256 * 1024 * 1024
JSON_BYTES = 1024 * 1024
TERMINAL = {'SUCCEEDED', 'FAILED', 'STOPPED'}
TRANSITIONS = {
    'PENDING': {'RUNNING', 'STOP_REQUESTED', 'FAILED', 'UNKNOWN'},
    'RUNNING': {'STOP_REQUESTED', 'SUCCEEDED', 'FAILED', 'UNKNOWN'},
    'STOP_REQUESTED': {'STOPPED', 'FAILED', 'UNKNOWN'},
    'UNKNOWN': {'RUNNING', 'STOP_REQUESTED', 'SUCCEEDED', 'FAILED', 'STOPPED'},
}
MUTABLE = {'status', 'phase', 'error', 'runtime', 'cleanup'}
MEDIA = {'application/json', 'application/octet-stream', 'text/plain',
         'video/mp4', 'image/jpeg', 'image/png'}


class RunConflict(ValueError):
    """Reload the existing run; never silently create a replacement."""


def _id(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{32}', value):
        raise ValueError('invalid run/request ID')
    return value


def _bytes(value):
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                     separators=(',', ':')).encode('utf-8')
    if len(raw) > JSON_BYTES:
        raise ValueError('JSON record exceeds limit')
    return raw


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError('non-finite JSON value')


def _parts(value):
    if (not isinstance(value, str) or not value or len(value) > 180
            or not re.fullmatch('[A-Za-z0-9._/-]+', value)):
        raise ValueError('invalid artifact name')
    parts = value.split('/')
    reserved = {'con', 'prn', 'aux', 'nul', *('com'+str(i) for i in range(1, 10)),
                *('lpt'+str(i) for i in range(1, 10))}
    if any(p in {'', '.', '..'} or p.endswith('.') or p.split('.')[0].lower() in reserved
           for p in parts):
        raise ValueError('unsafe relative artifact name')
    return parts


@contextmanager
def _directory(root, relative='', *, create=False):
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        parts = list(root.parts[1:]) + (_parts(relative) if relative else [])
        for part in parts:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                    os.fsync(fd)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def _recover_publication(fd, name, info):
    # A killed publisher can leave its one temporary hard link beside the final name.
    if info.st_nlink != 2 or info.st_uid != os.getuid():
        raise ValueError('unrelated hard links are not run records')
    entries = os.listdir(fd)
    if len(entries) > 1024:
        raise ValueError('run directory exceeds recovery limit')
    matches = []
    for candidate in entries:
        if re.fullmatch(r'\.pending-[0-9a-f]{32}', candidate):
            other = os.stat(candidate, dir_fd=fd, follow_symlinks=False)
            if (other.st_dev, other.st_ino) == (info.st_dev, info.st_ino):
                matches.append(candidate)
    current = os.stat(name, dir_fd=fd, follow_symlinks=False)
    if len(matches) != 1 or (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
        raise ValueError('publication is not a recoverable store temporary link')
    os.unlink(matches[0], dir_fd=fd)
    os.fsync(fd)


def _read(fd, name, limit=JSON_BYTES, *, recover=False, durable=False):
    handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    with os.fdopen(handle, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if recover and stat.S_ISREG(before.st_mode) and before.st_nlink != 1:
            _recover_publication(fd, name, before)
            before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > limit:
            raise ValueError('artifact is not a bounded private regular file')
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        if (len(raw) > limit or (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise ValueError('artifact changed during read')
        if durable:
            os.fsync(stream.fileno())
            os.fsync(fd)
        return raw


def _json(fd, name):
    return json.loads(_read(fd, name, recover=True), object_pairs_hook=_pairs,
                      parse_constant=_invalid_constant)


def _write(fd, name, value, *, exclusive=False):
    raw = _bytes(value)
    if exclusive:
        try:
            existing = _read(fd, name, recover=True)
        except FileNotFoundError:
            pass
        else:
            if existing != raw:
                raise RunConflict('immutable record already exists with different content')
            return
    temporary = '.pending-' + uuid.uuid4().hex
    handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=fd)
    try:
        with os.fdopen(handle, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if exclusive:
            os.link(temporary, name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
            os.unlink(temporary, dir_fd=fd)
        else:
            os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=fd)
        except FileNotFoundError:
            pass


def requested(config: dict) -> dict:
    """The request's settings back from a normalized config: the seed, and the case of an arm S case run."""
    return {'seed': config['seed'], **({'case': config['case']} if 'case' in config else {})}


def input_snapshot(scenario_id: str, config: dict, source_sha: str) -> dict:
    if not isinstance(source_sha, str) or not re.fullmatch('[0-9a-f]{40}', source_sha):
        raise ValueError('source must be a full commit SHA')
    normalized = normalize(scenario_id, config)
    check_vendor_manifest()
    value = {'schema': 'rosy.isaac-run-input/1', 'catalog_version': 1,
             'scenario_id': scenario_id, 'config': normalized, 'source_sha': source_sha,
             'assets_sha256': hashlib.sha256((ASSETS / 'manifest.json').read_bytes()).hexdigest(),
             'verifier_sha256': hashlib.sha256(Path(__file__).with_name('import_omx.py').read_bytes()).hexdigest(),
             'scene': None, 'scene_not_applicable_reason': 'model_import_has_no_cargo_scene'}
    if scenario_id.startswith('arm-s-cell-'):
        from arm_s_cell_fixture import FIXTURE as ARM_S_CELL
        scene = json.loads(json.dumps(ARM_S_CELL))
        value.update(scene=scene, scene_sha256=hashlib.sha256(_bytes(scene)).hexdigest(), scene_not_applicable_reason=None,
            verifier_sha256=hashlib.sha256(Path(__file__).with_name('arm_s_cell_report.py').read_bytes()).hexdigest())
    if scenario_id == 'pinky-conveyor-roundtrip':
        from conveyor_fixture import FIXTURE, fixture_sha256
        value.update(scene=FIXTURE, scene_sha256=fixture_sha256(), scene_not_applicable_reason=None,
            verifier_sha256=hashlib.sha256(Path(__file__).with_name('conveyor_report.py').read_bytes()).hexdigest())
    return {'input': value, 'input_sha256': hashlib.sha256(_bytes(value)).hexdigest()}


class RunStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        if not self.root.is_absolute() or '..' in self.root.parts:
            raise ValueError('run root must be an absolute non-link path')
        try:
            with _directory(self.root, create=True) as fd:
                info = os.fstat(fd)
                if info.st_uid != os.getuid() or info.st_mode & 0o022:
                    raise ValueError('run root must be owned and not writable by other users')
            for name in ('requests', 'runs'):
                with _directory(self.root, name, create=True):
                    pass
        except OSError as exc:
            raise ValueError('run root cannot contain links or inaccessible directories') from exc

    @contextmanager
    def _locked(self):
        with _directory(self.root) as fd:
            handle = os.open('store.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                             0o600, dir_fd=fd)
            with os.fdopen(handle, 'a+b') as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                yield

    def _get(self, run_id):
        with _directory(self.root, 'runs/' + _id(run_id)) as fd:
            record = _json(fd, 'input.json')
            row = _json(fd, 'state.json')
            required = {'run_id', 'request_id', 'parent_run_id', 'input_sha256',
                        'status', 'revision', 'created_at', 'updated_at'}
            if (not isinstance(record, dict) or set(record) != {'input', 'input_sha256'}
                    or not isinstance(row, dict) or not required <= row.keys()
                    or not isinstance(row['status'], str)):
                raise ValueError('run record has an invalid shape')
            _id(row['request_id'])
            if row['parent_run_id'] is not None:
                _id(row['parent_run_id'])
            digest = hashlib.sha256(_bytes(record['input'])).hexdigest()
            if (row['run_id'] != run_id or row['input_sha256'] != digest
                    or record['input_sha256'] != digest or row['status'] not in TRANSITIONS.keys() | TERMINAL
                    or type(row['revision']) is not int or row['revision'] < 0):
                raise ValueError('invalid run state or changed input')
            row['input'] = record['input']
            row['snapshot'] = 'FINAL' if row['status'] in TERMINAL else 'OBSERVATION_NOT_ATOMIC'
            if row['status'] in TERMINAL:
                completion = row.pop('_completion', None)
                if not isinstance(completion, dict) or set(completion) != {'result', 'artifacts'}:
                    raise ValueError('terminal checkpoint is incomplete')
                if (hashlib.sha256(_bytes(completion['result'])).hexdigest() != row.get('result_sha256')
                        or hashlib.sha256(_bytes(completion['artifacts'])).hexdigest() != row.get('artifacts_sha256')):
                    raise ValueError('terminal checkpoint evidence changed')
                # State is the atomic commit; exported files can be recovered without replaying the job.
                _write(fd, 'artifacts.json', completion['artifacts'], exclusive=True)
                _write(fd, 'result.json', completion['result'], exclusive=True)
                row['result'] = _json(fd, 'result.json')
                row['artifacts'] = _json(fd, 'artifacts.json')
                if (hashlib.sha256(_bytes(row['result'])).hexdigest() != row.get('result_sha256')
                        or hashlib.sha256(_bytes(row['artifacts'])).hexdigest() != row.get('artifacts_sha256')):
                    raise ValueError('terminal evidence changed')
                if not isinstance(row['result'], dict) or row['result'].get('status') != row['status']:
                    raise ValueError('terminal result and run state disagree')
            return row

    def get(self, run_id: str) -> dict:
        with self._locked():
            return self._get(run_id)

    def list(self) -> list[dict]:
        with self._locked(), _directory(self.root, 'runs') as fd:
            rows = []
            for name in sorted(os.listdir(fd)):
                _id(name)
                try:
                    rows.append(self._get(name))
                except (ValueError, OSError, KeyError, TypeError):
                    rows.append({'run_id': name, 'status': 'UNKNOWN',
                                 'error': 'run record could not be verified'})
            return rows

    def create(self, request_id: str, scenario_id: str, config: dict, source_sha: str,
               *, parent_run_id: str | None = None) -> dict:
        _id(request_id)
        snapshot = input_snapshot(scenario_id, config, source_sha)
        run_id = uuid.uuid5(uuid.NAMESPACE_URL, 'rosy.isaac-run:' + request_id).hex
        with self._locked():
            if parent_run_id is not None:
                self._get(_id(parent_run_id))
            with _directory(self.root, 'runs/' + run_id, create=True) as fd:
                _write(fd, 'input.json', snapshot, exclusive=True)
                try:
                    row = _json(fd, 'state.json')
                except FileNotFoundError:
                    now = datetime.now(timezone.utc).isoformat()
                    row = {'run_id': run_id, 'request_id': request_id,
                           'parent_run_id': parent_run_id, 'input_sha256': snapshot['input_sha256'],
                           'status': 'PENDING', 'revision': 0, 'created_at': now, 'updated_at': now}
                    _write(fd, 'state.json', row, exclusive=True)
                if row['request_id'] != request_id or row['parent_run_id'] != parent_run_id:
                    raise RunConflict('request metadata differs from the reserved run')
            with _directory(self.root, 'requests') as fd:
                _write(fd, request_id + '.json', {'run_id': run_id,
                       'input_sha256': snapshot['input_sha256']}, exclusive=True)
            return self._get(run_id)

    def _event(self, fd, row):
        event = _bytes({key: row[key] for key in ('run_id', 'revision', 'status', 'updated_at')}) + b'\n'
        handle = os.open('events.jsonl', os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW,
                         0o600, dir_fd=fd)
        with os.fdopen(handle, 'ab') as stream:
            if os.fstat(stream.fileno()).st_size + len(event) > 16 * 1024 * 1024:
                raise ValueError('event log exceeds limit')
            stream.write(event)
            stream.flush()
            os.fsync(stream.fileno())

    def _change(self, row, expected_revision, changes):
        if row['revision'] != expected_revision or row['status'] in TERMINAL:
            raise RunConflict('stale or terminal run; reload the existing record')
        if not isinstance(changes, dict) or not changes or set(changes) - MUTABLE:
            raise ValueError('only execution state may be updated')
        target = changes.get('status', row['status'])
        if target != row['status'] and target not in TRANSITIONS.get(row['status'], set()):
            raise ValueError('invalid run transition')
        value = {k: v for k, v in row.items() if k not in {'input', 'snapshot', 'result', 'artifacts'}}
        value.update(changes, revision=row['revision'] + 1,
                     updated_at=datetime.now(timezone.utc).isoformat())
        _bytes(value)
        return value

    def update(self, run_id: str, expected_revision: int, changes: dict) -> dict:
        if not isinstance(changes, dict) or not changes:
            raise ValueError('state changes must be a nonempty JSON object')
        with self._locked():
            row = self._get(run_id)
            if changes.get('status') in TERMINAL:
                raise ValueError('terminal transitions require immutable result evidence')
            value = self._change(row, expected_revision, changes)
            with _directory(self.root, 'runs/' + run_id) as fd:
                self._event(fd, value)
                _write(fd, 'state.json', value)
            return self._get(run_id)

    def _manifest(self, run_id, items, *, durable=False):
        if not isinstance(items, list) or len(items) > 256:
            raise ValueError('too many artifacts')
        ids, names, total = set(), set(), 0
        for item in items:
            if (not isinstance(item, dict) or set(item) != {'id', 'name', 'bytes', 'sha256', 'media_type'}
                    or not isinstance(item['id'], str) or not re.fullmatch('[a-z0-9][a-z0-9_-]{0,63}', item['id'])
                    or item['id'] in ids or not isinstance(item['sha256'], str)
                    or not re.fullmatch('[0-9a-f]{64}', item['sha256'])
                    or type(item['bytes']) is not int or item['bytes'] < 0
                    or item['media_type'] not in MEDIA):
                raise ValueError('invalid artifact manifest')
            parts = _parts(item['name'])
            if item['name'].casefold() in names:
                raise ValueError('duplicate portable artifact name')
            ids.add(item['id'])
            names.add(item['name'].casefold())
            suffix = Path(parts[-1]).suffix.lower()
            limit = {'.json': JSON_BYTES, '.log': 16 * 1024 * 1024,
                     '.mp4': 128 * 1024 * 1024}.get(suffix, RUN_BYTES)
            total += item['bytes']
            if item['bytes'] > limit or total > RUN_BYTES:
                raise ValueError('artifact size exceeds limit')
            with _directory(self.root, 'runs/' + run_id + ('/' + '/'.join(parts[:-1]) if len(parts) > 1 else '')) as fd:
                raw = _read(fd, parts[-1], limit, durable=durable)
            if len(raw) != item['bytes'] or hashlib.sha256(raw).hexdigest() != item['sha256']:
                raise ValueError('artifact differs from its manifest')
        return {'snapshot': 'FINAL', 'files': items}

    def finish(self, run_id: str, expected_revision: int, result: dict, artifacts: list[dict]) -> dict:
        with self._locked():
            row = self._get(run_id)
            if not isinstance(result, dict) or result.get('status') not in TERMINAL:
                raise ValueError('a terminal result is required')
            value = self._change(row, expected_revision, {'status': result['status']})
            if result['status'] == 'SUCCEEDED':
                if row['input']['scenario_id'] == 'pinky-conveyor-roundtrip':
                    required = {'contact-report', 'pinky_initial', 'out_lift', 'conveyor_settle', 'back_lift', 'pinky_settle'}
                    if (result.get('stage') != 'contact_roundtrip' or result.get('import_verified') is not True
                            or type(result.get('completed_frames')) is not int or not 0 < result['completed_frames'] <= 4800
                            or result.get('task_success') is not True or result.get('evidence_class') != 'PHYSICS_GRASP'
                            or result.get('cleanup') != 'OWNED_PROCESSES_EXITED_GPU_RELEASED'
                            or result.get('coordinate_scope') != 'SYNTHETIC_NOT_CAMERA_REGISTERED'
                            or not required <= {item.get('id') for item in artifacts}):
                        raise ValueError('SDK exit alone is not verified contact roundtrip')
                elif row['input']['scenario_id'].startswith('arm-s-cell-'):
                    if (result.get('stage') != 'arm_s_cell' or result.get('import_verified') is not True
                            or result.get('task_success') is not True
                            or result.get('cleanup') != 'OWNED_PROCESSES_EXITED_GPU_RELEASED'
                            or 'arm-s-cell-report' not in {item.get('id') for item in artifacts}):
                        raise ValueError('SDK exit alone is not a verified arm S cell scenario')
                elif (result.get('stage') != 'model_import' or result.get('import_verified') is not True
                      or result.get('completed_frames') != 120 or result.get('task_success') is not None):
                    raise ValueError('SDK exit alone is not verified model import')
            manifest = self._manifest(run_id, artifacts, durable=True)
            value['result_sha256'] = hashlib.sha256(_bytes(result)).hexdigest()
            value['artifacts_sha256'] = hashlib.sha256(_bytes(manifest)).hexdigest()
            value['_completion'] = {'result': result, 'artifacts': manifest}
            with _directory(self.root, 'runs/' + run_id) as fd:
                self._event(fd, value)
                _write(fd, 'state.json', value)
                _write(fd, 'artifacts.json', manifest, exclusive=True)
                _write(fd, 'result.json', result, exclusive=True)
            return self._get(run_id)

    def artifact(self, run_id: str, artifact_id: str) -> dict:
        with self._locked():
            row = self._get(run_id)
            if row['status'] not in TERMINAL:
                raise ValueError('artifact is not finalized')
            manifest = row['artifacts']
            self._manifest(run_id, manifest['files'])
            item = next((item for item in manifest['files'] if item['id'] == artifact_id), None)
            if item is None:
                raise ValueError('artifact was not registered')
            parts = _parts(item['name'])
            with _directory(self.root, 'runs/' + run_id + ('/' + '/'.join(parts[:-1]) if len(parts) > 1 else '')) as fd:
                data = _read(fd, parts[-1], item['bytes'])
            if len(data) != item['bytes'] or hashlib.sha256(data).hexdigest() != item['sha256']:
                raise ValueError('artifact changed before delivery')
            return dict(item, data=data)
