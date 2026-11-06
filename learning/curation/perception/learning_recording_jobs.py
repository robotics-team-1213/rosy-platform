"""Owned passive export subprocesses and explicit local uploaded-study handoff."""
import base64
import hashlib
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import threading
import time
import zipfile

OMX = Path(__file__).resolve().parents[2]/'training/omx'
if str(OMX) not in sys.path:
    sys.path.insert(0, str(OMX))
from experiment_io import identifier, read_json, write_json, sync_directory
from experiment_process import process_stamp
from experiment_lerobot_worker import offline_environment as environment
import experiment_lerobot_source as source

SCRIPT = Path(__file__).resolve().parents[1]/'omx/passive_export.py'
ACTIVE = {'launching', 'running'}
MAX_BYTES = 2*1024**3


def file_hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    write_json(path, value)
    with path.open('rb') as stream:
        os.fsync(stream.fileno())
    sync_directory(path.parent)


class Jobs:
    def __init__(self, root, python, center=None):
        self.root, self.python, self.center = Path(root), python, center
        if not self.root.is_absolute() or self.root.is_symlink():
            raise ValueError('absolute owned recording export root required')
        self.root.mkdir(parents=True, exist_ok=True)
        self.root = self.root.resolve()
        self.lock, self.children = threading.RLock(), {}
        self.available = dict(available=False, reason='고정 LeRobot 0.4.4 자료 변환기가 연결되지 않았습니다.')
        if python and Path(python).is_absolute() and Path(python).is_file() and os.name == 'posix':
            try:
                result = subprocess.run([str(python), '-c',
                    'import importlib.metadata as m; assert m.version("lerobot")=="0.4.4"'],
                    capture_output=True, timeout=15, check=False, env=environment(self.root/'probe'))
                if result.returncode == 0:
                    self.available = dict(available=True, reason=None)
            except (OSError, subprocess.TimeoutExpired):
                pass

    def availability(self):
        return dict(self.available)

    def _exports(self, session, create=False):
        current = self.root
        for part in (identifier(session['id']), 'exports'):
            current = current/part
            if current.is_symlink() or (current.exists() and not current.is_dir()):
                raise ValueError('regular owned export directory required')
            if create:
                current.mkdir(exist_ok=True)
        return current

    def _current(self, session):
        root = self._exports(session)
        pointer = root/'current.json'
        if not pointer.exists():
            return None, None
        request_id = identifier(read_json(pointer)['request_id'])
        folder = root/request_id
        if folder.is_symlink() or not folder.is_dir():
            raise ValueError('owned export job missing')
        row = read_json(folder/'job.json', max_bytes=8*1024**2)
        if (row['session_id'] != session['id'] or row['request_id'] != request_id
                or row['profile_revision'] != session['profile_revision']):
            raise ValueError('export session binding changed')
        return folder, row

    @staticmethod
    def _public(session, row):
        return dict(status=row['status'], error=row.get('error'),
            artifact_url='/api/learning/recording/artifact/'+session['id']
                if row['status'] == 'succeeded' else None)

    def start(self, session, episode_roots, request_id):
        request_id = identifier(request_id)
        roots = [str(Path(path).resolve()) for path in episode_roots]
        if (not 2 <= len(roots) <= 1000 or len(set(roots)) != len(roots)
                or any(Path(path).is_symlink() or not Path(path).is_dir() for path in episode_roots)):
            raise ValueError('two or more distinct kept episode directories required')
        binding = dict(session_id=identifier(session['id']), profile_revision=session['profile_revision'],
            episodes=roots, request_id=request_id, policy_camera_keys=[camera['input_key']
                for camera in session['profile']['cameras'] if 'policy' in camera['purposes']])
        if not 1 <= len(binding['policy_camera_keys']) <= 8:
            raise ValueError('one to eight frozen policy camera inputs required')
        with self.lock:
            exports = self._exports(session, create=True)
            folder = exports/request_id
            if folder.is_symlink():
                raise ValueError('regular owned export job required')
            if folder.exists():
                old = read_json(folder/'job.json', max_bytes=8*1024**2)
                if any(old.get(key) != value for key, value in binding.items()):
                    raise ValueError('export request identity reused with changed inputs')
                current, _ = self._current(session)
                if current != folder:
                    raise ValueError('export request belongs to an older attempt')
                return self.refresh(session)
            if not self.available['available']:
                raise ValueError(self.available['reason'])
            if shutil.disk_usage(self.root).free < 2 * MAX_BYTES + 1024**3:
                raise ValueError('자료 변환과 ZIP 보관을 위한 여유 공간 5 GiB가 필요합니다.')
            _, previous = self._current(session)
            if previous and previous['status'] in ACTIVE:
                raise ValueError('owned export already running')
            folder.mkdir()
            row = dict(binding, status='launching', error=None, process=None)
            save(folder/'job.json', row)
            save(exports/'current.json', dict(request_id=request_id))
            command = [str(self.python), str(SCRIPT), '--out', str(folder/'dataset')]
            for path in roots:
                command.extend(['--episode', path])
            child = None
            try:
                with (folder/'export.log').open('xb') as log:
                    child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                        stderr=subprocess.STDOUT, env=environment(folder), start_new_session=True)
                self.children[request_id] = child
                stamp, deadline = None, time.monotonic() + 2
                while child.poll() is None:
                    stamp = process_stamp(child.pid, folder/'dataset')
                    if stamp or time.monotonic() >= deadline:
                        break
                    # Popen can return while /proc still contains the pre-exec command.
                    time.sleep(.01)
                if not stamp:
                    # A very short successful worker can exit before its /proc identity is observed.
                    if child.poll() is None:
                        raise ValueError('export process ownership could not be established')
                row.update(status='running', process=stamp)
                save(folder/'job.json', row)
            except Exception:
                if child is not None and child.poll() is None:
                    child.terminate()
                    child.wait(timeout=10)
                row.update(status='failed', error='자료 변환기를 시작하지 못했습니다.')
                save(folder/'job.json', row)
                raise
            return self._public(session, row)

    def _manifest(self, folder, row):
        dataset = folder/'dataset'
        if dataset.is_symlink() or not dataset.is_dir():
            raise ValueError('owned exported dataset missing')
        receipt = read_json(folder/'dataset.receipt.json', max_bytes=8*1024**2)
        if (receipt.get('schema') != 'rosy.passive-export-result/1'
                or receipt.get('reader_verified') is not True
                or receipt.get('physical_learning_verified') is not False
                or receipt.get('profile_revision') != row['profile_revision']
                or receipt.get('policy_camera_keys') != row['policy_camera_keys']
                or receipt.get('episodes') != len(row['episodes'])
                or type(receipt.get('frames')) is not int or not 1 <= receipt['frames'] <= 200000):
            raise ValueError('complete passive export evidence required')
        files, actual, total = [], {}, 0
        for path in dataset.rglob('*'):
            if path.is_symlink() or not path.resolve().is_relative_to(dataset.resolve()):
                raise ValueError('export links are forbidden')
            if path.is_dir():
                continue
            if not path.is_file() or len(actual) >= 10000:
                raise ValueError('bounded regular exported files required')
            name, size = path.relative_to(dataset).as_posix(), path.stat().st_size
            total += size
            if size > source.FILE_BYTES or total > MAX_BYTES:
                raise ValueError('export exceeds dataset byte limit')
            actual[name] = file_hash(path)
            if any(part.startswith('.') for part in path.relative_to(dataset).parts):
                continue
            source.allowed(name)
            files.append(dict(name=name, size=size, sha256=actual[name]))
        if actual != receipt.get('files'):
            raise ValueError('export bytes differ from verified receipt')
        info = read_json(dataset/'meta/info.json')
        keys = {key for key in info.get('features', {}) if key.startswith('observation.images.')}
        if info.get('codebase_version') != 'v3.0' or keys != set(row['policy_camera_keys']):
            raise ValueError('exported policy camera keys differ from frozen session')
        return source.validate_files(files)

    def refresh(self, session):
        with self.lock:
            folder, row = self._current(session)
            if row is None:
                return None
            if row['status'] not in ACTIVE:
                return self._public(session, row)
            child = self.children.get(row['request_id'])
            code = child.poll() if child is not None else None
            stamp = row.get('process')
            if stamp and process_stamp(stamp['pid'], folder/'dataset') == stamp and (child is None or code is None):
                return self._public(session, row)
            if not stamp and child is None:
                candidates = [process_stamp(int(path.name), folder/'dataset')
                              for path in Path('/proc').iterdir() if path.name.isdigit()]
                candidates = [value for value in candidates if value]
                if len(candidates) == 1:
                    row.update(status='running', process=candidates[0])
                    save(folder/'job.json', row)
                    return self._public(session, row)
            try:
                if code not in (0, None):
                    raise ValueError('export worker failed')
                files = self._manifest(folder, row)
                archive = folder/'dataset.zip'
                if not archive.exists():
                    temporary = folder/'dataset.zip.part'
                    with zipfile.ZipFile(temporary, 'x', compression=zipfile.ZIP_DEFLATED) as zipped:
                        for item in files:
                            if shutil.disk_usage(folder).free < item['size'] + 1024**3:
                                raise ValueError('자료 ZIP 저장 공간이 부족합니다.')
                            zipped.write(folder/'dataset'/item['name'], item['name'])
                    if temporary.stat().st_size > MAX_BYTES:
                        raise ValueError('export archive exceeds 2 GiB')
                    with temporary.open('rb') as stream:
                        os.fsync(stream.fileno())
                    temporary.rename(archive)
                if archive.is_symlink() or not archive.is_file() or archive.stat().st_size > MAX_BYTES:
                    raise ValueError('bounded owned export archive required')
                with zipfile.ZipFile(archive) as zipped:
                    if sorted(zipped.namelist()) != sorted(item['name'] for item in files):
                        raise ValueError('export archive file set differs')
                    for item in files:
                        if zipped.getinfo(item['name']).file_size != item['size']:
                            raise ValueError('export archive file size differs')
                        with zipped.open(item['name']) as stream:
                            if hashlib.file_digest(stream, 'sha256').hexdigest() != item['sha256']:
                                raise ValueError('export archive bytes differ')
                row.update(status='succeeded', files=files, manifest_revision=source.manifest_revision(files),
                           archive_sha256=file_hash(archive), archive_bytes=archive.stat().st_size)
            except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile):
                row.update(status='failed', error='자료 변환 또는 원본 증거 검증에 실패했습니다. 새 요청으로 다시 시도하세요.')
            self.children.pop(row['request_id'], None)
            save(folder/'job.json', row)
            return self._public(session, row)

    def artifact(self, session):
        with self.lock:
            self.refresh(session)
            folder, row = self._current(session)
            if row is None or row['status'] != 'succeeded':
                raise ValueError('completed owned recording export required')
            if (self._manifest(folder, row) != row['files']
                    or source.manifest_revision(row['files']) != row['manifest_revision']):
                raise ValueError('export source manifest changed')
            archive = folder/'dataset.zip'
            if (archive.is_symlink() or not archive.is_file() or archive.stat().st_size != row['archive_bytes']
                    or archive.stat().st_size > MAX_BYTES or file_hash(archive) != row['archive_sha256']):
                raise ValueError('completed recording archive bytes changed')
            return archive

    def publish(self, session, request_id, actor):
        identifier(request_id)
        if self.center is None or not hasattr(self.center, 'studies'):
            raise ValueError('같은 프로젝트의 로컬 Learning 실행기가 필요합니다.')
        with self.lock:
            self.artifact(session)
            folder, row = self._current(session)
            study = self.center.studies.create(dict(request_id=request_id, name=session['name'], files=row['files']), actor)
            uid = identifier(study['id'])
            for item in row['files']:
                with (folder/'dataset'/item['name']).open('rb') as stream:
                    offset = 0
                    while raw := stream.read(256*1024):
                        value = self.center.studies.upload(dict(study_id=uid, name=item['name'], offset=offset,
                            data=base64.b64encode(raw).decode('ascii')))
                        offset += len(raw)
                        if value.get('offset') != offset:
                            raise ValueError('local study upload acknowledgement differs')
            return dict(study_id=uid, url='/learning/imitate?study='+uid+'&panel=inspect')

    def close(self):
        with self.lock:
            for pointer in self.root.glob('*/exports/current.json'):
                try:
                    request_id = identifier(read_json(pointer)['request_id'])
                    folder = pointer.parent/request_id
                    row = read_json(folder/'job.json', max_bytes=8*1024**2)
                    stamp = row.get('process')
                    if (row['status'] in ACTIVE and stamp
                            and process_stamp(stamp['pid'], folder/'dataset') == stamp):
                        os.killpg(stamp['pid'], signal.SIGTERM)
                        deadline = time.monotonic()+3
                        while time.monotonic() < deadline and process_stamp(stamp['pid'], folder/'dataset') == stamp:
                            time.sleep(.05)
                        if process_stamp(stamp['pid'], folder/'dataset') == stamp:
                            os.killpg(stamp['pid'], signal.SIGKILL)
                        row.update(status='failed', error='자료 변환기가 종료됐습니다. 새 요청으로 다시 시도하세요.')
                        save(folder/'job.json', row)
                except (OSError, ValueError, KeyError, TypeError):
                    continue
            for child in self.children.values():
                try:
                    child.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    pass
            self.children.clear()
