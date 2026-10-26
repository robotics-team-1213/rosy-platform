"""Private bounded OS bundle cache; never unpack, write slots or remove unknown cache entries."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat

from auto_update_host import DISK_MARGIN_BYTES
from os_factory_release import PUBLIC_KEY
from os_state_io import _write_atomic
from os_state_layout import COMMON, _path, _read
from os_update_manifest import release_id, verify_metadata

STAGING = COMMON + "/os-update/staging"


def _directory(root, relative):
    path = _path(root, relative)
    path.mkdir(mode=0o700, exist_ok=True)
    if not path.is_dir() or stat.S_IMODE(path.stat().st_mode) != 0o700:
        raise ValueError("OS_STAGE: directory must be private")
    return path


def _file(root, path, mode, limit):
    info = path.stat()
    if info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != mode:
        raise ValueError("OS_STAGE: unsafe cached file")
    return _read(path, limit, root.stat().st_uid)


def _cached(root, path, expected):
    if not path.exists(): return False
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as handle:
        info = os.fstat(handle.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != root.stat().st_uid or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o400 or info.st_size != expected["size_bytes"]):
            raise ValueError("OS_STAGE: cached bundle size/mode differs")
        digest = hashlib.sha256()
        while chunk := handle.read(2 * 1024**2): digest.update(chunk)
        after = path.stat()
        if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns):
            raise ValueError("OS_STAGE: cached bundle changed")
    if digest.hexdigest() != expected["sha256"]:
        raise ValueError("OS_STAGE: cached bundle digest differs")
    return True


def _reclaim(root, staging, keep):
    """Caller holds OS lock with no pending writer; delete only fully recognized signed cache trees."""
    for entry in staging.iterdir():
        if entry.name == keep: continue
        try:
            release_id(entry.name)
            directory = _path(root, entry.relative_to(root).as_posix())
            if not directory.is_dir() or stat.S_IMODE(directory.stat().st_mode) != 0o700: continue
            raw = _file(root, directory / "os-update.json", 0o400, 16384)
            sig = _file(root, directory / "os-update.json.sig", 0o400, 512).decode("ascii").strip()
            metadata = verify_metadata(raw, sig, _path(root, PUBLIC_KEY))
            if metadata["release_id"] != directory.name: continue
            name = metadata["bundle"]["filename"]
            paths = list(directory.iterdir())
            if any(p.name not in {"os-update.json", "os-update.json.sig", name, name + ".part"} for p in paths): continue
            for path in paths:
                _path(root, path.relative_to(root).as_posix())
                mode = 0o600 if path.name.endswith(".part") else 0o400
                info = path.stat()
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != root.stat().st_uid or info.st_nlink != 1
                        or stat.S_IMODE(info.st_mode) != mode): raise ValueError("unsafe cache entry")
            for path in paths: path.unlink()
            directory.rmdir()
        except (OSError, ValueError, UnicodeError):
            continue  # Unknown or interrupted metadata is preserved for inspection.


def stage(root: Path, metadata: dict, raw: bytes, signature: str, url: str, *, host, http) -> Path:
    staging = _directory(root, STAGING)
    directory = _directory(root, STAGING + "/" + metadata["release_id"])
    expected = metadata["bundle"]
    allowed = {"os-update.json", "os-update.json.sig", expected["filename"], expected["filename"] + ".part"}
    if any(p.name not in allowed for p in directory.iterdir()):
        raise ValueError("OS_STAGE: unknown staging entry")
    for name, content in (("os-update.json", raw), ("os-update.json.sig", (signature + "\n").encode("ascii"))):
        target = _path(root, directory.relative_to(root).as_posix() + "/" + name)
        if target.exists():
            if _file(root, target, 0o400, 16384) != content:
                raise ValueError("OS_STAGE: immutable release metadata changed")
        else: _write_atomic(target, content, 0o400)
    target = _path(root, directory.relative_to(root).as_posix() + "/" + expected["filename"])
    cached = _cached(root, target, expected)
    need = DISK_MARGIN_BYTES + (0 if cached else expected["size_bytes"])
    if host.free_bytes(staging) < need:
        _reclaim(root, staging, metadata["release_id"])
    if host.free_bytes(staging) < need:
        raise ValueError("OS_STAGE_DISK_LOW: bundle and safety margin do not fit")
    if cached: return target
    part = _path(root, target.relative_to(root).as_posix() + ".part")
    if part.exists():
        info = part.stat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != root.stat().st_uid
                or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600):
            raise ValueError("OS_STAGE: unknown partial file")
        part.unlink()
    descriptor = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    os.close(descriptor)
    try:
        digest = http.download(url, part, expected["size_bytes"])
        if part.stat().st_size != expected["size_bytes"] or digest != expected["sha256"]:
            raise ValueError("OS_STAGE: downloaded bundle size/digest differs")
        part.chmod(0o400)
        os.replace(part, target)
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)
        _cached(root, target, expected)
        return target
    finally:
        part.unlink(missing_ok=True)
