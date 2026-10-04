"""Copy a stopped Job to a new directory, adding only a review authority pin.

No fetch, training, approval or service transition. Existing receipt paths stay original.
Use migrate(source_folder, source_config_path, new_config_path, target_folder), or CLI.
The target appears only after a complete locked snapshot; an existing target is refused.
"""
import argparse
from contextlib import contextmanager
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
from urllib.parse import urlparse

from job_state import JobError


def _canonical(value):
    return json.dumps(value, sort_keys=True, allow_nan=False).encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise JobError("duplicate JSON field")
        result[key] = value
    return result


def _json(raw):
    return json.loads(raw, object_pairs_hook=_pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(JobError("nonfinite JSON")))


def _path(path):
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise JobError("symlink/junction path refused")
    return path


def _read(path):
    path = _path(path)
    before = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode):
        raise JobError("regular input file required")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise JobError("input file replaced")
        raw = stream.read()
    after = _path(path).stat(follow_symlinks=False)
    if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (
            before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns):
        raise JobError("input changed during read")
    return raw


def _configs(old, new):
    if not isinstance(old, dict) or not isinstance(new, dict) or "authority" in old:
        raise JobError("source must have no authority configuration")
    if set(new) != set(old) | {"authority"} or _canonical(old) != _canonical(
            {k: v for k, v in new.items() if k != "authority"}):
        raise JobError("only adding authority is permitted")
    authority = new["authority"]
    if not isinstance(authority, dict) or not isinstance(authority.get("workspace_id"), str) or not re.fullmatch(
            r"[a-f0-9]{32}", authority["workspace_id"]):
        raise JobError("typed pinned workspace_id required")
    if "trainer" in old:
        from learning_cycle import validate_config
        validate_config(old)
        if (set(authority) != {"path", "workspace_id", "max_age_s"}
                or not isinstance(authority["path"], str) or not authority["path"].strip()
                or not Path(authority["path"]).is_absolute()
                or type(authority["max_age_s"]) is not int or not 1 <= authority["max_age_s"] <= 3600):
            raise JobError("typed absolute current path and bounded max_age_s required")
    else:
        from review_bridge import peer_target
        if set(old) != {"source", "peer", "remote_reviews", "interval_s", "max_attempts"}:
            raise JobError("unsupported source Job configuration")
        peer_target(old)
        if (set(authority) != {"endpoint", "workspace_id"}
                or not isinstance(authority["endpoint"], str)):
            raise JobError("typed local authority endpoint required")
        endpoint = urlparse(authority["endpoint"])
        if (endpoint.scheme != "http" or endpoint.hostname not in ("127.0.0.1", "localhost", "::1")
                or endpoint.path != "/api/decisions" or endpoint.query or endpoint.fragment
                or endpoint.username or endpoint.password):
            raise JobError("local current-decisions endpoint required")
    if any(type(old[k]) is not int or old[k] < 1 for k in ("interval_s", "max_attempts")):
        raise JobError("positive interval and attempt limit required")


@contextmanager
def _locked(source):
    # Reuse Job's existing lock, without creating it or calling its state-saving enter.
    path = source / ".lock"
    info = _path(path).stat(follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode) or (os.name == "nt" and info.st_size < 1):
        raise JobError("existing regular Job lock required")
    with path.open("r+b") as stream:
        try:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                raise JobError("Job lock replaced")
            if os.name == "nt":
                import msvcrt
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise JobError("source job is already running") from exc
        yield (path, opened.st_dev, opened.st_ino)
        after = _path(path).stat(follow_symlinks=False)
        if (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino):
            raise JobError("Job lock replaced during migration")


def _files(root):
    files = []
    for path in root.rglob("*"):
        _path(path)
        mode = path.stat(follow_symlinks=False).st_mode
        if not stat.S_ISREG(mode) and not stat.S_ISDIR(mode):
            raise JobError("special source file refused")
        if stat.S_ISREG(mode) and path != root / ".lock":
            files.append(path.relative_to(root).as_posix())
    return sorted(files)


def _directories(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_dir())


def _sync_directory(path):
    if os.name != "nt":
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _copy_file(target, raw):
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _publish(staging, target):
    if os.name == "nt":
        os.rename(staging, target)  # Windows never replaces an existing destination.
    else:
        # Linux renameat2 supplies atomic no-replace directory publication.
        libc = ctypes.CDLL(None, use_errno=True)
        rename = getattr(libc, "renameat2", None)
        if rename is None:
            raise JobError("atomic no-replace publication unavailable")
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        if rename(-100, os.fsencode(staging), -100, os.fsencode(target), 1):
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code), str(target))


def migrate(source_folder, source_config_path, new_config_path, target_folder):
    """Return a receipt after preserving the entire stopped Job in a NEW folder.

    Original state/config and every copied byte are rechecked before publication.
    Only inputs/input_signature change; migration.json records provenance separately.
    An interrupted copy leaves no published target. External receipt paths stay fixed.
    """
    source, target = _path(source_folder), _path(target_folder)
    if not source.is_dir() or target.exists() or target.is_relative_to(source) or source.is_relative_to(target):
        raise JobError("separate absent target and existing source required")
    if not target.parent.is_dir():
        raise JobError("target parent must already exist")
    old_raw, new_raw = _read(source_config_path), _read(new_config_path)
    old, new = _json(old_raw), _json(new_raw)
    _configs(old, new)
    with _locked(source) as lock_identity:
        state_raw = _read(source / "state.json")
        state = _json(state_raw)
        if (not isinstance(state, dict) or state.get("schema") != "rosy.learning.job/1"
                or state.get("input_signature") != _sha(_canonical(old))
                or _canonical(state.get("inputs")) != _canonical(old)):
            raise JobError("source Job exact inputs/signature differ")
        if (source / "migration.json").exists():
            raise JobError("source already migrated")
        files = _files(source)
        directories = _directories(source)
        staging = Path(tempfile.mkdtemp(prefix=".review-migration-", dir=target.parent))
        try:
            hashes = {}
            for rel in directories:
                (staging / rel).mkdir(parents=True, exist_ok=True)
            for rel in files:
                raw = _read(source / rel)
                hashes[rel] = _sha(raw)
                if rel != "state.json":
                    _copy_file(staging / rel, raw)
            updated = dict(state, inputs=new, input_signature=_sha(_canonical(new)))
            _copy_file(staging / "state.json", _canonical(updated) + b"\n")
            result = {"schema": "rosy.learning.authority-migration/1", "source_folder": str(source),
                      "source_config_sha256": _sha(old_raw), "new_config_sha256": _sha(new_raw),
                      "source_state_sha256": _sha(state_raw), "new_input_signature": updated["input_signature"],
                      "source_files": hashes, "training_dataset_qualified": False}
            _copy_file(staging / "migration.json", _canonical(result) + b"\n")
            if (files != _files(source) or directories != _directories(source)
                    or _read(source / "state.json") != state_raw
                    or _read(source_config_path) != old_raw or _read(new_config_path) != new_raw
                    or any(_sha(_read(source / rel)) != digest for rel, digest in hashes.items())):
                raise JobError("source snapshot/config changed during migration")
            _path(target)
            if target.exists():
                raise JobError("target appeared during migration")
            lock_path, device, inode = lock_identity
            current_lock = _path(lock_path).stat(follow_symlinks=False)
            if (current_lock.st_dev, current_lock.st_ino) != (device, inode):
                raise JobError("Job lock replaced during migration")
            for folder in sorted((p for p in staging.rglob("*") if p.is_dir()),
                                 key=lambda p: len(p.parts), reverse=True):
                _sync_directory(folder)
            _sync_directory(staging)
            _publish(staging, target)
            _sync_directory(target.parent)
            return result
        finally:
            if staging.exists():
                shutil.rmtree(staging)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source_folder", "source_config", "new_config", "target_folder"):
        parser.add_argument(name)
    args = parser.parse_args()
    print(json.dumps(migrate(args.source_folder, args.source_config, args.new_config, args.target_folder),
                     sort_keys=True))


if __name__ == "__main__":
    main()
