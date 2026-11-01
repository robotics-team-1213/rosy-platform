"""Bounded loopback transport for an authenticated distribution and public authorities."""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import os
from pathlib import Path
import re
import stat
import tempfile
import threading

AUTHORITIES = {'__operator__/release.pem': '/work/operator-release.pub.pem',
               '__operator__/cms.pem': '/work/operator-cms.pem'}
CHUNK = 2 * 1024**2


def _route(value):
    if (not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9._~+/-]+', value)
            or any(part in ('', '.', '..') for part in value.split('/'))):
        raise ValueError('public input route is not canonical')
    return value


def _plain(path, *, directory=False):
    info = path.lstat()
    if (stat.S_ISLNK(info.st_mode)
            or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)
            or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))):
        raise ValueError('public input must use plain directories and regular files')
    return info


def _open(path, size):
    for parent in reversed(path.parents):
        _plain(parent, directory=True)
    before = _plain(path)
    if before.st_size != size:
        raise ValueError('public input size differs from authenticated snapshot')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if (not stat.S_ISREG(opened.st_mode) or opened.st_size != size
                or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)):
            raise ValueError('public input changed while opening')
        return os.fdopen(descriptor, 'rb')
    except BaseException:
        os.close(descriptor)
        raise


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


@contextmanager
def _captures(dist, entries, sizes):
    # Verify private snapshots before listening; requests never reopen mutable source paths.
    with ExitStack() as cleanup:
        captured = {}
        for name, expected in entries.items():
            snapshot = cleanup.enter_context(tempfile.TemporaryFile())
            with _open(dist / name, sizes[name]) as incoming:
                identity = _identity(os.fstat(incoming.fileno()))
                digest, total = hashlib.sha256(), 0
                while raw := incoming.read(min(CHUNK, sizes[name] - total + 1)):
                    total += len(raw)
                    if total > sizes[name]:
                        raise ValueError('public input grew beyond its authenticated size')
                    digest.update(raw)
                    snapshot.write(raw)
                if (total != sizes[name] or digest.hexdigest() != expected
                        or _identity(os.fstat(incoming.fileno())) != identity):
                    raise ValueError('public input differs from its authenticated bytes')
            snapshot.seek(0)
            captured[name] = snapshot, threading.Lock(), identity
        yield captured


@contextmanager
def serve_inputs(dist, snapshot, certificate):
    """Expose only immutable, hash-verified public snapshots and captured authorities."""
    dist = Path(dist).absolute()
    entries, sizes = dict(snapshot['entries']), dict(snapshot['sizes'])
    if entries.keys() != sizes.keys():
        raise ValueError('public input snapshot size map differs')
    memory = {'SHA256SUMS': snapshot['checksums'], 'SHA256SUMS.sig': snapshot['signature'],
              '__operator__/release.pem': snapshot['public_key'], '__operator__/cms.pem': certificate}
    for name, limit in (('SHA256SUMS', 16 * 1024**2), ('SHA256SUMS.sig', 512),
                        ('__operator__/release.pem', 8192), ('__operator__/cms.pem', 32768)):
        raw = memory[name]
        if not isinstance(raw, bytes) or not 0 < len(raw) <= limit:
            raise ValueError('captured public input has invalid type or size')
        if name in AUTHORITIES and b'PRIVATE KEY' in raw:
            raise ValueError('private material is not a public authority')
    records = []
    for name, digest in entries.items():
        _route(name)
        if name in memory or name == '__operator__' or name.startswith('__operator__/'):
            raise ValueError('authenticated file collides with a captured public route')
        size = sizes[name]
        if type(size) is not int or size < 1 or not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
            raise ValueError('invalid authenticated file size or SHA256')
        records.append(dict(route=name, destination='/work/dist/' + name, size_bytes=size, sha256=digest))
    for name, raw in memory.items():
        records.append(dict(route=name, destination=AUTHORITIES.get(name, '/work/dist/' + name),
                            size_bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
    lookup = {row['route']: dict(row) for row in records}

    @contextmanager
    def source_for(route):
        if route in memory:
            with io.BytesIO(memory[route]) as source:
                yield source
        else:
            source, lock, identity = captured[route]
            with lock:
                with _open(dist / route, lookup[route]['size_bytes']) as current:
                    # Windows path stat and fstat can report different ctime values for the same file.
                    if _identity(os.fstat(current.fileno())) != identity:
                        raise ValueError('public input changed after capture')
                yield source

    class Handler(BaseHTTPRequestHandler):
        timeout = 30

        def log_message(self, *_args):
            pass

        def do_GET(self):
            route = self.path[1:] if self.path.startswith('/') else ''
            record = lookup.get(route)
            if record is None:
                self.send_error(404)
                return
            try:
                with source_for(route) as source:
                    self.send_source(source, record['size_bytes'])
            except (OSError, ValueError):
                self.send_error(404)

        def send_source(self, source, size):
            start, end, status = 0, size - 1, 200
            ranges = self.headers.get_all('Range', [])
            if ranges:
                match = re.fullmatch(r'bytes=([0-9]+)-([0-9]+)', ranges[0]) if len(ranges) == 1 and len(ranges[0]) <= 96 else None
                if match:
                    start, end = map(int, match.groups())
                if match is None or start >= size or end < start:
                    self.send_response(416)
                    self.send_header('Content-Range', f'bytes */{size}')
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                end, status = min(end, size - 1), 206
            self.send_response(status)
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Content-Length', str(end - start + 1))
            if status == 206:
                self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
            self.end_headers()
            source.seek(start)
            remaining = end - start + 1
            try:
                while remaining:
                    raw = source.read(min(CHUNK, remaining))
                    if not raw:
                        self.close_connection = True
                        break
                    self.wfile.write(raw)
                    remaining -= len(raw)
            except OSError:
                self.close_connection = True

    with _captures(dist, entries, sizes) as captured:
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.daemon_threads = False  # Join bounded handler lifetimes before closing snapshot handles.
        thread = threading.Thread(target=server.serve_forever, name='rosy-public-inputs', daemon=True)
        thread.start()
        try:
            yield dict(base_url=f'http://10.0.2.2:{server.server_port}', files=records)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


RECEIVE_SCRIPT = r'''
import json
from pathlib import Path
import re
import stat
import sys
from urllib.parse import urlsplit

sys.path.insert(0, '/work/source/tools/release')
from os_tools_vm import download

value = json.load(sys.stdin)
if not isinstance(value, dict) or set(value) != {'base_url', 'files'}:
    raise ValueError('invalid public input description')
base = value['base_url']
if not isinstance(base, str):
    raise ValueError('invalid public input origin')
origin = urlsplit(base)
if (origin.scheme != 'http' or origin.hostname != '10.0.2.2' or origin.port is None
        or not 1 <= origin.port <= 65535 or base != 'http://10.0.2.2:' + str(origin.port)):
    raise ValueError('invalid public input origin')
files = value['files']
if not isinstance(files, list) or not files:
    raise ValueError('invalid public input file list')
authorities = {'__operator__/release.pem': '/work/operator-release.pub.pem', '__operator__/cms.pem': '/work/operator-cms.pem'}
routes = set()
for row in files:
    if not isinstance(row, dict) or set(row) != {'route', 'destination', 'size_bytes', 'sha256'}:
        raise ValueError('invalid public input record')
    route = row['route']
    if (not isinstance(route, str) or not re.fullmatch(r'[A-Za-z0-9._~+/-]+', route)
            or any(part in ('', '.', '..') for part in route.split('/')) or route in routes):
        raise ValueError('invalid or duplicate public input route')
    if route == '__operator__' or route.startswith('__operator__/') and route not in authorities:
        raise ValueError('unknown public authority route')
    destination = authorities.get(route, '/work/dist/' + route)
    if (row['destination'] != destination or type(row['size_bytes']) is not int or row['size_bytes'] < 1
            or not isinstance(row['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', row['sha256'])):
        raise ValueError('invalid public input destination or digest binding')
    routes.add(route)
    path = Path(destination)
    if path.exists() or path.is_symlink():
        raise ValueError('public input destination already exists')
    for parent in path.parents:
        if parent.is_symlink():
            raise ValueError('public input destination parent redirects')
        if parent.exists() and not stat.S_ISDIR(parent.lstat().st_mode):
            raise ValueError('public input destination parent is not a directory')
work = Path('/work')
dist = work / 'dist'
if dist.exists() or dist.is_symlink():
    raise ValueError('public input distribution destination already exists')
dist.mkdir(parents=True, mode=0o700)
for row in files:
    destination = Path(row['destination'])
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    download(dict(url=base + '/' + row['route'], size_bytes=row['size_bytes'], sha256=row['sha256']), destination)
'''
