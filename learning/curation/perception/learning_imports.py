"""D-755 permission-bound, immutable HF imports. Downloaded code is never executed.

Create one service per application. Workers receive a current authenticated principal;
only requester IDs, never sessions or provider tokens, enter persistent jobs.
"""
from __future__ import annotations

import hashlib
import errno
from contextlib import contextmanager, nullcontext
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


MAX_FILE = 2 * 1024 ** 3
MAX_TOTAL = 8 * 1024 ** 3
MAX_FILES = 256


class RangeRestart(ValueError):
    """The provider ignored Range; never append its full response."""


class ImportFailure(ValueError):
    """Public, credential-free failure code."""


def _filename(value):
    if (not isinstance(value, str) or not value or len(value) > 512
            or any(c in value for c in '\\:%?#\x00') or value.startswith('/')
            or any(ord(c) < 32 for c in value)):
        raise ValueError('invalid file name')
    for part in value.split('/'):
        if (part in ('', '.', '..') or part.endswith((' ', '.'))
                or re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?', part)):
            raise ValueError('invalid file name')
    return value


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HFTransport:
    """Fixed provider endpoints; CDN redirects never receive the HF bearer."""
    HOSTS = frozenset(('huggingface.co', 'cdn-lfs.huggingface.co', 'cdn-lfs.hf.co',
                       'cdn-lfs-us-1.hf.co', 'cdn-lfs-eu-1.hf.co', 'cas-bridge.xethub.hf.co'))

    @classmethod
    def check_url(cls, url):
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme != 'https' or parsed.hostname not in cls.HOSTS
                or parsed.username or parsed.password or parsed.port not in (None, 443)):
            raise ValueError('unapproved provider endpoint')
        return parsed

    def _open(self, url, token, *, offset=0):
        if not isinstance(token, str) or not token or any(not 33 <= ord(c) <= 126 for c in token):
            raise ValueError('invalid provider credential')
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        for _ in range(6):
            parsed = self.check_url(url)
            headers = {'Accept-Encoding': 'identity', 'User-Agent': 'ROSY-learning-import/1'}
            if offset:
                headers['Range'] = f'bytes={offset}-'
            if parsed.hostname == 'huggingface.co':
                headers['Authorization'] = 'Bearer ' + token
            try:
                return opener.open(urllib.request.Request(url, headers=headers), timeout=30)
            except urllib.error.HTTPError as exc:
                if exc.code not in (301, 302, 303, 307, 308):
                    exc.close()
                    raise ValueError('provider request rejected') from None
                location = exc.headers.get('Location', '')
                exc.close()
                url = urllib.parse.urljoin(url, location)
        raise ValueError('provider redirect limit')

    def resolve(self, kind, repo, revision, token):
        url = ('https://huggingface.co/api/' + ('datasets/' if kind == 'dataset' else 'models/')
               + repo + '/revision/' + urllib.parse.quote(revision, safe='') + '?blobs=true')
        with self._open(url, token) as response:
            data = response.read(8 * 1024 ** 2 + 1)
        if len(data) > 8 * 1024 ** 2:
            raise ValueError('provider metadata too large')
        return json.loads(data)

    def chunks(self, kind, repo, revision, filename, token, *, offset=0, total=None):
        url = ('https://huggingface.co/' + ('datasets/' if kind == 'dataset' else '')
               + repo + '/resolve/' + revision + '/' + urllib.parse.quote(filename, safe='/'))
        with self._open(url, token, offset=offset) as response:
            if response.headers.get('Content-Encoding', 'identity') != 'identity':
                raise ValueError('encoded download refused')
            if offset and response.status == 200:
                raise RangeRestart('provider ignored range')
            if response.status == 206:
                match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('Content-Range', ''))
                if total is None or not match or tuple(map(int, match.groups())) != (offset, total - 1, total):
                    raise ValueError('invalid provider range')
            elif response.status != 200 or offset:
                raise ValueError('invalid provider response')
            length = response.headers.get('Content-Length')
            if total is not None and length is not None and length != str(total - offset):
                raise ValueError('invalid provider length')
            while True:
                chunk = response.read(1024 ** 2)
                if not chunk:
                    break
                yield chunk


class LearningImports:
    def __init__(self, root, authorize, credential, *, transport=None, limits=None):
        limits = {} if limits is None else limits
        defaults = dict(max_file_bytes=MAX_FILE, max_total_bytes=MAX_TOTAL, reserve_bytes=1024 ** 3)
        if (not isinstance(limits, dict) or set(limits) - defaults.keys()
                or any(type(v) is not int or not 0 <= v <= 1024 ** 4 for v in limits.values())):
            raise ValueError('invalid import limits')
        self.limits = {**defaults, **limits}
        if not 0 < self.limits['max_file_bytes'] <= self.limits['max_total_bytes']:
            raise ValueError('invalid import limits')
        self.root = Path(root).absolute()
        self._safe(self.root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.authorize, self.credential = authorize, credential
        self.transport = transport or HFTransport()
        self.lock = threading.RLock()
        self.worker = threading.Lock()
        self.db_path = self.root / 'imports.sqlite3'
        self._safe(self.db_path)
        with self._db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, document TEXT NOT NULL)')
        with self._lease() as owned:
            if owned:
                self._interrupt_orphans()
        os.chmod(self.db_path, 0o600)

    @contextmanager
    def _lease(self):
        path = self.root / '.worker.lock'
        self._safe(path)
        with os.fdopen(os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600), 'r+b') as stream:
            try:
                if os.name == 'nt':
                    import msvcrt
                    if os.fstat(stream.fileno()).st_size == 0:
                        stream.write(b'0'); stream.flush()
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN): raise
                yield False
            else:
                yield True

    def _interrupt_orphans(self):
        with self._db() as db:
            for row in db.execute('SELECT document FROM jobs').fetchall():
                job = json.loads(row[0])
                if job['status'] == 'running':
                    job.update(status='interrupted', error='worker_interrupted', reserved_bytes=0)
                    self._write(db, job)

    @staticmethod
    def _safe(path):
        for item in (path, *path.parents):
            if item.is_symlink():
                raise ValueError('symlink forbidden')

    @contextmanager
    def _db(self):
        self._safe(self.db_path)
        db = sqlite3.connect(self.db_path, timeout=10)
        try:
            with db:
                db.execute('BEGIN IMMEDIATE')
                yield db
        finally:
            db.close()

    @staticmethod
    def _write(db, job):
        db.execute('INSERT OR REPLACE INTO jobs VALUES (?, ?)', (job['id'], json.dumps(job)))

    def _load(self, job_id, db=None):
        if not isinstance(job_id, str) or not re.fullmatch('[a-f0-9]{32}', job_id):
            raise ValueError('invalid import id')
        with self._db() if db is None else nullcontext(db) as db:
            row = db.execute('SELECT document FROM jobs WHERE id=?', (job_id,)).fetchone()
        if row is None:
            raise ValueError('import not found')
        return json.loads(row[0])

    @staticmethod
    def _user(actor):
        return actor['user_id'] if isinstance(actor, dict) else actor

    def _credentials(self, actor, job, *, initial=False):
        self.authorize(actor, job['project_id'], 'import')
        if self._user(actor) != job['requester_id']:
            raise PermissionError('requester required')
        result = self.credential(actor, job['project_id'], job['connection_id'],
                                 generation=None if initial else job['generation'],
                                 resource=job['repo_type'] + ':' + job['repo_id'])
        if (not isinstance(result.get('token'), str) or not result['token']
                or type(result.get('generation')) is not int):
            raise PermissionError('connection unavailable')
        if not initial and result['generation'] != job['generation']:
            raise PermissionError('connection changed')
        return result

    def create(self, actor, project_id, connection_id, repo_type, repo_id, revision, files, rights):
        self.authorize(actor, project_id, 'import')
        if repo_type not in ('dataset', 'model'):
            raise ValueError('unsupported repository kind')
        if (not isinstance(repo_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+', repo_id)
                or '..' in repo_id or repo_id.endswith(('.', '.git'))):
            raise ValueError('invalid repository')
        if not isinstance(revision, str) or not re.fullmatch(r'[A-Za-z0-9_./-]{1,200}', revision):
            raise ValueError('invalid revision')
        if (not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES
                or not all(isinstance(name, str) for name in files) or len(set(files)) != len(files)):
            raise ValueError('invalid selected files')
        files = [_filename(name) for name in files]
        if (not isinstance(rights, dict) or rights.get('internal_use') is not True
                or not isinstance(rights.get('evidence'), str) or not rights['evidence'].strip()
                or len(rights['evidence']) > 4000):
            raise ValueError('internal use evidence required')
        if 'license' in rights and (not isinstance(rights['license'], str) or len(rights['license']) > 200):
            raise ValueError('invalid license')
        rights = {key: rights[key] for key in ('internal_use', 'evidence', 'license',
                                              'gated_team_use', 'team_use_evidence')
                  if key in rights}
        if 'team_use_evidence' in rights and (not isinstance(rights['team_use_evidence'], str)
                                             or len(rights['team_use_evidence']) > 4000):
            raise ValueError('invalid team use evidence')
        job = dict(id=uuid.uuid4().hex, project_id=project_id, requester_id=self._user(actor),
                   connection_id=connection_id, repo_type=repo_type, repo_id=repo_id,
                   requested_revision=revision, rights=rights, created_at=time.time(),
                   curation_status='pending_curation', error=None)
        cred = self._credentials(actor, job, initial=True)
        metadata = self.transport.resolve(repo_type, repo_id, revision, cred['token'])
        sha = metadata.get('sha')
        if not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{40}', sha):
            raise ValueError('provider immutable revision missing')
        names = {item['rfilename']: item for item in metadata.get('siblings', [])}
        entries = []
        for name in files:
            item = names.get(name, {})
            size = item.get('size')
            if type(size) is not int or not 0 <= size <= self.limits['max_file_bytes']:
                raise ValueError('file missing or exceeds size limit')
            expected = (item.get('lfs') or {}).get('sha256')
            if expected is not None and (not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected)):
                raise ValueError('invalid provider checksum')
            entries.append(dict(path=name, bytes=size, expected_sha256=expected))
        if sum(item['bytes'] for item in entries) > self.limits['max_total_bytes']:
            raise ValueError('import exceeds size limit')
        gated = metadata.get('gated', False) not in (False, None)
        job.update(revision=sha, files=entries, generation=cred['generation'],
                   gated=gated, private=bool(metadata.get('private')), status='queued', reserved_bytes=0)
        if gated and not (rights.get('gated_team_use') is True and rights.get('team_use_evidence', '').strip()):
            job['status'] = 'rights_hold'
            job['error'] = 'gated_team_use_evidence_required'
        self._credentials(actor, job)
        with self.lock, self._db() as db:
            rows = [json.loads(row[0]) for row in db.execute('SELECT document FROM jobs')]
            for previous in rows:
                keys = ('project_id', 'requester_id', 'connection_id', 'generation', 'repo_type',
                        'repo_id', 'revision', 'rights')
                selected = [{key: item[key] for key in ('path', 'bytes', 'expected_sha256')}
                            for item in previous['files']]
                if previous['status'] not in ('cancelled', 'failed', 'blocked') and all(
                        previous[key] == job[key] for key in keys) and selected == entries:
                    return previous
            if sum(row['status'] in ('queued', 'running') for row in rows) >= 32:
                raise ValueError('import queue full')
            self._write(db, job)
        return job

    def get(self, actor, project_id, job_id):
        self.authorize(actor, project_id, 'view')
        job = self._load(job_id)
        if job['project_id'] != project_id:
            raise PermissionError('project mismatch')
        return job

    def list(self, actor, project_id):
        self.authorize(actor, project_id, 'view')
        with self._lease() as owned:
            if owned:
                self._interrupt_orphans()
        with self._db() as db:
            rows = [json.loads(row[0]) for row in db.execute('SELECT document FROM jobs')]
        return sorted((row for row in rows if row['project_id'] == project_id),
                      key=lambda row: row['created_at'], reverse=True)

    def retry(self, actor, project_id, job_id):
        with self.lock:
            job = self.get(actor, project_id, job_id)
            self._credentials(actor, job)
            with self._lease() as owned:
                if owned:
                    self._interrupt_orphans()
            with self._db() as db:
                job = self._load(job_id, db)
                if job['status'] not in ('queued', 'failed', 'interrupted', 'blocked', 'cancelled'):
                    raise ValueError('import cannot retry')
                job.update(status='queued', error=None, reserved_bytes=0)
                self._write(db, job)
        return job

    def cancel(self, actor, project_id, job_id):
        with self.lock:
            job = self.get(actor, project_id, job_id)
            self.authorize(actor, project_id, 'import')
            if self._user(actor) != job['requester_id']:
                raise PermissionError('requester required')
            with self._db() as db:
                job = self._load(job_id, db)
                if job['status'] == 'completed':
                    raise ValueError('completed import cannot cancel')
                job.update(status='cancelled', error=None, reserved_bytes=0)
                self._write(db, job)
        return job

    def _checkpoint(self, actor, job, db=None):
        current = self._load(job['id'], db)
        if current['status'] != 'running' or current.get('attempt') != job.get('attempt'):
            raise InterruptedError('import cancelled')
        return self._credentials(actor, job)

    def _progress(self, job):
        with self._db() as db:
            current = self._load(job['id'], db)
            if current['status'] != 'running' or current.get('attempt') != job.get('attempt'):
                raise InterruptedError('import cancelled')
            self._write(db, job)

    def _space(self, remaining):
        try:
            free = shutil.disk_usage(self.root).free
        except OSError:
            raise ImportFailure('storage_unavailable') from None
        if free < remaining + self.limits['reserve_bytes'] + 1024 ** 2:
            raise ImportFailure('insufficient_space')

    @contextmanager
    def _partial(self, actor, job, entry, dest):
        self._safe(dest)
        dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0)
        with os.fdopen(os.open(dest, flags, 0o600), 'r+b') as output:
            info = os.fstat(output.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError('regular private file required')
            size, digest = entry.get('downloaded_bytes', 0), hashlib.sha256()
            trusted = entry.get('sha256') or entry.get('partial_sha256')
            if (0 <= size <= min(info.st_size, entry['bytes']) and trusted
                    and (entry.get('sha256') or entry['expected_sha256'])):
                unread = size
                while unread:
                    chunk = output.read(min(unread, 1024 ** 2))
                    if not chunk: break
                    self._checkpoint(actor, job)
                    digest.update(chunk)
                    unread -= len(chunk)
                valid = unread == 0 and digest.hexdigest() == trusted
            else:
                valid = False
            if not valid:
                output.seek(0); output.truncate()
                size, digest = 0, hashlib.sha256()
                entry.pop('sha256', None)
            # A crash may leave an uncommitted tail after the durable checkpoint.
            output.seek(size); output.truncate()
            entry.update(downloaded_bytes=size, partial_sha256=digest.hexdigest())
            yield output, size, digest

    def _download(self, actor, job, entry, dest, remaining):
        with self._partial(actor, job, entry, dest) as (output, size, digest):
            self._space(entry['bytes'] - size + remaining)
            job['reserved_bytes'] = entry['bytes'] - size + remaining
            self._progress(job)
            saved, measured = size, time.monotonic()
            try:
                while size < entry['bytes']:
                    cred = self._checkpoint(actor, job)
                    options = dict(offset=size, total=entry['bytes']) if size else {}
                    try:
                        for chunk in self.transport.chunks(job['repo_type'], job['repo_id'], job['revision'],
                                                           entry['path'], cred['token'], **options):
                            self._checkpoint(actor, job)
                            if size + len(chunk) > entry['bytes']:
                                raise ImportFailure('verification_failed')
                            self._space(len(chunk))
                            output.write(chunk); digest.update(chunk); size += len(chunk)
                            if size - saved >= 8 * 1024 ** 2 or time.monotonic() - measured >= 1:
                                output.flush(); os.fsync(output.fileno())
                                entry.update(downloaded_bytes=size, partial_sha256=digest.hexdigest())
                                job['reserved_bytes'] = entry['bytes'] - size + remaining
                                self._progress(job)
                                saved, measured = size, time.monotonic()
                        break
                    except RangeRestart:
                        if not options: raise
                        output.seek(0); output.truncate()
                        size, digest = 0, hashlib.sha256()
                        self._space(entry['bytes'] + remaining)
                if size != entry['bytes'] or (entry['expected_sha256'] is not None
                                               and digest.hexdigest() != entry['expected_sha256']):
                    # A bad complete prefix must not become a perpetual resume candidate.
                    output.seek(0); output.truncate()
                    size, digest = 0, hashlib.sha256()
                    raise ImportFailure('verification_failed')
                entry['sha256'] = digest.hexdigest()
            finally:
                output.flush(); os.fsync(output.fileno())
                entry.update(downloaded_bytes=size, partial_sha256=digest.hexdigest())
                job['reserved_bytes'] = entry['bytes'] - size + remaining
                self._progress(job)

    @staticmethod
    def _media(stage, job):
        extensions = ('.png', '.jpg', '.jpeg', '.webp', '.mp4', '.mkv', '.mov', '.avi')
        if job['repo_type'] != 'dataset' or not any(
                row['path'].lower().endswith(extensions) for row in job['files']):
            return
        contracts = str(Path(__file__).resolve().parents[3] / 'contracts/learning/src')
        if contracts not in sys.path:
            sys.path.insert(0, contracts)
        from rosy.contracts.learning.artifacts import seal
        from rosy.contracts.learning.media import media_eligibility, validate_media
        rights = json.dumps(job['rights'], sort_keys=True).encode('utf-8')
        rights_path = stage / 'rights.json'
        LearningImports._safe(rights_path)
        rights_path.write_bytes(rights)
        evidence = {'path': 'rights.json', 'sha256': hashlib.sha256(rights).hexdigest(), 'bytes': len(rights)}
        doc = seal(dict(schema='rosy.media-manifest/1', profile='actionless_media_v1',
            media_id=job['id'], project_id=job['project_id'], media_kind='unknown',
            source=dict(kind='external_unknown', capture_session=None, source_group=None, parents=[],
                upstream=dict(provider='huggingface', repo_type='dataset', repo_id=job['repo_id'],
                              revision=job['revision'])),
            files=[dict(path='files/' + row['path'], sha256=row['sha256'], bytes=row['bytes'])
                   for row in job['files']],
            labels=dict(ontology_revision=None, semantic_ids=[], origin='none', status='unreviewed',
                        author=None, reviewer=None, evidence=[]),
            rights=dict(license=None, evidence=[evidence], view='unknown', train='unknown',
                        infer='unknown', share='unknown')))
        validate_media(doc, root=stage)
        job['eligibility'] = media_eligibility(doc)
        job['media_revision'] = doc['revision']
        sidecar = stage / 'media.json'
        LearningImports._safe(sidecar)
        sidecar.write_text(json.dumps(doc, sort_keys=True), encoding='utf-8')

    def _published(self, job, final, tick):
        self._safe(final)
        manifest = final / 'manifest.json'
        self._safe(manifest)
        if not manifest.is_file() or manifest.stat().st_size > 1024 ** 2:
            raise ValueError('invalid published artifact')
        published = json.loads(manifest.read_text(encoding='utf-8'))
        for key in ('id', 'project_id', 'requester_id', 'connection_id', 'generation',
                    'repo_type', 'repo_id', 'revision', 'rights'):
            if published.get(key) != job[key]:
                raise ValueError('published artifact identity mismatch')
        if len(published['files']) != len(job['files']):
            raise ValueError('published file count mismatch')
        for row, expected in zip(published['files'], job['files']):
            if any(row[key] != expected[key] for key in ('path', 'bytes', 'expected_sha256')):
                raise ValueError('published file identity mismatch')
            path = final / 'files' / _filename(row['path'])
            self._safe(path)
            digest = hashlib.sha256()
            if path.stat().st_size != row['bytes']:
                raise ValueError('published size mismatch')
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 ** 2), b''):
                    tick()
                    digest.update(chunk)
            if (digest.hexdigest() != row['sha256'] or (expected['expected_sha256'] is not None
                    and digest.hexdigest() != expected['expected_sha256'])):
                raise ValueError('published checksum mismatch')
        if published.get('media_revision'):
            contracts = str(Path(__file__).resolve().parents[3] / 'contracts/learning/src')
            if contracts not in sys.path:
                sys.path.insert(0, contracts)
            from rosy.contracts.learning.media import validate_media
            sidecar = final / 'media.json'
            self._safe(sidecar)
            if sidecar.stat().st_size > 1024 ** 2:
                raise ValueError('invalid media sidecar')
            doc = validate_media(json.loads(sidecar.read_text(encoding='utf-8')), root=final)
            if doc['revision'] != published['media_revision']:
                raise ValueError('published media revision mismatch')
        return published

    def verified(self, actor, project_id, job_id):  # completed import re-read from disk: (job, {path: file})
        job = self.get(actor, project_id, job_id)
        self.authorize(actor, project_id, 'import')
        if job['status'] != 'completed': raise ValueError('import not completed')
        final = self.root / 'artifacts' / job['id']
        files = self._published(job, final, lambda: None)['files']
        return dict(job, files=files), {row['path']: final / 'files' / _filename(row['path']) for row in files}

    def record_review(self, actor, project_id, job_id, review):
        self.authorize(actor, project_id, 'import')
        with self.lock, self._db() as db:
            job = self._load(job_id, db)
            if job['project_id'] != project_id or job['status'] != 'completed': raise ValueError('import not completed')
            job.setdefault('review', review)   # the first registration stays; the review store dedups frames
            self._write(db, job)
        return job

    def _recover(self, actor, job, final):
        published = self._published(job, final, lambda: self._checkpoint(actor, job))
        with self.lock, self._db() as db:
            self._checkpoint(actor, job, db)
            published.pop('schema', None)
            published.update(status='completed', error=None, reserved_bytes=0)
            self._write(db, published)

    def run(self, job_id, actor):
        with self.worker, self._lease() as owned:
            if not owned:
                return
            with self.lock, self._db() as db:
                job = self._load(job_id, db)
                if job['status'] != 'queued':
                    return
                job.update(status='running', attempt=uuid.uuid4().hex)
                self._write(db, job)
            stage = self.root / '.partial' / job_id
            final = self.root / 'artifacts' / job_id
            try:
                self._checkpoint(actor, job)
                if final.exists():
                    self._recover(actor, job, final)
                    return
                self._safe(stage)
                stage.mkdir(parents=True, exist_ok=True, mode=0o700)
                for entry in job['files']:
                    dest = stage / 'files' / _filename(entry['path'])
                    with self._partial(actor, job, entry, dest):
                        pass
                remaining = sum(row['bytes'] - row['downloaded_bytes'] for row in job['files'])
                self._space(remaining)
                job['reserved_bytes'] = remaining
                self._progress(job)
                for entry in job['files']:
                    self._checkpoint(actor, job)
                    dest = stage / 'files' / _filename(entry['path'])
                    remaining -= entry['bytes'] - entry['downloaded_bytes']
                    self._download(actor, job, entry, dest, remaining)
                self._checkpoint(actor, job)
                self._media(stage, job)
                with self.lock, self._db() as db:
                    self._checkpoint(actor, job, db)
                    job.update(status='completed', completed_at=time.time(), error=None, reserved_bytes=0)
                    manifest = stage / 'manifest.json'
                    self._safe(manifest)
                    with manifest.open('w', encoding='utf-8') as output:
                        json.dump({'schema': 'rosy.learning.import/1', **job}, output, sort_keys=True)
                        output.flush()
                        os.fsync(output.fileno())
                    self._safe(final)
                    final.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    if final.exists():
                        raise ValueError('artifact already exists')
                    os.rename(stage, final)
                    self._write(db, job)
            except Exception as exc:
                with self.lock:
                    with self._db() as db:
                        current = self._load(job_id, db)
                        if current['status'] == 'running' and current.get('attempt') == job.get('attempt'):
                            code = ('access_revoked' if isinstance(exc, PermissionError) else
                                    str(exc) if isinstance(exc, ImportFailure) else
                                    'insufficient_space' if isinstance(exc, OSError) and exc.errno == errno.ENOSPC
                                    else 'import_failed')
                            current.update(status='blocked' if isinstance(exc, PermissionError) else 'failed',
                                           error=code, reserved_bytes=0)
                            self._write(db, current)
