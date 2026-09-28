#!/usr/bin/env python3
"""Restore a powered-off Pinky card to no-drive on a Linux ext4 mount.

Inspection is read-only.  Applying requires an external backup directory and
exact identity/release arguments; it never mounts, formats, or powers a card.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile


KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")
RELEASE = re.compile(r"^[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]{3}$")
UID = re.compile(r"^[0-9a-f-]{36}$")


def plain_file(root: Path, relative: str) -> Path:
    current = root
    for part in relative.split("/"):
        current = current / part
        mode = current.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise ValueError(f"symlink in card path: {relative}")
    if not stat.S_ISREG(current.stat().st_mode):
        raise ValueError(f"not a regular card file: {relative}")
    return current


def card_root(path: str) -> Path:
    root = Path(path).absolute()
    if not sys.platform.startswith("linux") or os.geteuid() != 0:
        raise ValueError("use root on a Linux host")
    if root == Path("/") or root.is_symlink() or not os.path.ismount(root):
        raise ValueError("root must be a separate mounted card partition")
    probe = subprocess.run(
        ["findmnt", "-n", "--mountpoint", str(root), "-o", "FSTYPE,SOURCE"],
        capture_output=True, text=True, check=True,
    )
    fields = probe.stdout.strip().split(maxsplit=1)
    if len(fields) != 2 or fields[0] != "ext4" or not fields[1].startswith("/dev/"):
        raise ValueError("root must be a directly mounted ext4 block device")
    return root


def parse_env(raw: bytes) -> dict[str, str]:
    text = raw.decode("utf-8")
    result = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not KEY.fullmatch(key) or key in result:
            raise ValueError("runtime.env contains malformed or duplicate keys")
        result[key] = value
    return result


def inspect(root: Path) -> tuple[Path, bytes, dict, dict]:
    env_path = plain_file(root, "etc/rosy/runtime.env")
    complete_path = plain_file(root, "var/lib/rosy/provisioning/complete.json")
    raw = env_path.read_bytes()
    env = parse_env(raw)
    complete = json.loads(complete_path.read_text(encoding="utf-8"))
    if complete.get("schema_version") != 1:
        raise ValueError("unknown provisioning record")
    active_link = root / "opt/rosy/current"
    if not active_link.is_symlink():
        raise ValueError("active release link is missing")
    active_target = os.readlink(active_link)
    active_release = active_target.removeprefix("/opt/rosy/releases/")
    if active_target != f"/opt/rosy/releases/{active_release}" or not RELEASE.fullmatch(active_release):
        raise ValueError("active release link is unsafe")
    release_path = root / "opt/rosy/releases" / active_release
    if release_path.is_symlink() or not release_path.is_dir():
        raise ValueError("active release directory is missing or linked")
    number = complete.get("dds", {}).get("robot_number")
    identity = {
        "device_uid": complete.get("device_uid"),
        "device_name": complete.get("device_name"),
        "robot_number": number,
        "provisioned_release_id": complete.get("release_id"),
        "release_id": active_release,
    }
    expected = {
        "ROSY_DEVICE_UID": identity["device_uid"],
        "ROSY_DEVICE_NAME": identity["device_name"],
        "ROSY_ROBOT_NUMBER": str(number),
    }
    if any(env.get(key) != value for key, value in expected.items()):
        raise ValueError("runtime.env disagrees with provisioning identity")
    if (not UID.fullmatch(str(identity["device_uid"]))
            or not RELEASE.fullmatch(str(identity["provisioned_release_id"]))):
        raise ValueError("invalid card identity or release")
    return env_path, raw, env, identity


def apply(root: Path, backup_dir: Path, args, path: Path, raw: bytes, env: dict, identity: dict) -> dict:
    if (identity["device_uid"], identity["device_name"], identity["robot_number"], identity["release_id"]) != (
        args.device_uid, args.device_name, args.robot_number, args.release_id,
    ):
        raise ValueError("supplied identity/release does not match card readback")
    if env.get("ROSY_RUNTIME_MODE") != "motor" or env.get("ROSY_IO_DRIVE_ENABLED") != "true":
        raise ValueError("expected the specific persistent motor/drive=true state")
    if not backup_dir.is_dir() or backup_dir.is_symlink() or backup_dir.stat().st_dev == root.stat().st_dev:
        raise ValueError("backup directory must exist on a different filesystem")
    if path.stat().st_nlink != 1:
        raise ValueError("runtime.env must not have hard links")
    backup = backup_dir / f"runtime-before-{identity['device_uid']}.env"
    receipt = backup_dir / f"runtime-recovery-{identity['device_uid']}.json"
    if backup.exists() or receipt.exists():
        raise ValueError("backup or receipt already exists; refusing overwrite")
    before_hash = hashlib.sha256(raw).hexdigest()
    lines = raw.decode("utf-8").splitlines(keepends=True)
    updated = []
    for line in lines:
        if line.startswith("ROSY_RUNTIME_MODE="):
            updated.append("ROSY_RUNTIME_MODE=core\n")
        elif not line.startswith("ROSY_IO_DRIVE_ENABLED="):
            updated.append(line)
    after = "".join(updated).encode("utf-8")
    if parse_env(after).get("ROSY_RUNTIME_MODE") != "core" or "ROSY_IO_DRIVE_ENABLED" in parse_env(after):
        raise ValueError("no-drive transformation failed")
    backup_fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(backup_fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    if hashlib.sha256(backup.read_bytes()).hexdigest() != before_hash:
        raise ValueError("backup readback failed; card was not changed")
    fd, temporary = tempfile.mkstemp(prefix=".runtime-no-drive-", dir=path.parent)
    try:
        os.fchmod(fd, stat.S_IMODE(path.stat().st_mode))
        os.fchown(fd, path.stat().st_uid, path.stat().st_gid)
        with os.fdopen(fd, "wb") as stream:
            stream.write(after)
            stream.flush()
            os.fsync(stream.fileno())
        if path.read_bytes() != raw:
            raise ValueError("card changed during recovery")
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    if path.read_bytes() != after:
        raise ValueError("card write readback failed")
    result = {**identity, "state": "NO_DRIVE_RESTORED_ON_CARD", "before_sha256": before_hash,
              "after_sha256": hashlib.sha256(after).hexdigest(), "backup": str(backup)}
    receipt_fd = os.open(receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(receipt_fd, "w", encoding="utf-8") as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="mounted ext4 card root, never /")
    parser.add_argument("--apply", action="store_true", help="write no-drive only after exact identity confirmation")
    parser.add_argument("--backup-dir", type=Path, help="existing directory on another filesystem")
    parser.add_argument("--device-uid")
    parser.add_argument("--device-name")
    parser.add_argument("--robot-number", type=int)
    parser.add_argument("--release-id")
    args = parser.parse_args()
    try:
        root = card_root(args.root)
        path, raw, env, identity = inspect(root)
        result = {**identity, "runtime_mode": env.get("ROSY_RUNTIME_MODE"),
                  "drive_enabled": env.get("ROSY_IO_DRIVE_ENABLED", "absent"),
                  "runtime_sha256": hashlib.sha256(raw).hexdigest(), "changed": False}
        if args.apply:
            if not args.backup_dir or not all((args.device_uid, args.device_name,
                                               args.robot_number is not None, args.release_id)):
                raise ValueError("--apply needs backup-dir and all exact identity/release fields")
            result = apply(root, args.backup_dir, args, path, raw, env, identity)
            result["changed"] = True
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"HOLD: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
