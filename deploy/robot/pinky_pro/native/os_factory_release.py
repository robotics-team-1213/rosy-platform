"""Bind each OS root to its own signed native factory without replaying enrollment."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import stat
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from os_state_config import common_lock
from os_state_firstboot import _hold
from os_state_io import _json_atomic, _write_atomic
from os_state_files import sync_directory
from os_state_layout import COMMON, _digest, _layout, _object, _path, _read
from os_state_ready import verify_ready_locked

DESCRIPTOR = "etc/rosy/os-factory-release.json"
PUBLIC_KEY = "etc/rosy/trusted-release-keys/rosy-release-2026-01.pem"
CAPSULE_FIELDS = {"schema_version", "release_id", "checksums_sha256", "public_key_sha256", "sha256sums_sig_b64"}
CHECKSUM_LIMIT = 16 * 1024 * 1024


def _binding(root):
    descriptor = _object(_read(_path(root, DESCRIPTOR), 8192, root.stat().st_uid),
                         {"schema_version", "release_id", "checksums_sha256"})
    release_id = descriptor["release_id"]
    if not isinstance(release_id, str) or not re.fullmatch(r"[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]{3}", release_id):
        raise ValueError("invalid OS factory release identity")
    _digest(descriptor["checksums_sha256"])
    release = _path(root, "opt/rosy/releases/" + release_id)
    sums = _read(release / "SHA256SUMS", CHECKSUM_LIMIT, root.stat().st_uid)
    if hashlib.sha256(sums).hexdigest() != descriptor["checksums_sha256"]:
        raise ValueError("OS factory checksum differs from its root descriptor")
    key = _path(root, PUBLIC_KEY)
    key_sha = hashlib.sha256(_read(key, 8192, root.stat().st_uid)).hexdigest()
    return descriptor, release, sums, key, key_sha


def _signature(value, sums, key):
    from signing import verify_signature
    if not isinstance(value, str):
        raise ValueError("factory signature is not text")
    raw = base64.b64decode(value, validate=True)
    if len(raw) != 64 or base64.b64encode(raw).decode("ascii") != value:
        raise ValueError("factory signature is not canonical Ed25519")
    if verify_signature(sums, value, key):
        raise ValueError("factory signature does not verify")


def _capsule(root, descriptor, key_sha):
    return _path(root, COMMON + "/state/factory-signatures/" + descriptor["checksums_sha256"] + "-" + key_sha + ".json")


def _read_capsule(root, path):
    info = path.stat()
    if info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600:
        raise ValueError("factory signature capsule permissions differ")
    return _object(_read(path, 8192, root.stat().st_uid), CAPSULE_FIELDS)


def cache_signature(root: Path, record: dict) -> None:
    """Firstboot holds the common lock and has already verified its native factory."""
    root = Path(root).absolute()
    descriptor, _, sums, key, key_sha = _binding(root)
    if set(record) != {"release_id", "sha256sums_sig_b64"} or record["release_id"] != descriptor["release_id"]:
        raise ValueError("factory signature belongs to a different release")
    _signature(record["sha256sums_sig_b64"], sums, key)
    capsule = dict(descriptor, public_key_sha256=key_sha, sha256sums_sig_b64=record["sha256sums_sig_b64"])
    path = _capsule(root, descriptor, key_sha)
    if not path.parent.exists():
        path.parent.mkdir(mode=0o700)
        sync_directory(path.parent.parent)
    if path.exists():
        if _read_capsule(root, path) != capsule:
            raise ValueError("existing factory signature capsule differs")
    else:
        _json_atomic(path, capsule, 0o600)


@_hold
def prepare_factory(root: Path) -> dict:
    from native_release import NativeReleaseManager
    root = Path(root).absolute()
    with common_lock(root) as shared:
        verify_ready_locked(root, shared)
        descriptor, release, sums, key, key_sha = _binding(root)
        manager = NativeReleaseManager(root=root, public_key=key)
        signature = _path(root, "opt/rosy/releases/" + descriptor["release_id"] + "/SHA256SUMS.sig")
        previous = _read(signature, 512, root.stat().st_uid) if signature.exists() else None
        try:
            manager.verify(descriptor["release_id"])
        except ValueError:
            record = _read_capsule(root, _capsule(root, descriptor, key_sha))
            if {k: record[k] for k in descriptor} != descriptor or record["public_key_sha256"] != key_sha:
                raise ValueError("factory signature capsule belongs to another root")
            _signature(record["sha256sums_sig_b64"], sums, key)
            _write_atomic(signature, record["sha256sums_sig_b64"] + "\n", 0o644)
            try:
                manager.verify(descriptor["release_id"])
            except BaseException:
                if previous is None:
                    signature.unlink()
                    sync_directory(signature.parent)
                else:
                    _write_atomic(signature, previous.decode("ascii"), 0o644)
                raise
        return dict(schema_version=1, phase="FACTORY_VERIFIED", release_id=descriptor["release_id"],
                    checksums_sha256=descriptor["checksums_sha256"])


def pinned_factory(root: Path) -> str | None:
    root = Path(root).absolute()
    return _binding(root)[0]["release_id"] if _layout(root) is not None else None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/"))
    args = parser.parse_args(argv)
    try:
        report = prepare_factory(args.root)
    except (OSError, ValueError, KeyError, TypeError):
        print(json.dumps({"schema_version": 1, "phase": "HOLD", "reason": "OS_FACTORY_HOLD"}))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
