"""OS-owned projection readback and boot-local admission receipts."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat

from os_state_config import common_lock
from os_state_firstboot import _hold
from os_state_files import ROOT_FILES, _timezone, validate_projection
from os_state_io import SERIAL, _json_atomic
from os_state_layout import (
    READY, TLS_PENDING, _guid, _layout, _object, _path, _read, shared_mount_facts,
)

RECEIPT_FIELDS = {"schema_version", "phase", "boot_id", "slot", "descriptor_sha256",
                  "generation", "projection_sha256", "mounts"}


def projection_facts(root: Path, shared) -> dict:
    """Read only, under the common configuration lock; never repair a root here."""
    if shared is None or not shared.current.exists():
        raise ValueError("projection requires a committed A/B device")
    if _path(root, TLS_PENDING).exists():
        raise ValueError("TLS transaction pending")
    if _path(root, "var/lib/rosy/provisioning/new-device-setup.json").exists():
        raise ValueError("new-device registration pending")
    loaded = _layout(root)
    layout, descriptor_sha = loaded
    pointer, manifest, values = shared._generation()
    shared._committed()
    owner = root.stat().st_uid
    live = _read(root / "proc/device-tree/serial-number", 128, owner).decode("ascii").strip("\0\r\n ").lower()
    if not SERIAL.fullmatch(live) or live != manifest["hardware_serial"]:
        raise ValueError("projection hardware binding differs")
    identity = json.loads(values["etc/rosy/device-identity.json"])
    hostname = _read(root / "proc/sys/kernel/hostname", 256, owner).decode("ascii").strip()
    if hostname != identity["hostname"]:
        raise ValueError("live hostname differs from canonical identity")
    for name, target in validate_projection(root, values).items():
        expected = values[name]
        if expected is None:
            if target.exists():
                raise ValueError("deleted canonical setting is present")
            continue
        info = target.stat()
        if (info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != ROOT_FILES[name]
                or _read(target, 64 * 1024, owner) != expected):
            raise ValueError("root setting differs from canonical projection")
    timezone = _timezone(root, values["etc/rosy/timezone.json"])
    localtime = _path(root, "etc") / "localtime"
    info = localtime.lstat()
    if (not stat.S_ISLNK(info.st_mode) or info.st_uid != owner
            or os.readlink(localtime) != "/usr/share/zoneinfo/" + timezone):
        raise ValueError("localtime differs from canonical projection")
    zonefile = _path(root, "etc/timezone")
    info = zonefile.stat()
    if (info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o644
            or _read(zonefile, 256, owner) != (timezone + "\n").encode("utf-8")):
        raise ValueError("timezone differs from canonical projection")
    boot = _read(root / "proc/sys/kernel/random/boot_id", 128, owner).decode("ascii").strip()
    _guid(boot)
    return dict(schema_version=1, phase="PROJECTED", boot_id=boot, slot=layout["slot"],
                descriptor_sha256=descriptor_sha, generation=pointer["generation"],
                projection_sha256=pointer["manifest_sha256"], mounts=shared_mount_facts(root, layout))


@_hold
def publish_ready(root: Path) -> dict:
    root = Path(root).absolute()
    with common_lock(root) as shared:
        if shared is None:
            return {"schema_version": 1, "phase": "LEGACY"}
        report = projection_facts(root, shared)
        target = _path(root, READY)
        target.parent.mkdir(mode=0o700, exist_ok=True)
        _path(root, READY)
        _json_atomic(target, report, 0o600)
        return report


@_hold
def verify_ready(root: Path) -> dict:
    root = Path(root).absolute()
    with common_lock(root) as shared:
        expected = projection_facts(root, shared)
        path = _path(root, READY)
        info = path.stat()
        if info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError("projection receipt permissions differ")
        actual = _object(_read(path, 32768, root.stat().st_uid), RECEIPT_FIELDS)
        if actual != expected:
            raise ValueError("projection receipt differs from current root/boot/generation")
        return actual
