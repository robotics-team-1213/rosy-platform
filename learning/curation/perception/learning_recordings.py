"""Project-local observer recording lifecycle, separate from robot command owners."""
import json
import math
from pathlib import Path
import sqlite3
import sys
import threading
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'training' / 'omx'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'omx'))
from experiment_io import identifier
from experiment_profiles import Profiles
from experiment_profile import profile_revision
from learning_recording_sources import Sources, read


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def check_fields(body, fields):
    if not isinstance(body, dict) or set(body) != set(fields):
        raise ValueError('fixed recording request fields required')


def timing_policy(value):
    check_fields(value, ('fps', 'max_camera_age_s', 'max_arm_age_s', 'max_camera_skew_s',
                         'max_arm_skew_s', 'max_gap_s'))
    if type(value['fps']) is not int or not 1 <= value['fps'] <= 60:
        raise ValueError('recording rate must be an integer from 1 to 60 Hz')
    for key in set(value) - {'fps'}:
        number = value[key]
        if type(number) not in (int, float) or not math.isfinite(number) or not 0 < number <= 2:
            raise ValueError('bounded positive recording timing limits required')
    return json.loads(canonical(value))


class Recordings:
    def __init__(self, store, center=None, config=None):
        self.store, self.center = store, center
        self.lock = threading.RLock()
        self.active = None
        self.thread = None
        self.stop_event = threading.Event()
        self.recorders = {}
        self.capture_rows, self.failed_sessions = {}, {}
        self.closing = threading.Event()
        self.monitors = []
        from learning_recording_review import Reviews
        self.reviews = Reviews()
        config = config or {}
        if not isinstance(config, dict) or set(config) - {'schema', 'host_id', 'sources', 'source_root', 'export_python'}:
            raise ValueError('fixed local recording configuration required')
        if config and config.get('schema') != 'rosy.learning.recording-config/1':
            raise ValueError('recording configuration schema required')
        self.host_id = config.get('host_id')
        if self.host_id is not None and (not isinstance(self.host_id, str) or not 1 <= len(self.host_id) <= 128):
            raise ValueError('bounded recording host label required')
        self.root = store.state / 'recordings'
        if self.root.is_symlink():
            raise ValueError('owned recording directory required')
        self.root.mkdir(exist_ok=True)
        self.sources = Sources(config.get('sources', []), registry=config.get('source_root'))
        # UI-only test doubles need no profile schema; real Center registries are reused.
        profiles = getattr(center, 'profiles', None)
        self.profiles = profiles if isinstance(profiles, Profiles) else Profiles(store.connect, self.lock)
        with store.connect() as db:
            self.profiles.schema(db)
            db.execute('CREATE TABLE IF NOT EXISTS recording_sessions (id TEXT PRIMARY KEY, document TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS recording_requests '
                       '(id TEXT PRIMARY KEY, binding TEXT NOT NULL, reply TEXT NOT NULL)')
            for uid, text in db.execute('SELECT id,document FROM recording_sessions').fetchall():
                row = json.loads(text)
                if row['status'] in ('arming', 'recording'):
                    row.update(status='failed', error='녹화 프로세스가 재시작됐습니다. 종료되지 않은 시연은 보관할 수 없습니다.')
                    for episode in row['episodes']:
                        if episode['status'] == 'recording':
                            episode.update(status='invalid', integrity_verified=False, error=row['error'])
                    self._save(db, row)
        from learning_recording_jobs import Jobs
        self.jobs = Jobs(self.root, config.get('export_python'), center)
        boot = Path('/proc/sys/kernel/random/boot_id')
        self.clock_domain = 'host-monotonic:' + (boot.read_text().strip() if boot.is_file() else str(uuid.uuid4()))
        with store.connect() as db:
            pending = [json.loads(row[0]) for row in db.execute('SELECT document FROM recording_sessions')]
        for row in pending:
            if row['status'] == 'exporting':
                self._monitor(row['id'], row.get('export_request'))

    def _save(self, db, row):
        db.execute('INSERT INTO recording_sessions VALUES (?,?) ON CONFLICT(id) '
                   'DO UPDATE SET document=excluded.document', (row['id'], canonical(row)))

    def _load(self, db, uid):
        identifier(uid)
        if uid in self.failed_sessions:
            return json.loads(canonical(self.failed_sessions[uid]))
        found = db.execute('SELECT document FROM recording_sessions WHERE id=?', (uid,)).fetchone()
        if found is None:
            raise ValueError('이 작업 공간에 저장된 녹화가 없습니다.')
        row = json.loads(found[0])
        if row['id'] != uid or profile_revision(row['profile']) != row['profile_revision']:
            raise ValueError('frozen recording configuration changed')
        return row

    @staticmethod
    def _public(row):
        return {key: value for key, value in row.items()
                if key not in ('creation', 'profile', 'capture_config', 'export_request')}

    def _request(self, action, body, actor, operation):
        request_id = identifier(body.get('request_id'))
        who = actor.get('user_id') if isinstance(actor, dict) else None
        binding = canonical(dict(action=action, body=body, actor=who))
        with self.lock, self.store.connect() as db:
            if body.get('session_id') in self.failed_sessions:
                raise ValueError('저장 공간 오류로 종료된 세션입니다. 공간을 확보한 뒤 앱을 재시작하세요.')
            prior = db.execute('SELECT binding,reply FROM recording_requests WHERE id=?', (request_id,)).fetchone()
            if prior:
                if prior[0] != binding:
                    raise ValueError('녹화 요청 식별자가 다른 내용이나 사용자로 재사용됐습니다.')
                reply = json.loads(prior[1])
                return self.get(reply['id']) if action != 'publish' else reply
            reply = operation(db)
            db.execute('INSERT INTO recording_requests VALUES (?,?,?)', (request_id, binding, canonical(reply)))
            return reply

    def create(self, body, actor=None):
        check_fields(body, ('request_id', 'name', 'profile_id', 'profile_revision', 'timing'))
        name = body['name']
        if (not isinstance(name, str) or not 1 <= len(name.strip()) <= 128
                or any(ord(char) < 32 for char in name)):
            raise ValueError('bounded recording name required')
        saved = self.profiles.get(body['profile_id'])
        if saved['revision'] != body['profile_revision']:
            raise ValueError('선택한 구성의 저장된 버전이 다릅니다.')
        policy = timing_policy(body['timing'])
        def operation(db):
            if db.execute('SELECT count(*) FROM recording_sessions').fetchone()[0] >= 1000:
                raise ValueError('녹화 작업 공간의 세션 한도에 도달했습니다.')
            row = dict(id=identifier(body['request_id']), name=name.strip(), profile_id=saved['id'],
                profile_revision=saved['revision'], profile=saved['profile'], timing=policy,
                status='idle', episodes=[], export=None, study_id=None, error=None)
            self._save(db, row)
            return self._public(row)
        return self._request('create', body, actor, operation)

    def get(self, uid):
        with self.lock, self.store.connect() as db:
            return self._public(self._load(db, uid))

    def _review_episode(self, session_id, episode_id):
        identifier(session_id)
        identifier(episode_id)
        with self.lock, self.store.connect() as db:
            if self.active is not None:
                raise ValueError('녹화를 마친 뒤 저장 기록을 검수하세요.')
            row = self._load(db, session_id)
            episode = next((value for value in row['episodes'] if value['id'] == episode_id), None)
            if (episode is None or episode['status'] not in ('draft', 'kept')
                    or episode.get('integrity_verified') is not True):
                raise ValueError('무결성을 확인한 종료 시연만 검수할 수 있습니다.')
            root = self.root
            if root.is_symlink() or not root.is_dir():
                raise ValueError('owned existing recording directory required')
            for part in (session_id, 'episodes', episode_id):
                root = root / part
                if root.is_symlink() or not root.is_dir():
                    raise ValueError('owned existing recording directory required')
            return root, row['profile_revision']

    def review(self, session_id, episode_id, *, refresh=False):
        # Reserve the worker while holding the capture lock, without hashing any raw bytes here.
        with self.lock:
            root, revision = self._review_episode(session_id, episode_id)
            return self.reviews.prepare((session_id, episode_id), root, revision, refresh=refresh)

    def review_frame(self, session_id, episode_id, revision, index):
        self._review_episode(session_id, episode_id)
        return self.reviews.frame((session_id, episode_id), revision, index)

    def review_image(self, session_id, episode_id, revision, index, camera):
        self._review_episode(session_id, episode_id)
        return self.reviews.image((session_id, episode_id), revision, index, camera)

    def review_close(self, body, actor=None):
        check_fields(body, ('session_id', 'episode_id'))
        key = (identifier(body['session_id']), identifier(body['episode_id']))
        with self.lock, self.store.connect() as db:
            row = self._load(db, key[0])
            if not any(value['id'] == key[1] for value in row['episodes']):
                raise ValueError('검수할 저장 시연이 없습니다.')
        return self.reviews.close(key)

    def _monitor(self, uid, request_id):
        worker = threading.Thread(target=self._monitor_export, args=(uid, request_id), daemon=True)
        self.monitors.append(worker)
        worker.start()

    def _monitor_export(self, uid, request_id):
        while not self.closing.wait(.2):
            with self.lock, self.store.connect() as db:
                row = self._load(db, uid)
                if row['status'] != 'exporting' or row.get('export_request') != request_id:
                    return
            # Hashing and ZIP construction must never delay the recording Stop endpoint.
            try:
                exported = self.jobs.refresh(row)
                if exported is None:
                    raise ValueError('owned export job missing')
            except (ValueError, OSError, KeyError, TypeError):
                exported = dict(status='failed', artifact_url=None, error='변환 근거를 확인하지 못했습니다.')
            with self.lock:
                with self.store.connect() as db:
                    row = self._load(db, uid)
                if row.get('export_request') != request_id:
                    return
                row['export'] = exported
                if exported['status'] != 'running':
                    row['status'] = 'ready' if exported['status'] == 'succeeded' else 'failed'
                try:
                    with self.store.connect() as db:
                        self._save(db, row)
                except (OSError, sqlite3.Error):
                    message = '변환 상태를 저장하지 못했습니다. 공간을 확보한 뒤 앱을 재시작하세요. 종료 상태는 메모리에만 보존됩니다.'
                    row.update(status='failed', error=message,
                        export=dict(status='failed', artifact_url=None, error=message))
                    self.failed_sessions[uid] = json.loads(canonical(row))
                    return
                if exported['status'] != 'running':
                    return

    def snapshot(self):
        with self.lock, self.store.connect() as db:
            ids = [row[0] for row in db.execute('SELECT id FROM recording_sessions ORDER BY rowid DESC LIMIT 100')]
        sessions = [self.get(uid) for uid in ids]
        sources = self.sources.snapshot()
        return dict(configured=bool(self.sources.rows) or self.sources.registry is not None, host_id=self.host_id,
            profiles=self.profiles.list(), sources=sources, sessions=sessions,
            review_busy=self.reviews.busy.is_set(),
            active=self.get(self.active) if self.active else None,
            exporter=self.jobs.availability(), import_available=self.center is not None and hasattr(self.center, 'studies'))

    def start(self, body, actor=None):
        check_fields(body, ('session_id', 'request_id'))
        def operation(db):
            import passive_recording
            if self.reviews.busy.is_set():
                raise ValueError('저장 기록 검수 준비를 마치거나 닫은 뒤 녹화를 시작하세요.')
            row = self._load(db, body['session_id'])
            if self.active is not None or row['status'] not in ('idle', 'ready', 'failed') or row['export'] is not None:
                raise ValueError('진행 중인 작업을 마친 뒤 새 녹화를 시작하세요.')
            chosen, producers = self.sources.bind(row['profile'])
            config = passive_recording.preflight(row['profile'], producers, row['timing'],
                now=time.monotonic(), clock_domain=self.clock_domain)
            stable = {key: value for key, value in config.items() if key not in ('preflight_at', 'revision')}
            if row.get('capture_config') is not None and row['capture_config'] != stable:
                raise ValueError('장비·보정·생산자 버전이 변경됐습니다. 새 세션을 만드세요.')
            row['capture_config'] = stable
            if len(row['episodes']) >= 1000:
                raise ValueError('세션당 시연 한도에 도달했습니다.')
            episode_id = str(uuid.uuid4())
            episode_root = self._episode_root(row['id'], episode_id)
            recorder = passive_recording.Recorder(episode_root, config)
            self.recorders[episode_id] = recorder
            row['episodes'].append(dict(id=episode_id, status='recording', frames=0,
                integrity_verified=False, task_outcome='unknown', error=None))
            row.update(status='arming', error=None)
            self._save(db, row)
            self.capture_rows[row['id']] = json.loads(canonical(row))
            self.active = row['id']
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._capture,
                args=(row['id'], episode_id, recorder, chosen), daemon=True)
            self.thread.start()
            return self._public(row)
        return self._request('start', body, actor, operation)

    def _episode_root(self, session_id, episode_id):
        root = self.root
        for part in (identifier(session_id), 'episodes'):
            root = root / part
            if root.is_symlink():
                raise ValueError('owned recording directory required')
            root.mkdir(exist_ok=True)
        result = root / identifier(episode_id)
        if result.is_symlink():
            raise ValueError('owned episode directory required')
        return result

    def _capture(self, session_id, episode_id, recorder, chosen):
        try:
            cursors = {}
            self.sources.poll(chosen, cursors, recorder)
            recorder.start(time.monotonic())
            self._capture_status(session_id, episode_id, recorder, 'recording')
            last_status = time.monotonic()
            while not self.stop_event.wait(.01):
                self.sources.poll(chosen, cursors, recorder)
                recorder.advance(time.monotonic())
                if time.monotonic() - last_status >= .5:
                    self._capture_status(session_id, episode_id, recorder, 'recording')
                    last_status = time.monotonic()
            self.sources.poll(chosen, cursors, recorder)
            recorder.stop(time.monotonic())
            self._capture_status(session_id, episode_id, recorder, 'ready')
        except Exception as error:
            message = ('녹화 입력 또는 저장소를 읽거나 쓰지 못했습니다.' if isinstance(error, OSError) else str(error))
            try:
                recorder.invalidate(message)
            except (OSError, ValueError):
                message += ' 원본 종료 상태를 저장하지 못했습니다.'
            self._capture_status(session_id, episode_id, recorder, 'failed', message)
        finally:
            with self.lock:
                self.recorders.pop(episode_id, None)
                self.capture_rows.pop(session_id, None)
                if self.active == session_id:
                    self.active = None

    def _capture_status(self, uid, episode_id, recorder, status, error=None):
        with self.lock:
            if uid in self.failed_sessions:
                return
            row = self.capture_rows.get(uid)
            if row is None:
                with self.store.connect() as db:
                    row = self._load(db, uid)
            summary = recorder.summary()
            episode = next(value for value in row['episodes'] if value['id'] == episode_id)
            episode.update({key: summary[key] for key in ('status', 'frames', 'integrity_verified', 'task_outcome', 'error')})
            if error is not None:
                episode.update(status='invalid', integrity_verified=False, error=error[:1000])
            row.update(status=status, error=error[:1000] if error else None)
            self.capture_rows[uid] = row
            try:
                with self.store.connect() as db:
                    self._save(db, row)
            except (OSError, sqlite3.Error):
                message = '상태 저장에 실패해 녹화를 종료했습니다. 공간을 확보한 뒤 앱을 재시작하세요. 종료 상태는 메모리에만 보존됩니다.'
                episode.update(status='invalid', integrity_verified=False, error=message)
                row.update(status='failed', error=message)
                self.failed_sessions[uid] = json.loads(canonical(row))
                self.stop_event.set()

    def stop(self, body, actor=None):
        check_fields(body, ('session_id', 'request_id'))
        def operation(db):
            row = self._load(db, body['session_id'])
            if self.active != row['id'] or row['status'] not in ('arming', 'recording'):
                raise ValueError('진행 중인 녹화가 없습니다.')
            self.stop_event.set()
            return self._public(row)
        return self._request('stop', body, actor, operation)

    def _decision(self, action, body, actor):
        fields = ['session_id', 'episode_id', 'request_id'] + (['task_outcome'] if action == 'keep' else [])
        check_fields(body, fields)
        def operation(db):
            import passive_recording
            row = self._load(db, body['session_id'])
            if self.active is not None or row['export'] is not None:
                raise ValueError('녹화·변환이 끝난 시연만 검수할 수 있습니다.')
            episode = next((value for value in row['episodes'] if value['id'] == body['episode_id']), None)
            if episode is None or episode['status'] not in ('draft', 'invalid'):
                raise ValueError('검수할 시연을 선택하세요.')
            recorder = self.recorders.get(episode['id'])
            if recorder is None:
                if action == 'keep':
                    recorder = passive_recording.Recorder.resume(self._episode_root(row['id'], episode['id']))
                else:
                    episode.update(status='discarded', integrity_verified=False)
                    self._save(db, row)
                    return self._public(row)
            if action == 'keep':
                seal = recorder.keep(task_outcome=body['task_outcome'], actor=actor)
                passive_recording.verify(self._episode_root(row['id'], episode['id']))
                episode.update(status='kept', integrity_verified=True, task_outcome=seal['task_outcome'])
            else:
                recorder.discard()
                episode.update(status='discarded', integrity_verified=False)
            self._save(db, row)
            return self._public(row)
        return self._request(action, body, actor, operation)

    def keep(self, body, actor=None):
        reply = self._decision('keep', body, actor)
        self.reviews.close((body['session_id'], body['episode_id']))
        return reply

    def discard(self, body, actor=None):
        reply = self._decision('discard', body, actor)
        self.reviews.close((body['session_id'], body['episode_id']))
        return reply

    def export(self, body, actor=None):
        check_fields(body, ('session_id', 'request_id'))
        def operation(db):
            row = self._load(db, body['session_id'])
            kept = [value for value in row['episodes'] if value['status'] == 'kept']
            if self.active is not None or row['status'] not in ('ready', 'idle', 'failed') or len(kept) < 2:
                raise ValueError('동일한 구성에서 검수를 마친 시연이 두 개 이상 필요합니다.')
            roots = [self._episode_root(row['id'], value['id']) for value in kept]
            row['export'] = self.jobs.start(row, roots, body['request_id'])
            row['export_request'] = body['request_id']
            row['status'] = 'exporting'
            self._save(db, row)
            self._monitor(row['id'], body['request_id'])
            return self._public(row)
        return self._request('export', body, actor, operation)

    def artifact(self, uid):
        with self.lock, self.store.connect() as db:
            row = self._load(db, uid)
        return self.jobs.artifact(row)

    def preview(self, uid):
        row = self.sources.rows.get(uid)
        if row is None or row['kind'] != 'camera':
            raise ValueError('등록된 카메라가 없습니다.')
        return read(row['root'], 'preview.jpg', 16 * 1024**2)

    def publish(self, body, actor=None):
        check_fields(body, ('session_id', 'request_id'))
        def operation(db):
            row = self._load(db, body['session_id'])
            if self.active is not None:
                raise ValueError('녹화를 마친 뒤 학습 자료를 전달하세요.')
            reply = self.jobs.publish(row, body['request_id'], actor)
            row['study_id'] = reply['study_id']
            self._save(db, row)
            return reply
        return self._request('publish', body, actor, operation)

    def close(self):
        self.closing.set()
        self.stop_event.set()
        self.reviews.close()
        if self.thread is not None:
            self.thread.join(timeout=5)
        self.jobs.close()
