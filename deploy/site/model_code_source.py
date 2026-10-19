"""D-446 signed archive retention and fresh installed-source closure.

The installed controller supplies its fixed archive policy and enrolled public key.
No inventory stored beside the source is trusted. Every strict execution verifies
the signature, hashes the retained archive and derives its inventory anew. Callers
hold D-446's actual work lock throughout verification and child execution; this
module does not grant execution, schedule jobs or establish environment identity.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile

from candidate_signing import verify_manifest_signature

PROOF = '.rosy-source-proof'
MEMBERS = {'release.json': 65536, 'release.json.sig': 16384, 'READY': 128}


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)


def _canonical(value):
    path = Path(value).absolute()
    if '..' in path.parts:
        raise ValueError('source path traversal refused')
    return path


@contextmanager
def _directory(path):
    """Pin and recheck every ancestor without following a directory link."""
    path = _canonical(path)
    descriptors, ancestry = [], []
    try:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        parent = os.open(path.anchor, flags)
        descriptors.append(parent)
        for name in path.parts[1:]:
            child = os.open(name, flags, dir_fd=parent)
            descriptors.append(child)
            ancestry.append((parent, name, child))
            parent = child
        yield parent
        for ancestor, name, child in ancestry:
            current = os.stat(name, dir_fd=ancestor, follow_symlinks=False)
            pinned = os.fstat(child)
            if (current.st_dev, current.st_ino, current.st_mode) != (pinned.st_dev, pinned.st_ino, pinned.st_mode):
                raise ValueError('source directory changed')
    except OSError as exc:
        raise ValueError('source directory unavailable or linked') from exc
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


@contextmanager
def _file(path, maximum):
    path = _canonical(path)
    # Build/sign tooling also runs on Windows; strict execution uses POSIX locks.
    if os.name != 'posix':
        try:
            if any(parent.is_symlink() for parent in (path, *path.parents)):
                raise ValueError('source file ancestry is linked')
            with path.open('rb') as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 <= before.st_size <= maximum:
                    raise ValueError('source requires bounded unlinked regular files')
                yield stream, before
                if _identity(before) != _identity(path.lstat()) or _identity(before) != _identity(os.fstat(stream.fileno())):
                    raise ValueError('source file changed during verification')
        except OSError as exc:
            raise ValueError('source file unavailable or linked') from exc
        return
    with _directory(path.parent) as parent:
        try:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            with os.fdopen(fd, 'rb') as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 <= before.st_size <= maximum:
                    raise ValueError('source requires bounded unlinked regular files')
                yield stream, before
                if (_identity(before) != _identity(os.fstat(stream.fileno()))
                        or _identity(before) != _identity(os.stat(path.name, dir_fd=parent, follow_symlinks=False))):
                    raise ValueError('source file changed during verification')
        except OSError as exc:
            raise ValueError('source file unavailable or linked') from exc


def _read(path, maximum):
    with _file(path, maximum) as (stream, _):
        raw = stream.read(maximum + 1)
        if len(raw) > maximum:
            raise ValueError('source file exceeds limit')
        return raw


def _hash(stream, maximum):
    digest, size = hashlib.sha256(), 0
    for block in iter(lambda: stream.read(min(1024 ** 2, maximum + 1 - size)), b''):
        size += len(block)
        if size > maximum:
            raise ValueError('source bytes exceed limit')
        digest.update(block)
    return digest.hexdigest(), size


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('duplicate source manifest field')
        result[key] = value
    return result


def _manifest(raw, signature, ready, *, key_id, public_key):
    if ready.decode('ascii').strip() != hashlib.sha256(raw).hexdigest():
        raise ValueError('candidate is not complete')
    verify_manifest_signature(raw, signature, trusted_key_id=key_id, public_key=Path(public_key))
    value = json.loads(raw, object_pairs_hook=_pairs)
    if (not isinstance(value, dict) or set(value) != {'schema', 'source_commit', 'sequence',
            'environment_sha256', 'archive_sha256'} or value['schema'] != 'rosy-model-code/1'):
        raise ValueError('wrong model-code manifest')
    if type(value['sequence']) is not int or not 0 < value['sequence'] < 2**63:
        raise ValueError('invalid sequence')
    for key, length in (('source_commit', 40), ('environment_sha256', 64), ('archive_sha256', 64)):
        if not isinstance(value[key], str) or re.fullmatch(f'[0-9a-f]{{{length}}}', value[key]) is None:
            raise ValueError('invalid manifest digest')
    return value


def read_candidate(folder, *, key_id, public_key, limit):
    folder = Path(folder)
    raw = {name: _read(folder / name, maximum) for name, maximum in MEMBERS.items()}
    with _file(folder / 'code.tar', limit):
        pass
    return _manifest(raw['release.json'], raw['release.json.sig'], raw['READY'],
                     key_id=key_id, public_key=public_key)


def _inventory(tar, policy):
    """Validate the same source-only archive policy for extraction and readback."""
    entries = tar.getmembers()
    if len(entries) > 10000:
        raise ValueError('too many archive members')
    files, directories, seen, total = {}, set(), set(), 0
    prefixes = policy['prefixes']
    ancestors = {str(p) for prefix in prefixes for p in PurePosixPath(prefix).parents}
    for item in entries:
        name = item.name.rstrip('/')
        path = PurePosixPath(name)
        if '\\' in name or path.is_absolute() or '..' in path.parts or str(path) != name or not name:
            raise ValueError('unsafe archive path')
        if name in seen:
            raise ValueError('duplicate archive member')
        seen.add(name)
        ancestor = item.isdir() and (name in ancestors or any(name == prefix.rstrip('/') for prefix in prefixes))
        if not ancestor and (not any(name == prefix or (prefix.endswith('/') and name.startswith(prefix))
                                    for prefix in prefixes) or not (item.isfile() or item.isdir())):
            raise ValueError('archive must contain only approved model-code dependencies, without links')
        if set(path.parts) & set(policy['forbidden']) or any(part.startswith('.env') for part in path.parts):
            raise ValueError('persistent data or secrets in code archive')
        total += item.size
        if item.size < 0 or total > policy['limit']:
            raise ValueError('expanded archive too large')
        directories.update(str(parent) for parent in path.parents if str(parent) != '.')
        if item.isdir():
            directories.add(name)
        else:
            with tar.extractfile(item) as stream:
                digest, size = _hash(stream, item.size)
            if size != item.size:
                raise ValueError('truncated archive file')
            files[name] = dict(sha256=digest, bytes=size, mode=0o444)
    for required in policy['required']:
        if required not in files:
            raise ValueError('missing model-code entry point or dependency')
    for trigger, required, error in policy['conditional']:
        if trigger in files and not all(name in files for name in required):
            raise ValueError(error)
    return files, directories


def unpack(archive, dest, *, policy):
    dest = Path(dest)
    try:
        with _file(archive, policy['limit']) as (stream, _), tarfile.open(fileobj=stream, mode='r:') as tar:
            files, directories = _inventory(tar, policy)
            for name in sorted(directories):
                (dest / name).mkdir(parents=True, exist_ok=True)
            for name in files:
                target = dest / name
                with tar.extractfile(name) as source, target.open('xb') as output:
                    for block in iter(lambda: source.read(1024 ** 2), b''):
                        output.write(block)
                    if os.name == 'posix':
                        os.fchmod(output.fileno(), 0o444)
                    output.flush()
                    os.fsync(output.fileno())
    except tarfile.TarError as exc:
        raise ValueError('invalid source archive') from exc


def retain_proof(folder, source, *, expected_manifest, key_id, public_key, limit):
    """Stage proof inside source so the existing rename publishes both atomically."""
    folder, source = Path(folder), Path(source)
    proof = source / PROOF
    proof.mkdir(mode=0o700)
    for name, maximum in {**MEMBERS, 'code.tar': limit}.items():
        with _file(folder / name, maximum) as (input_file, _), (proof / name).open('xb') as output:
            copied = 0
            for block in iter(lambda: input_file.read(min(1024 ** 2, maximum + 1 - copied)), b''):
                copied += len(block)
                if copied > maximum:
                    raise ValueError('source proof exceeds limit')
                output.write(block)
            if os.name == 'posix':
                os.fchmod(output.fileno(), 0o444)
            output.flush()
            os.fsync(output.fileno())
    actual = read_candidate(proof, key_id=key_id, public_key=public_key, limit=limit)
    with _file(proof / 'code.tar', limit) as (stream, _):
        archive_digest, _ = _hash(stream, limit)
    if actual != expected_manifest or archive_digest != actual['archive_sha256']:
        raise ValueError('retained source proof differs from selected release')
    # Extraction fsynced all files; sync every directory before the release rename.
    if os.name == 'posix':
        for parent, _, _ in os.walk(source, followlinks=False, topdown=False):
            with _directory(Path(parent)) as fd:
                os.fsync(fd)


def validate_expectation(value):
    if not isinstance(value, dict) or set(value) != {'source_commit', 'manifest_sha256', 'environment_sha256'}:
        raise ValueError('source expectation requires exact signed pins')
    for name, length in (('source_commit', 40), ('manifest_sha256', 64), ('environment_sha256', 64)):
        if not isinstance(value[name], str) or re.fullmatch(f'[0-9a-f]{{{length}}}', value[name]) is None:
            raise ValueError('source expectation requires full lowercase digests')
    return dict(value)


def _actual_tree(source, expected_files, expected_dirs, *, limit, data_root):
    files, directories, pending = {}, set(), [source]
    while pending:
        folder = pending.pop()
        with _directory(folder) as fd:
            for name in sorted(os.listdir(fd)):
                path = folder / name
                relative = path.relative_to(source).as_posix()
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if relative == PROOF:
                    if not stat.S_ISDIR(info.st_mode):
                        raise ValueError('linked source proof refused')
                    continue
                if relative == 'data':
                    if (data_root is None or not stat.S_ISLNK(info.st_mode)
                            or path.resolve(strict=True) != data_root
                            or data_root.is_relative_to(source.parent)):
                        raise ValueError('source data link differs from enrollment')
                    continue
                if stat.S_ISDIR(info.st_mode):
                    if relative not in expected_dirs:
                        raise ValueError('extra or shadow source directory')
                    directories.add(relative)
                    pending.append(path)
                elif stat.S_ISREG(info.st_mode):
                    if relative not in expected_files:
                        raise ValueError('extra or shadow source file')
                    with _file(path, limit) as (stream, pinned):
                        digest, size = _hash(stream, limit)
                        files[relative] = dict(sha256=digest, bytes=size, mode=stat.S_IMODE(pinned.st_mode))
                else:
                    raise ValueError('linked or special source member')
    if files != expected_files or directories != expected_dirs:
        raise ValueError('installed source differs from signed archive')


def verify_source(source, *, key_id, public_key, policy, data_root=None):
    """Freshly verify installed source; caller keeps work_lock through execution."""
    source = _canonical(source)
    proof = source / PROOF
    if data_root is not None:
        data_root = Path(data_root).resolve(strict=True)
    with _directory(source), _directory(proof) as proof_fd:
        if set(os.listdir(proof_fd)) != set(MEMBERS) | {'code.tar'}:
            raise ValueError('source proof requires exact signed members')
        raw = {name: _read(proof / name, maximum) for name, maximum in MEMBERS.items()}
        manifest = _manifest(raw['release.json'], raw['release.json.sig'], raw['READY'],
                             key_id=key_id, public_key=public_key)
        try:
            with _file(proof / 'code.tar', policy['limit']) as (stream, _):
                archive_digest, _ = _hash(stream, policy['limit'])
                if archive_digest != manifest['archive_sha256']:
                    raise ValueError('retained archive digest differs')
                stream.seek(0)
                with tarfile.open(fileobj=stream, mode='r:') as tar:
                    files, directories = _inventory(tar, policy)
        except tarfile.TarError as exc:
            raise ValueError('invalid retained source archive') from exc
        if any(Path(name).suffix in ('.pyc', '.pyo') or '__pycache__' in Path(name).parts for name in (*files, *directories)):
            raise ValueError('bytecode cannot establish source closure')
        _actual_tree(source, files, directories, limit=policy['limit'], data_root=data_root)
        inventory = json.dumps(dict(files=files, directories=sorted(directories)),
                               sort_keys=True, separators=(',', ':')).encode()
        return dict(schema='rosy.model-code-source/1', sequence=manifest['sequence'],
                    source_commit=manifest['source_commit'], environment_sha256=manifest['environment_sha256'],
                    manifest_sha256=hashlib.sha256(raw['release.json']).hexdigest(),
                    archive_sha256=archive_digest, inventory_sha256=hashlib.sha256(inventory).hexdigest())
