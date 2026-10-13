"""D-755 permission-bound, immutable HF imports. Downloaded code is never executed.

Create one service per application. Workers receive a current authenticated principal;
only requester IDs, never sessions or provider tokens, enter persistent jobs.
"""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import sqlite3
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

    def _open(self, url, token):
        if not isinstance(token, str) or not token or any(not 33 <= ord(c) <= 126 for c in token):
            raise ValueError('invalid provider credential')
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        for _ in range(6):
            parsed = self.check_url(url)
            headers = {'Accept-Encoding': 'identity', 'User-Agent': 'ROSY-learning-import/1'}
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

    def chunks(self, kind, repo, revision, filename, token):
        url = ('https://huggingface.co/' + ('datasets/' if kind == 'dataset' else '')
               + repo + '/resolve/' + revision + '/' + urllib.parse.quote(filename, safe='/'))
        with self._open(url, token) as response:
            while True:
                chunk = response.read(1024 ** 2)
                if not chunk:
                    break
                yield chunk


class LearningImports:
    def __init__(self, root, authorize, credential, *, transport=None):
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
            for row in db.execute('SELECT id, document FROM jobs').fetchall():
                job = json.loads(row[1])
                if job['status'] == 'running':
                    job.update(status='interrupted', error='worker_interrupted')
                    self._write(db, job)
        os.chmod(self.db_path, 0o600)

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
                yield db
        finally:
            db.close()

    @staticmethod
    def _write(db, job):
        db.execute('INSERT OR REPLACE INTO jobs VALUES (?, ?)', (job['id'], json.dumps(job)))

    def _load(self, job_id):
        if not isinstance(job_id, str) or not re.fullmatch('[a-f0-9]{32}', job_id):
            raise ValueError('invalid import id')
        with self._db() as db:
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
            if type(size) is not int or not 0 <= size <= MAX_FILE:
                raise ValueError('file missing or exceeds size limit')
            expected = (item.get('lfs') or {}).get('sha256')
            if expected is not None and not re.fullmatch('[0-9a-f]{64}', expected):
                raise ValueError('invalid provider checksum')
            entries.append(dict(path=name, bytes=size, expected_sha256=expected))
        if sum(item['bytes'] for item in entries) > MAX_TOTAL:
            raise ValueError('import exceeds size limit')
        gated = metadata.get('gated', False) not in (False, None)
        job.update(revision=sha, files=entries, generation=cred['generation'],
                   gated=gated, private=bool(metadata.get('private')), status='queued')
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
        with self._db() as db:
            rows = [json.loads(row[0]) for row in db.execute('SELECT document FROM jobs')]
        return sorted((row for row in rows if row['project_id'] == project_id),
                      key=lambda row: row['created_at'], reverse=True)

    def retry(self, actor, project_id, job_id):
        with self.lock:
            job = self.get(actor, project_id, job_id)
            self._credentials(actor, job)
            if job['status'] not in ('queued', 'failed', 'interrupted', 'blocked', 'cancelled'):
                raise ValueError('import cannot retry')
            job.update(status='queued', error=None)
            with self._db() as db:
                self._write(db, job)
        return job

    def cancel(self, actor, project_id, job_id):
        with self.lock:
            job = self.get(actor, project_id, job_id)
            self.authorize(actor, project_id, 'import')
            if self._user(actor) != job['requester_id']:
                raise PermissionError('requester required')
            if job['status'] == 'completed':
                raise ValueError('completed import cannot cancel')
            job.update(status='cancelled', error=None)
            with self._db() as db:
                self._write(db, job)
        return job

    def _checkpoint(self, actor, job):
        if self._load(job['id'])['status'] != 'running':
            raise InterruptedError('import cancelled')
        return self._credentials(actor, job)

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

    def _recover(self, actor, job, final):
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
                    self._checkpoint(actor, job)
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
        with self.lock:
            self._checkpoint(actor, job)
            published.pop('schema', None)
            published.update(status='completed', error=None)
            with self._db() as db:
                self._write(db, published)

    def run(self, job_id, actor):
        with self.worker:
            with self.lock, self._db() as db:
                job = self._load(job_id)
                if job['status'] != 'queued':
                    return
                job['status'] = 'running'
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
                    cred = self._checkpoint(actor, job)
                    dest = stage / 'files' / _filename(entry['path'])
                    self._safe(dest)
                    dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    digest, size = hashlib.sha256(), 0
                    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0)
                    with os.fdopen(os.open(dest, flags, 0o600), 'wb') as output:
                        for chunk in self.transport.chunks(job['repo_type'], job['repo_id'], job['revision'],
                                                           entry['path'], cred['token']):
                            self._checkpoint(actor, job)
                            size += len(chunk)
                            if size > entry['bytes']:
                                raise ValueError('download size exceeded')
                            digest.update(chunk)
                            output.write(chunk)
                        output.flush()
                        os.fsync(output.fileno())
                    if size != entry['bytes'] or (entry['expected_sha256'] is not None
                                                  and digest.hexdigest() != entry['expected_sha256']):
                        raise ValueError('download verification failed')
                    entry['sha256'] = digest.hexdigest()
                self._checkpoint(actor, job)
                self._media(stage, job)
                with self.lock:
                    self._checkpoint(actor, job)
                    job.update(status='completed', completed_at=time.time(), error=None)
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
                    with self._db() as db:
                        self._write(db, job)
            except Exception as exc:
                with self.lock:
                    current = self._load(job_id)
                    if current['status'] != 'cancelled':
                        current.update(status='blocked' if isinstance(exc, PermissionError) else 'failed',
                                       error='access_revoked' if isinstance(exc, PermissionError) else 'import_failed')
                        with self._db() as db:
                            self._write(db, current)
