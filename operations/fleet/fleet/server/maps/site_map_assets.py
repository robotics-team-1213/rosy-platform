"""Private immutable source/projection store; converter runs in a bounded child."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading

from fleet.server.site_map_projection import CONVERTER_VERSION, MAX_SOURCE_BYTES, canonical
from fleet.server.site_map_store import SiteMapError

MAX_STORE_BYTES = 1024 * 1024 * 1024


def drawing_error(status, suffix, detail):
    return SiteMapError(status, 'SITE_MAP_DRAWING_' + suffix, detail)


class SiteMapAssetStore:
    def __init__(self, root: Path):
        self.root = Path(root).absolute()
        if any(p.is_symlink() for p in (self.root, *self.root.parents)):
            raise drawing_error(503, 'UNAVAILABLE', 'asset directory must not be a symlink')
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.slot = threading.Lock()
        self._conversion = threading.Lock()
        self._process = None
        self.cancelled = threading.Event()

    def _path(self, digest, suffix):
        if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
            raise drawing_error(404, 'NOT_FOUND', 'unknown drawing hash')
        path = self.root / (digest + suffix)
        if path.is_symlink() or self.root.is_symlink():
            raise drawing_error(422, 'INVALID', 'symlink asset rejected')
        return path

    def _read(self, path, limit):
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, 'rb') as stream:
                data = stream.read(limit + 1)
            if len(data) > limit:
                raise drawing_error(413, 'LIMIT', 'stored asset exceeds size limit')
            return data
        except FileNotFoundError as exc:
            raise drawing_error(404, 'NOT_FOUND', 'drawing is not stored') from exc
        except OSError as exc:
            raise drawing_error(503, 'UNAVAILABLE', 'drawing cannot be read') from exc

    def _write(self, path, data):
        if self.cancelled.is_set():
            raise drawing_error(503, 'UNAVAILABLE', 'conversion cancelled')
        if path.exists():
            if self._read(path, len(data)) != data:
                raise drawing_error(422, 'INVALID', 'stored content does not match its hash')
            return
        temporary = None
        try:
            used = 0
            for entry in self.root.iterdir():
                if entry.is_symlink() or not entry.is_file():
                    raise drawing_error(422, 'INVALID', 'unexpected entry in asset directory')
                used += entry.stat().st_size
            if used + len(data) > MAX_STORE_BYTES:
                raise drawing_error(507, 'STORAGE', 'drawing storage quota exceeded')
            with tempfile.NamedTemporaryFile(dir=self.root, suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except OSError as exc:
            raise drawing_error(507, 'STORAGE', 'drawing could not be stored') from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def cancel_worker(self):
        self.cancelled.set()
        process = self._process
        if process is not None:
            try:
                process.kill()
            except ProcessLookupError:
                pass

    def _worker(self, path, operation, transform=None):
        if not self._conversion.acquire(blocking=False):
            raise drawing_error(429, 'BUSY', 'another conversion is running')
        process = None
        try:
            if self.cancelled.is_set():
                raise drawing_error(503, 'UNAVAILABLE', 'conversion cancelled')
            environment = {**os.environ, 'PYTHONPATH': os.pathsep.join(sys.path)}
            process = subprocess.Popen([sys.executable, '-m', 'fleet.server.site_map_projection'], env=environment,
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self._process = process
            request = {'path': str(path), 'operation': operation}
            if transform is not None:
                request['transform'] = transform.model_dump(mode='json')
            try:
                output, _ = process.communicate(input=canonical(request), timeout=5)
            except subprocess.TimeoutExpired as exc:
                process.kill()
                process.wait()
                raise drawing_error(503, 'UNAVAILABLE', 'drawing conversion timed out') from exc
            if process.returncode or self.cancelled.is_set():
                raise drawing_error(503, 'UNAVAILABLE', 'drawing converter did not complete')
            response = json.loads(output)
            if response.get('error'):
                limit = response['error'] == 'limit'
                raise drawing_error(413 if limit else 422, 'LIMIT' if limit else 'INVALID',
                                    'drawing exceeds limits' if limit else 'invalid STL or registration')
            return response['result']
        except (OSError, ValueError, KeyError) as exc:
            if isinstance(exc, SiteMapError):
                raise
            raise drawing_error(503, 'UNAVAILABLE', 'drawing converter unavailable') from exc
        finally:
            self._process = None
            if process is not None and process.returncode is None:
                process.kill()
                process.wait()
            self._conversion.release()

    def put_stl(self, path: Path) -> dict:
        # Copy once so the worker and content hash see the exact same bounded bytes.
        with Path(path).open('rb') as stream:
            data = stream.read(MAX_SOURCE_BYTES + 1)
        if len(data) > MAX_SOURCE_BYTES:
            raise drawing_error(413, 'LIMIT', 'STL source exceeds 16 MiB')
        digest = hashlib.sha256(data).hexdigest()
        target = self._path(digest, '.stl')
        metadata = self._path(digest, '.source.json')
        if target.exists() and metadata.exists():
            self.source(digest)
            return json.loads(self._read(metadata, 4096))
        with tempfile.NamedTemporaryFile(dir=self.root, suffix='.tmp') as stream:
            stream.write(data)
            stream.flush()
            result = self._worker(Path(stream.name), 'inspect')
        self._write(target, data)
        self._write(metadata, canonical(result))
        return result

    def project(self, asset_sha256, transform) -> dict:
        path = self.source(asset_sha256)
        result = self._worker(path, 'project', transform)
        self._write(self._path(result['projection_sha256'], '.projection.json'), canonical(result))
        return result

    def source(self, asset_sha256) -> Path:
        path = self._path(asset_sha256, '.stl')
        if hashlib.sha256(self._read(path, MAX_SOURCE_BYTES)).hexdigest() != asset_sha256:
            raise drawing_error(422, 'INVALID', 'stored source hash mismatch')
        return path

    def projection(self, projection_sha256) -> dict:
        path = self._path(projection_sha256, '.projection.json')
        try:
            result = json.loads(self._read(path, 8 * 1024 * 1024))
            body = {k: v for k, v in result.items() if k != 'projection_sha256'}
            expected = hashlib.sha256(canonical({'version': CONVERTER_VERSION, **body})).hexdigest()
            if result['projection_sha256'] != projection_sha256 or expected != projection_sha256:
                raise ValueError('projection hash mismatch')
            self.source(result['asset_sha256'])
            return result
        except (ValueError, KeyError) as exc:
            if isinstance(exc, SiteMapError):
                raise
            raise drawing_error(422, 'INVALID', 'stored projection hash mismatch') from exc

    def validate_reference(self, reference, survey_revision):
        result = self.projection(reference.projection_sha256)
        if result['asset_sha256'] != reference.asset_sha256 or survey_revision != reference.projection_sha256:
            raise drawing_error(422, 'INVALID', 'drawing and survey references must match')
