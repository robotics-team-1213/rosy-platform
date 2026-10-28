"""Read-only A/B admission for root services, including private mount namespaces."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid

DESCRIPTOR = "etc/rosy/os-slot.json"
COMMON = "var/lib/rosy-device"
READY = "run/rosy-os-state/ready.json"
TLS_PENDING = COMMON + "/state/tls-pending.json"
LAYOUT_FIELDS = {"schema_version", "state_schema", "slot", "root_partuuid", "data_partuuid", "provision_partuuid"}
MOUNTS = (("root", "/", "ext4"), ("data", "/" + COMMON, "ext4"),
          ("provision", "/run/rosy-provision-boot", "vfat"))
SHARED_BINDINGS = {
    "var/lib/rosy/provisioning": "/provisioning", "var/lib/rosy/core": "/core",
    "etc/NetworkManager/system-connections": "/network/system-connections",
    "var/lib/rosy/ssh": "/ssh", "home/rosy/.ssh": "/operator-ssh",
    "etc/rosy/tls": "/tls",
    "var/lib/tailscale": "/tailscale/machine",
    "var/lib/rosy/maps": "/maps", "var/lib/rosy/models": "/models",
    "var/lib/rosy/pilot-recordings": "/pilot-recordings",
    "var/lib/rosy/calibration": "/calibration",
}


class StateError(ValueError):
    pass


def _path(root: Path, relative: str) -> Path:
    target = root
    for component in relative.split("/"):
        target /= component
        if target.is_symlink():
            raise ValueError("symlink in managed state path")
        if target.is_dir():
            info = target.stat()
            if info.st_uid != root.stat().st_uid or info.st_mode & 0o022:
                raise ValueError("managed state directory owner or permissions differ")
    return target


def _read(path: Path, limit: int, owner: int | None = None) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("state input is not a bounded regular file")
        if owner is not None and (info.st_uid != owner or info.st_mode & 0o022):
            raise ValueError("state owner or permissions differ")
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("state input exceeds size limit")
    return raw


def _sysfs_read(root: Path, path: Path) -> bytes:
    path = path.resolve(strict=True)
    if not path.is_relative_to((root / "sys").resolve(strict=True)):
        raise ValueError("kernel attribute escapes sysfs")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != root.stat().st_uid or info.st_mode & 0o022:
            raise ValueError("kernel attribute type or ownership differs")
        # sysfs reports PAGE_SIZE for short text attributes; bound actual bytes, not i_size.
        raw = handle.read(65)
    if len(raw) > 64:
        raise ValueError("kernel attribute exceeds size limit")
    return raw


def _pairs(items):
    value = {}
    for key, item in items:
        if key in value:
            raise ValueError("duplicate state field")
        value[key] = item
    return value


def _object(raw: bytes, fields: set[str], *, schema_versions=(1,)) -> dict:
    value = json.loads(raw, object_pairs_hook=_pairs)
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("state fields differ")
    if type(value["schema_version"]) is not int or value["schema_version"] not in schema_versions:
        raise ValueError("unsupported state schema_version")
    if "state_schema" in value and (type(value["state_schema"]) is not int or value["state_schema"] != 1):
        raise ValueError("unsupported shared state schema")
    return value


def _guid(value) -> str:
    if not isinstance(value, str):
        raise ValueError("invalid partition/generation GUID")
    parsed = uuid.UUID(value)
    if not parsed.int or str(parsed) != value:
        raise ValueError("noncanonical or zero GUID")
    return value


def _digest(value) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("invalid state digest")
    return value


def _layout(root: Path) -> tuple[dict, str] | None:
    cmdline = root / "proc/cmdline"
    words = _read(cmdline, 16 * 1024).decode("ascii").split() if cmdline.exists() else []
    markers = [word for word in words if word.startswith("rosy.os_layout=")]
    descriptor = _path(root, DESCRIPTOR)
    if not markers and not descriptor.exists():
        return None
    if markers not in (["rosy.os_layout=ab-v1"], ["rosy.os_layout=ab-v2"]):
        raise ValueError("A/B kernel marker missing, ambiguous or unsupported")
    raw = _read(descriptor, 8192, root.stat().st_uid)
    layout = _object(raw, LAYOUT_FIELDS, schema_versions=(1, 2))
    if markers != [f"rosy.os_layout=ab-v{layout['schema_version']}"]:
        raise ValueError("kernel marker differs from slot protocol")
    if layout["slot"] not in ("a", "b"):
        raise ValueError("invalid A/B slot")
    guids = [_guid(layout[key]) for key in ("root_partuuid", "data_partuuid", "provision_partuuid")]
    if len(set(guids)) != 3:
        raise ValueError("duplicate partition GUID")
    if [word for word in words if word.startswith("root=")] != ["root=PARTUUID=" + guids[0]]:
        raise ValueError("kernel root differs from slot descriptor")
    return layout, hashlib.sha256(raw).hexdigest()


def _unescape(value: str) -> str:
    if re.search(r"\\(?!040|011|012|134)", value):
        raise ValueError("unsupported mountinfo escape")
    return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), value)


def _mount_table(root: Path, relative: str) -> dict[str, list[dict]]:
    result = {}
    raw = _read(root / relative, 4 * 1024 * 1024).decode("utf-8")
    for line in raw.splitlines():
        left, separator, right = line.partition(" - ")
        fields, superblock = left.split(), right.split()
        if not separator or len(fields) < 6 or len(superblock) < 3:
            raise ValueError("invalid mountinfo record")
        if not re.fullmatch(r"[0-9]+:[0-9]+", fields[2]) or not fields[0].isdigit():
            raise ValueError("invalid mount identity")
        point = _unescape(fields[4])
        row = dict(mount_id=int(fields[0]), device=fields[2], root=_unescape(fields[3]), mountpoint=point,
                   filesystem=superblock[0], options=sorted(set(fields[5].split(","))),
                   super_options=sorted(set(superblock[2].split(","))))
        result.setdefault(point, []).append(row)
    return result


def _one_mount(table: dict, point: str, filesystem: str, writable: bool) -> dict:
    rows = table.get(point, [])
    if len(rows) != 1:
        raise ValueError("required mount missing or ambiguous")
    row = rows[0]
    if row["root"] != "/" or row["filesystem"] != filesystem:
        raise ValueError("mount root/subpath or filesystem differs")
    if "rw" not in row["super_options"] or "ro" in row["super_options"]:
        raise ValueError("filesystem is read-only")
    if writable and ("rw" not in row["options"] or "ro" in row["options"]):
        raise ValueError("host mount is read-only")
    return row


def mount_facts(root: Path, layout: dict) -> list[dict]:
    """PID1 is the host view; the caller may have ProtectSystem/PrivateDevices."""
    host = _mount_table(root, "proc/1/mountinfo")
    local = _mount_table(root, "proc/self/mountinfo")
    # Preserve this proc-root magic-link traversal: realpath would return the
    # caller's private /dev after flattening the path back to an absolute name.
    devices = root / "proc/1/root/dev/disk/by-partuuid"
    host_dev, local_dev = host.get("/dev", []), local.get("/dev", [])
    if (len(host_dev) == len(local_dev) == 1 and host_dev[0]["filesystem"] == "devtmpfs"
            and host_dev[0]["root"] == "/"
            and all(host_dev[0][key] == local_dev[0][key] for key in ("device", "root", "filesystem"))):
        # Shared devtmpfs needs no ptrace access to PID1; PrivateDevices still uses the host view.
        info = (root / "dev").stat()
        if (not stat.S_ISDIR(info.st_mode)
                or f"{os.major(info.st_dev)}:{os.minor(info.st_dev)}" != host_dev[0]["device"]):
            raise ValueError("visible /dev mount differs from PID1 devtmpfs")
        devices = root / "dev/disk/by-partuuid"
    names = os.listdir(devices)
    if len(names) > 4096:
        raise ValueError("too many partition aliases")
    result = []
    identities = set()
    disk = None
    for role, point, filesystem in MOUNTS:
        actual = _one_mount(host, point, filesystem, True)
        visible = _one_mount(local, point, filesystem, False)
        if visible["device"] != actual["device"]:
            raise ValueError("caller and host mount device differ")
        mountpoint = root if point == "/" else _path(root, point.lstrip("/"))
        info = mountpoint.stat()
        if f"{os.major(info.st_dev)}:{os.minor(info.st_dev)}" != actual["device"]:
            raise ValueError("visible mountpoint device differs")
        guid = layout[role + "_partuuid"]
        if [name for name in names if name.lower() == guid] != [guid]:
            raise ValueError("partition alias missing or ambiguous")
        partition = os.stat(devices / guid)
        if not stat.S_ISBLK(partition.st_mode):
            raise ValueError("partition alias is not a block device")
        identity = f"{os.major(partition.st_rdev)}:{os.minor(partition.st_rdev)}"
        if identity != actual["device"] or identity in identities:
            raise ValueError("mounted PARTUUID differs or is duplicated")
        partition_dir = (root / "sys/dev/block" / identity).resolve(strict=True)
        if not partition_dir.is_relative_to(root / "sys"):
            raise ValueError("partition sysfs path escapes sysfs")
        number = _sysfs_read(root, partition_dir / "partition").decode("ascii").strip()
        expected = {"root": 4 if layout["slot"] == "a" else 5, "data": 6,
                    "provision": 1 if layout["schema_version"] == 2 else 2}[role]
        if number != str(expected):
            raise ValueError("partition role differs from A/B slot")
        if disk is not None and partition_dir.parent != disk:
            raise ValueError("slot partitions belong to different physical disks")
        disk = partition_dir.parent
        identities.add(identity)
        result.append(dict(role=role, **actual))
    return result


def shared_mount_facts(root: Path, layout: dict) -> list[dict]:
    """Exact directory binds, including caller-visible devices, before firstboot writes."""
    facts = mount_facts(root, layout)
    data_device = next(row["device"] for row in facts if row["role"] == "data")
    host = _mount_table(root, "proc/1/mountinfo")
    caller = _mount_table(root, "proc/self/mountinfo")
    for relative, subpath in SHARED_BINDINGS.items():
        point = "/" + relative
        views = []
        for table, writable in ((host, True), (caller, False)):
            rows = table.get(point, [])
            if len(rows) != 1:
                raise ValueError("shared directory mount missing or ambiguous")
            row = rows[0]
            if (row["device"] != data_device or row["root"] != subpath
                    or row["filesystem"] != "ext4"
                    or "rw" not in row["super_options"] or "ro" in row["super_options"]
                    or writable and ("rw" not in row["options"] or "ro" in row["options"])):
                raise ValueError("shared directory mount device/subpath/permissions differ")
            views.append(row)
        target = root
        for component in relative.split("/"):
            target /= component
            if target.is_symlink():
                raise ValueError("symlink in shared directory mount path")
        info = target.stat()
        if not stat.S_ISDIR(info.st_mode) or f"{os.major(info.st_dev)}:{os.minor(info.st_dev)}" != data_device:
            raise ValueError("visible shared directory device differs")
        facts.append(dict(role="shared:" + relative, **views[0]))
    return facts


def policy_directory(root: Path) -> Path:
    """Revalidate A/B admission on every policy operation; legacy is explicit."""
    try:
        loaded = _layout(root)
        if loaded is None:
            return root / "var/lib/rosy/updates"
        from os_state_ready import verify_ready
        verify_ready(root)
        policy = _path(root, COMMON + "/policy/updates")
        if not policy.is_dir():
            raise ValueError("shared policy directory missing")
        return policy
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise StateError(f"OS_STATE_HOLD: {exc}") from exc


def policy_file(root: Path, name: str) -> Path:
    directory = policy_directory(root)
    if directory == root / "var/lib/rosy/updates":
        return directory / name
    try:
        if name not in ("config.json", "hold.json"):
            raise ValueError("unsupported shared policy file")
        path = _path(root, COMMON + "/policy/updates/" + name)
        if path.exists():
            _read(path, 64 * 1024, root.stat().st_uid)
        elif name == "config.json":
            raise ValueError("committed shared updater config is missing")
        return path
    except (OSError, ValueError) as exc:
        raise StateError(f"OS_STATE_HOLD: {exc}") from exc
