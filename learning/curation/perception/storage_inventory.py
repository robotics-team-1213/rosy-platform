"""Bounded, descriptor-based storage metadata reads; never transfers or deletes data."""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import threading
import time


LIMIT = 9_000_000_000_000_000
ROLES = {'raw', 'derived', 'cache', 'pending'}


def size(value):
    if type(value) is not int or not 0 <= value <= LIMIT:
        raise ValueError('bytes must be a nonnegative bounded integer')
    return value


def open_root(path):
    # Opening every component without following links also rejects swapped parent links.
    if os.name != 'posix' or not hasattr(os, 'O_NOFOLLOW'):
        raise OSError('descriptor storage scan requires POSIX')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open('/', flags)
    try:
        for part in Path(path).parts[1:]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd); fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def free_space(fd):
    value = os.fstatvfs(fd)
    return value.f_bavail * value.f_frsize


class StorageInventory:
    def __init__(self, db, config, project_id, *, clock=time.time):
        self.config = copy.deepcopy(config)
        if not isinstance(config, dict) or config.get('project_id') != project_id:
            raise ValueError('storage project must match workspace project')
        roots = config.get('roots')
        if not isinstance(roots, list) or not 1 <= len(roots) <= 16:
            raise ValueError('register 1..16 storage roots')
        paths, identifiers = [], set()
        for row in roots:
            if (not isinstance(row, dict) or not isinstance(row.get('id'), str)
                    or not re.fullmatch(r'[a-z][a-z0-9-]{0,39}', row['id'])
                    or row['id'] in identifiers or row.get('role') not in ROLES
                    or not isinstance(row.get('label'), str) or not 1 <= len(row['label']) <= 80
                    or not isinstance(row.get('path'), str)):
                raise ValueError('invalid registered storage root')
            path = Path(row['path'])
            if (not path.is_absolute() or '..' in path.parts or path.resolve() != path
                    or any(path == old or path in old.parents or old in path.parents for old in paths)
                    or Path(db).resolve().is_relative_to(path)):
                raise ValueError('storage roots must be distinct non-linked directories outside the history DB')
            paths.append(path); identifiers.add(row['id'])
        self.reserve = size(config.get('reserve_bytes', 1024 ** 3))
        quota = config.get('remote_quota')
        if quota is not None:
            if (not isinstance(quota, dict) or not isinstance(quota.get('source'), str)
                    or not 1 <= len(quota['source']) <= 160):
                raise ValueError('remote quota needs a source')
            for key in ('remaining_bytes', 'measured_at', 'expires_at'): size(quota.get(key))
            if quota['measured_at'] >= quota['expires_at']:
                raise ValueError('remote quota needs an expiry after measurement')
        self.db, self.project_id, self.clock = Path(db), project_id, clock
        self.fingerprint = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
        self.lock, self.cached, self.cached_at = threading.RLock(), None, 0
        self.max_entries, self.scan_seconds = 100000, 5
        with sqlite3.connect(self.db) as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS storage_samples
                (project TEXT, config TEXT, root TEXT, day INTEGER, measured REAL, bytes INTEGER,
                 PRIMARY KEY(project,config,root,day))''')

    def _scan(self, definition, budget):
        row = {key: definition[key] for key in ('id', 'label', 'role')}
        row.update(status='ready', reason=None, files=0, logical_bytes=0, file_bytes=0,
                   allocated_bytes=0, incomplete_bytes=0, free_bytes=None,
                   growth_bytes_per_day=None, estimated_days=None)
        seen = set()

        def visit(fd, depth, incomplete=False):
            if depth > 64: raise OverflowError
            with os.scandir(fd) as entries:
                for entry in entries:
                    budget[0] += 1
                    if budget[0] > self.max_entries or time.monotonic() > budget[1]: raise OverflowError
                    info = entry.stat(follow_symlinks=False)
                    unfinished = incomplete or entry.name.endswith(('.part', '.partial', '.tmp')) or entry.name == '.partial'
                    if stat.S_ISDIR(info.st_mode):
                        child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                        try: visit(child, depth + 1, unfinished)
                        finally: os.close(child)
                    elif stat.S_ISREG(info.st_mode):
                        row['files'] += 1; row['logical_bytes'] += info.st_size
                        if unfinished: row['incomplete_bytes'] += info.st_size
                        identity = (info.st_dev, info.st_ino)
                        if identity not in seen:
                            seen.add(identity); row['file_bytes'] += info.st_size
                            row['allocated_bytes'] += info.st_blocks * 512
                    else:
                        row.update(status='partial', reason='linked_or_special_entry')

        fd = None
        try:
            fd = open_root(definition['path'])
            row['free_bytes'] = free_space(fd)
            visit(fd, 0)
        except OverflowError:
            row.update(status='partial', reason='scan_limit')
        except OSError:
            row.update(status='unavailable', reason='root_unavailable')
        finally:
            if fd is not None: os.close(fd)
        if row['status'] != 'ready':
            for key in ('files', 'logical_bytes', 'file_bytes', 'allocated_bytes', 'incomplete_bytes'):
                row[key] = None
        return row

    def snapshot(self, *, refresh=False):
        with self.lock:
            now = self.clock()
            if not refresh and self.cached is not None and 0 <= now - self.cached_at < 60:
                return copy.deepcopy(self.cached)
            budget = [0, time.monotonic() + self.scan_seconds]
            rows = [self._scan(root, budget) for root in self.config['roots']]
            with sqlite3.connect(self.db) as conn:
                for row in rows:
                    if row['status'] != 'ready': continue
                    conn.execute('INSERT OR REPLACE INTO storage_samples VALUES(?,?,?,?,?,?)',
                        (self.project_id, self.fingerprint, row['id'], int(now // 86400), now, row['file_bytes']))
                    older = conn.execute('''SELECT measured,bytes FROM storage_samples
                        WHERE project=? AND config=? AND root=? AND measured<=? AND measured>=?
                        ORDER BY measured LIMIT 1''',
                        (self.project_id, self.fingerprint, row['id'], now - 86400, now - 30 * 86400)).fetchone()
                    if older and row['file_bytes'] > older[1]:
                        rate = (row['file_bytes'] - older[1]) * 86400 / (now - older[0])
                        row['growth_bytes_per_day'] = rate
                        row['estimated_days'] = max(0, row['free_bytes'] - self.reserve) / rate
                conn.execute('DELETE FROM storage_samples WHERE project=? AND measured<?',
                             (self.project_id, now - 31 * 86400))
            pending = [row for row in rows if row['role'] == 'pending']
            self.cached = dict(status='ready' if all(row['status'] == 'ready' for row in rows) else 'partial',
                project_id=self.project_id, measured_at=now, roots=rows, reserve_bytes=self.reserve,
                pending_bytes=sum(row['logical_bytes'] - row['incomplete_bytes'] for row in pending)
                    if pending and all(row['status'] == 'ready' for row in pending) else None)
            self.cached_at = now
            return copy.deepcopy(self.cached)

    def preflight(self, body):
        keys = {'destination_id', 'download_bytes', 'staging_bytes', 'transform_bytes', 'upload_bytes'}
        if not isinstance(body, dict) or set(body) != keys:
            raise ValueError('destination ID and four byte estimates required; paths are not accepted')
        root = next((row for row in self.config['roots'] if row['id'] == body['destination_id']), None)
        if root is None: raise ValueError('unknown storage destination')
        for key in keys - {'destination_id'}: size(body[key])
        required = sum(body[key] for key in ('download_bytes', 'staging_bytes', 'transform_bytes')) + self.reserve
        available = None
        try:
            fd = open_root(root['path'])
            try: available = free_space(fd)
            finally: os.close(fd)
        except OSError: pass
        local = 'unknown' if available is None else 'sufficient' if available >= required else 'insufficient'
        now, quota = self.clock(), self.config.get('remote_quota')
        fresh = quota is not None and quota['measured_at'] <= now < quota['expires_at']
        remote = ('not_required' if body['upload_bytes'] == 0 else 'unknown' if not fresh else
                  'sufficient' if quota['remaining_bytes'] >= body['upload_bytes'] else 'insufficient')
        status = 'blocked' if 'insufficient' in (local, remote) else 'hold' if 'unknown' in (local, remote) else 'ready'
        return dict(status=status, measured_at=now, destination_id=root['id'],
            local_status=local, local_required_bytes=required, local_available_bytes=available,
            components={key: body[key] for key in ('download_bytes', 'staging_bytes', 'transform_bytes')},
            reserve_bytes=self.reserve, remote_status=remote, upload_bytes=body['upload_bytes'],
            remote_quota=dict(quota, fresh=fresh) if quota else None, reserved=False)
