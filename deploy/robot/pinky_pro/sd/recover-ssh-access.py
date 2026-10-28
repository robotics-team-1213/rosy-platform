#!/usr/bin/env python3
"""Restore an operator public key on a powered-off card, without reimaging it.

Run on a Linux host with a separately mounted ext4 card. Inspection is read-only;
--apply requires exact identity/release confirmation and a backup on another disk.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

SOURCE = Path(__file__).resolve().parent
sys.path.insert(0, str(SOURCE.parent / "native"))
sys.path.insert(0, str(SOURCE.parent / "release"))
from operator_keys import merge_operator_keys
from ssh_pairing import fingerprint, public_key

_spec = importlib.util.spec_from_file_location("rosy_offline_card", SOURCE / "recover-no-drive.py")
card = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(card)

KEYS = "home/rosy/.ssh/authorized_keys"
CONFIRM = ("device_uid", "device_name", "robot_number", "release_id")


def mounted_card(path: str) -> Path:
    root = card.card_root(path)
    if root.stat().st_dev == Path("/").stat().st_dev:
        raise ValueError("card must not share the running host's root filesystem")
    return root


def _keys(root: Path) -> tuple[bytes, os.stat_result | None]:
    rows = [line.split(":") for line in card.plain_file(root, "etc/passwd").read_text().splitlines()
            if line.startswith("rosy:")]
    if (len(rows) != 1 or len(rows[0]) != 7 or rows[0][5] != "/home/rosy"
            or rows[0][6] not in {"/bin/bash", "/usr/bin/bash", "/bin/sh", "/usr/bin/sh"}):
        raise ValueError("usable rosy operator account is missing; provision a verified card")
    uid, gid = int(rows[0][2]), int(rows[0][3])
    if uid <= 0 or gid <= 0:
        raise ValueError("invalid operator account identity")
    directory = root
    for part in ("", "home", "rosy", ".ssh"):
        directory /= part
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o022:
            raise ValueError("operator key directory is unsafe")
        search = (stat.S_IXUSR if info.st_uid == uid else
                  stat.S_IXGRP if info.st_gid == gid else stat.S_IXOTH)
        if not info.st_mode & search:
            raise ValueError("operator key directory cannot be traversed by the account")
        if part in {"rosy", ".ssh"} and (info.st_uid, info.st_gid) != (uid, gid):
            raise ValueError("operator key directory ownership differs from the account")
    try:
        path = card.plain_file(root, KEYS)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return b"", None
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 65536
                or info.st_mode & 0o022 or not info.st_mode & stat.S_IRUSR
                or (info.st_uid, info.st_gid) != (uid, gid)):
            raise ValueError("operator key file is unsafe")
        return stream.read(65537), info


def _contains(raw: bytes, key: str) -> bool:
    return any(line.split()[:2] == key.split() for line in raw.decode("utf-8").splitlines())


def inspect(root: Path, key: str) -> dict:
    key = public_key(key)
    _, _, _, identity = card.inspect(root)
    raw, _ = _keys(root)
    return dict(identity, account="rosy", public_key_fingerprint=fingerprint(key),
                authorized_keys_sha256=hashlib.sha256(raw).hexdigest(), key_present=_contains(raw, key),
                registration_pending=(root / "var/lib/rosy/provisioning/new-device-setup.json").exists(),
                changed=False)


def _save(path: Path, content: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _sync(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def apply(root: Path, key: str, backup_dir: Path, expected: dict) -> dict:
    key = public_key(key)
    result = inspect(root, key)
    if any(result[field] != expected.get(field) for field in CONFIRM):
        raise ValueError("supplied identity/release does not match card readback")
    if result["key_present"]:
        return dict(result, state="SSH_KEY_ALREADY_ON_CARD")
    if (not backup_dir.is_dir() or backup_dir.is_symlink()
            or backup_dir.stat().st_dev == root.stat().st_dev):
        raise ValueError("backup directory must exist on a different filesystem")
    raw, info = _keys(root)
    if hashlib.sha256(raw).hexdigest() != result["authorized_keys_sha256"]:
        raise ValueError("card changed during recovery")
    saved = Path(tempfile.mkdtemp(prefix="ssh-access-", dir=backup_dir))
    _save(saved / "authorized_keys.before", raw)
    metadata = {"existed": info is not None, "uid": info.st_uid if info else None,
                "gid": info.st_gid if info else None,
                "mode": stat.S_IMODE(info.st_mode) if info else None,
                "before_sha256": result["authorized_keys_sha256"]}
    _save(saved / "before.json", json.dumps(metadata, sort_keys=True).encode())
    _sync(saved)
    _sync(backup_dir)
    if (saved / "authorized_keys.before").read_bytes() != raw:
        raise ValueError("backup readback failed; card was not changed")
    merge_operator_keys(root, [key])
    after, _ = _keys(root)
    if not _contains(after, key):
        raise ValueError(f"key write readback failed; backup retained at {saved}")
    result.update(state="SSH_KEY_RESTORED_ON_CARD", changed=True, backup=str(saved),
                  before_sha256=result["authorized_keys_sha256"],
                  after_sha256=hashlib.sha256(after).hexdigest())
    _save(saved / "receipt.json", (json.dumps(result, sort_keys=True, indent=2) + "\n").encode())
    _sync(saved)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="separately mounted ext4 card root, never /")
    parser.add_argument("--public-key", required=True, type=Path, help="this PC's ed25519 .pub file, never its private key")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-dir", type=Path, help="existing directory on another filesystem")
    parser.add_argument("--device-uid")
    parser.add_argument("--device-name")
    parser.add_argument("--robot-number", type=int)
    parser.add_argument("--release-id")
    args = parser.parse_args(argv)
    try:
        root = mounted_card(args.root)
        with args.public_key.open("r", encoding="ascii") as stream:
            raw_key = stream.read(513)
        if len(raw_key) > 512:
            raise ValueError("operator public key file exceeds limit")
        key = public_key(raw_key.strip())
        if args.apply:
            expected = {field: getattr(args, field) for field in CONFIRM}
            if args.backup_dir is None or any(value is None for value in expected.values()):
                raise ValueError("--apply needs backup-dir and all exact identity/release fields")
            result = apply(root, key, args.backup_dir, expected)
        else:
            result = inspect(root, key)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"HOLD: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
