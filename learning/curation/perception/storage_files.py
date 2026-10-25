"""Descriptor-bound managed artifact files; metadata stays outside reclaimable roots."""
from contextlib import contextmanager, ExitStack
import hashlib
import errno
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat

from storage_inventory import free_space, open_root, size


SOURCE = 'storage-source.json'
PROFILES = {
    'isaac': {'.json', '.jsonl', '.png', '.jpg', '.jpeg', '.mp4', '.npz', '.npy', '.parquet',
              '.yaml', '.yml', '.csv', '.txt', '.md', '.safetensors'},
    'dataset': {'.json', '.jsonl', '.png', '.jpg', '.jpeg', '.mp4', '.parquet', '.npz', '.npy', '.yaml', '.md'},
    'model': {'.json', '.safetensors', '.md'},
}


@contextmanager
def claim(fd, *, exclusive=False):
    import fcntl
    try:
        fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
    except OSError as error:
        if error.errno not in (errno.EAGAIN, errno.EACCES): raise
        raise ValueError('managed artifact is in use') from None
    try: yield
    finally: fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def consumer(root):
    """Hold finalized managed data through a native consumer's complete read lifetime."""
    if not (Path(root) / SOURCE).exists():
        yield
        return
    fd = open_root(str(Path(root).absolute()))
    try:
        with claim(fd): yield
    finally: os.close(fd)


def parts(value, *, internal=False):
    if (not isinstance(value, str) or not value or len(value) > 500 or '\\' in value
            or PurePosixPath(value).is_absolute() or PurePosixPath(value).as_posix() != value
            or any(p in ('', '.', '..') or (p.startswith('.') and not internal) for p in value.split('/'))):
        raise ValueError('relative managed artifact path required')
    return value.split('/')


def allowed(name, profile):
    path = PurePosixPath('/'.join(parts(name)))
    if (profile not in PROFILES or path.suffix.lower() not in PROFILES[profile]
            or any(p.lower() in ('private', 'secrets', 'tokens', 'credentials') for p in path.parts)):
        raise ValueError('artifact file is outside its profile')


@contextmanager
def directory(root, names, *, create=False):
    fd = os.dup(root)
    try:
        for name in names:
            if create:
                try: os.mkdir(name, 0o700, dir_fd=fd)
                except FileExistsError: pass
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd); fd = child
        yield fd
    finally:
        os.close(fd)


def file_open(root, relative, *, write=False):
    names = parts(relative)
    with directory(root, names[:-1], create=write) as parent:
        flags = os.O_NOFOLLOW | os.O_NONBLOCK | (os.O_RDWR | os.O_CREAT if write else os.O_RDONLY)
        fd = os.open(names[-1], flags, 0o600, dir_fd=parent)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        os.close(fd)
        raise ValueError('linked or special artifact file refused')
    return os.fdopen(fd, 'r+b' if write else 'rb')


def names(root):
    result = set()
    def visit(fd, prefix, depth):
        if depth > 32: raise ValueError('artifact tree is too deep')
        with os.scandir(fd) as entries:
            for entry in entries:
                name = prefix + entry.name
                parts(name)
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    with directory(fd, [entry.name]) as child: visit(child, name + '/', depth + 1)
                elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                    result.add(name)
                else:
                    raise ValueError('linked or special artifact entry refused')
                if len(result) > 10000: raise ValueError('artifact exceeds 10000 files')
    visit(root, '', 0)
    return result


def entry(root, relative):
    with file_open(root, relative) as stream:
        before = os.fstat(stream.fileno())
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        after = os.fstat(stream.fileno())
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError('artifact changed while hashing')
    return dict(bytes=after.st_size, sha256=digest)


def consume(chunks, expected, checkpoint, output=None):
    digest, count = hashlib.sha256(), 0
    for chunk in chunks:
        checkpoint()
        if not isinstance(chunk, bytes): raise ValueError('invalid remote bytes')
        count += len(chunk)
        if count > expected['bytes']: raise ValueError('remote file exceeds manifest')
        digest.update(chunk)
        if output is not None: output.write(chunk)
    if count != expected['bytes'] or digest.hexdigest() != expected['sha256']:
        raise ValueError('remote bytes differ from manifest')


class Files:
    def __init__(self, inventory):
        self.inventory = inventory
        self.roots = {row['id']: dict(row) for row in inventory.config['roots']}
        self.cache_id = inventory.config['pool']['managed_root_id']
        if self.cache_id not in self.roots or self.roots[self.cache_id]['role'] != 'cache':
            raise ValueError('managed storage needs a registered cache root')

    @contextmanager
    def open(self, location):
        root = open_root(self.roots[location['root_id']]['path'])
        try:
            with directory(root, parts(location['relative'], internal=True)) as fd:
                info = os.fstat(fd)
                if location.get('identity') is not None and location['identity'] != [info.st_dev, info.st_ino]:
                    raise ValueError('managed directory identity changed')
                yield fd
        finally:
            os.close(root)

    def exists(self, location):
        try:
            with self.open(location): return True
        except FileNotFoundError:
            return False

    @contextmanager
    def exclusive(self, location):
        with self.open(location) as fd, claim(fd, exclusive=True): yield

    def path(self, location):
        return Path(self.roots[location['root_id']]['path']).joinpath(*parts(location['relative'], internal=True))

    def manifest(self, location, profile):
        if profile not in PROFILES: raise ValueError('unknown artifact profile')
        with self.open(location) as fd:
            with file_open(fd, SOURCE) as stream: raw = stream.read(1024 ** 2 + 1)
            if len(raw) > 1024 ** 2: raise ValueError('source manifest is too large')
            source = json.loads(raw)
            files = source.get('files')
            if (source.get('schema') != 'rosy.storage-source/1' or source.get('status') != 'completed'
                    or source.get('profile') != profile or not isinstance(files, dict) or not 1 <= len(files) <= 9999
                    or not isinstance(source.get('provenance'), dict) or SOURCE in files):
                raise ValueError('completed, explicit artifact source manifest required')
            if profile == 'isaac' and (not isinstance(source['provenance'].get('run_id'), str)
                    or type(source['provenance'].get('seed')) is not int
                    or not re.fullmatch(r'[0-9a-f]{40}', source['provenance'].get('source_revision', ''))):
                raise ValueError('Isaac run, seed and source revision required')
            for name, expected in files.items():
                allowed(name, profile)
                if (not isinstance(expected, dict) or set(expected) != {'bytes', 'sha256'}
                        or not isinstance(expected['sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', expected['sha256'])):
                    raise ValueError('artifact file is outside its profile')
                size(expected['bytes'])
            if names(fd) != set(files) | {SOURCE}: raise ValueError('source file set differs from manifest')
            if any(entry(fd, name) != expected for name, expected in files.items()):
                raise ValueError('source bytes differ from manifest')
            info = os.fstat(fd)
            return dict(files={**files, SOURCE: entry(fd, SOURCE)}, provenance=source['provenance'],
                        identity=[info.st_dev, info.st_ino])

    def verify(self, location, files, *, subset=False):
        with self.open(location) as fd:
            present = names(fd)
            if (not present <= files.keys()) or (not subset and present != files.keys()):
                raise ValueError('local file set differs from verified manifest')
            if any(entry(fd, name) != files[name] for name in present):
                raise ValueError('local bytes differ from verified manifest')

    @contextmanager
    def streams(self, location, files):
        self.verify(location, files)
        with self.open(location) as fd, ExitStack() as stack:
            yield {name: stack.enter_context(file_open(fd, name)) for name in files}

    def quarantine(self, location, job_id):
        path = parts(location['relative'], internal=True)
        hidden = '.reclaim-' + job_id
        target = dict(location, relative='/'.join([*path[:-1], hidden]))
        if self.exists(target): raise ValueError('cleanup destination already exists')
        root = open_root(self.roots[location['root_id']]['path'])
        try:
            with directory(root, path[:-1]) as parent:
                os.rename(path[-1], hidden, src_dir_fd=parent, dst_dir_fd=parent)
                os.fsync(parent)
        finally: os.close(root)
        return target

    def delete(self, location, files):
        self.verify(location, files, subset=True)
        def clear(fd, prefix=''):
            with os.scandir(fd) as entries:
                for item in entries:
                    if item.is_dir(follow_symlinks=False):
                        with directory(fd, [item.name]) as child: clear(child, prefix + item.name + '/')
                        os.rmdir(item.name, dir_fd=fd)
                    else:
                        expected = files.get(prefix + item.name)
                        if expected is None or entry(fd, item.name) != expected:
                            raise ValueError('cleanup file changed after verification')
                        os.unlink(item.name, dir_fd=fd)
        with self.open(location) as fd: clear(fd)
        path = parts(location['relative'], internal=True)
        root = open_root(self.roots[location['root_id']]['path'])
        try:
            with directory(root, path[:-1]) as parent:
                os.rmdir(path[-1], dir_fd=parent); os.fsync(parent)
        finally: os.close(root)

    def restore(self, job, chunks, checkpoint):
        root = open_root(self.roots[self.cache_id]['path'])
        partial = '.' + job['id'] + '.partial'
        result = dict(root_id=self.cache_id, relative=job['id'])
        try:
            if self.exists(result):
                self.verify(result, job['files'])
                with self.open(result) as fd:
                    info = os.fstat(fd); result['identity'] = [info.st_dev, info.st_ino]
                return result
            if free_space(root) < sum(v['bytes'] for v in job['files'].values()) + self.inventory.reserve:
                raise ValueError('insufficient local space for restoration')
            try: os.mkdir(partial, 0o700, dir_fd=root)
            except FileExistsError: pass
            with directory(root, [partial]) as fd:
                if not names(fd) <= job['files'].keys(): raise ValueError('unknown partial restoration files')
                for name, expected in job['files'].items():
                    checkpoint()
                    with file_open(fd, name, write=True) as output:
                        output.truncate(0)
                        def check():
                            checkpoint()
                            if free_space(root) < self.inventory.reserve + 1024 ** 2:
                                raise ValueError('insufficient local space during restoration')
                        consume(chunks(name), expected, check, output)
                        output.flush(); os.fsync(output.fileno())
                os.fsync(fd)
                info = os.fstat(fd); result['identity'] = [info.st_dev, info.st_ino]
            if self.exists(result): raise ValueError('restore destination already exists')
            os.rename(partial, job['id'], src_dir_fd=root, dst_dir_fd=root); os.fsync(root)
            return result
        finally: os.close(root)

    def available(self):
        fd = open_root(self.roots[self.cache_id]['path'])
        try: return free_space(fd)
        finally: os.close(fd)
