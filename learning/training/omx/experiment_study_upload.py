"""Bounded regular-file writes for an immutable uploaded-study manifest."""
import base64
import os
from pathlib import Path, PurePosixPath
import shutil
import stat

from experiment_io import sync_directory

MARGIN = 1024**3


def source_root(center_root, uid, *, create=False):
    current = Path(center_root)
    for part in ('studies', uid, 'source'):
        current = current/part
        if current.is_symlink():
            raise ValueError('regular owned study directory required')
        if create:
            current.mkdir(exist_ok=True)
        if current.exists() and not current.is_dir():
            raise ValueError('regular owned study directory required')
    if not current.resolve().is_relative_to(Path(center_root).resolve()):
        raise ValueError('study escaped owned storage')
    return current


def path(root, name, *, create=False):
    relative = PurePosixPath(name)
    if (not isinstance(name, str) or '\\' in name or ':' in name or relative.is_absolute()
            or str(relative) != name or '..' in relative.parts):
        raise ValueError('relative manifest path required')
    current = root
    for part in relative.parts[:-1]:
        current = current/part
        if current.is_symlink() or (current.exists() and not current.is_dir()):
            raise ValueError('regular study parent required')
        if create:
            current.mkdir(exist_ok=True)
    result = current/relative.name
    if (result.is_symlink() or not result.resolve().is_relative_to(root.resolve())
            or (result.exists() and not stat.S_ISREG(result.stat().st_mode))):
        raise ValueError('regular study file required')
    return result


def status(root, files):
    result = []
    for item in files:
        file = path(root, item['name'])
        size = file.stat().st_size if file.exists() else 0
        if size > item['size']:
            raise ValueError('uploaded file size differs from manifest')
        result.append(dict(item, offset=size))
    return result


def write(root, item, offset, encoded):
    if type(offset) is not int or not 0 <= offset <= item['size']:
        raise ValueError('nonnegative manifest offset required')
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError('base64 upload bytes required') from exc
    if not 0 < len(raw) <= 256*1024 or offset+len(raw) > item['size']:
        raise ValueError('upload chunk exceeds manifest or 256 KiB limit')
    file = path(root, item['name'], create=True)
    size = file.stat().st_size if file.exists() else 0
    if offset > size or size > item['size']:
        raise ValueError('upload offset differs from confirmed bytes')
    overlap = min(len(raw), size-offset)
    if overlap:
        with file.open('rb') as stream:
            stream.seek(offset)
            if stream.read(overlap) != raw[:overlap]:
                raise ValueError('upload retry bytes differ')
    if shutil.disk_usage(root).free < len(raw)-overlap+MARGIN:
        raise ValueError('study upload requires 1 GiB of remaining free space')
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(file, flags, 0o600)
    with os.fdopen(fd, 'ab') as stream:
        if overlap < len(raw):
            stream.write(raw[overlap:])
        stream.flush()
        os.fsync(stream.fileno())
    sync_directory(file.parent)
    sync_directory(root)
    return offset+len(raw)
