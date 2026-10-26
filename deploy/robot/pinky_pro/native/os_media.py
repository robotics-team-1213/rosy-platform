"""Read-only physical GPT and inactive-slot admission for the frozen OS installer."""
from __future__ import annotations

from itertools import islice
import json
import os
from pathlib import Path
import re
import stat

from media_layout import parse_gpt, validate_layout
from os_state_layout import _layout, _mount_table, _one_mount, _pairs, _path, _read, _sysfs_read, mount_facts


def _number(path: Path, root: Path = Path("/")) -> int:
    raw = _sysfs_read(root, path).decode("ascii").strip()
    if not re.fullmatch(r"[0-9]{1,20}", raw):
        raise ValueError("invalid sysfs number")
    return int(raw)


def _device(path: Path, root: Path) -> str:
    raw = _sysfs_read(root, path).decode("ascii").strip()
    match = re.fullmatch(r"([0-9]{1,4}):([0-9]{1,7})", raw)
    if not match or not 1 <= int(match[1]) <= 4095 or int(match[2]) > 1048575:
        raise ValueError("invalid block device identity")
    if raw != f"{int(match[1])}:{int(match[2])}":
        raise ValueError("noncanonical block identity")
    return raw


def _partitions(disk: Path, root: Path, layout: dict) -> dict[int, str]:
    entries = list(islice(disk.iterdir(), 129))
    if len(entries) > 128:
        raise ValueError("too many disk sysfs entries")
    result = {}
    for path in entries:
        if path.is_symlink() or not path.is_dir() or not (path / "partition").exists():
            continue
        number, device = _number(path / "partition", root), _device(path / "dev", root)
        if number in result or device in result.values() or number not in range(1, 7):
            raise ValueError("ambiguous kernel partition topology")
        expected = layout["partitions"][number - 1]
        if (_number(path / "start", root) != expected["start_lba"]
                or _number(path / "size", root) != expected["size_lba"]):
            raise ValueError("kernel partition range differs from authenticated GPT")
        result[number] = device
    if set(result) != set(range(1, 7)):
        raise ValueError("kernel does not expose all six GPT partitions")
    return result


def _capture(root: Path) -> dict:
    root = Path(root).absolute()
    admitted = _layout(root)
    if admitted is None or admitted[0]["schema_version"] != 2:
        raise ValueError("automatic OS update requires boot protocol 2")
    descriptor = admitted[0]
    layout = validate_layout(json.loads(_read(_path(root, "etc/rosy/os-media.json"), 32768,
                                              root.stat().st_uid), object_pairs_hook=_pairs))
    parts = {part["role"]: part for part in layout["partitions"]}
    slot = descriptor["slot"]
    if (layout["provision_role"] != "bootstrap"
            or any(descriptor[key] != parts[role]["unique_guid"] for key, role in (
                ("root_partuuid", "root_" + slot), ("data_partuuid", "data"), ("provision_partuuid", "bootstrap")))):
        raise ValueError("slot descriptor differs from the factory media snapshot")
    tokens = _read(root / "proc/cmdline", 16384).decode("ascii").split()
    if [word for word in tokens if word.startswith("rauc.slot=")] != ["rauc.slot=" + slot]:
        raise ValueError("kernel RAUC slot differs from the active root")
    facts = mount_facts(root, descriptor)
    current_device = next(row["device"] for row in facts if row["role"] == "root")
    partition = (root / "sys/dev/block" / current_device).resolve(strict=True)
    if not partition.is_relative_to(root / "sys"):
        raise ValueError("root partition escapes sysfs")
    disk = partition.parent
    devices = _partitions(disk, root, layout)
    if devices[4 if slot == "a" else 5] != current_device:
        raise ValueError("current root device differs from kernel partition topology")
    disk_device = _device(disk / "dev", root)
    if disk_device in devices.values() or _number(disk / "size", root) * 512 < layout["raw_size_bytes"]:
        raise ValueError("physical disk identity or capacity differs")
    host, local = _mount_table(root, "proc/1/mountinfo"), _mount_table(root, "proc/self/mountinfo")
    active_boot = devices[2 if slot == "a" else 3]
    for table, writable in ((host, True), (local, False)):
        if _one_mount(table, "/boot/firmware", "vfat", writable)["device"] != active_boot:
            raise ValueError("active boot mount differs from the root slot")
    info = _path(root, "boot/firmware").stat()
    if f"{os.major(info.st_dev)}:{os.minor(info.st_dev)}" != active_boot:
        raise ValueError("visible boot mount device differs")
    inactive = {devices[5 if slot == "a" else 4], devices[3 if slot == "a" else 2]}
    if any(row["device"] in inactive for table in (host, local) for rows in table.values() for row in rows):
        raise ValueError("inactive OS root or boot is already mounted")
    raw = root / "proc/1/root/dev/block" / disk_device
    with os.fdopen(os.open(raw, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC), "rb", buffering=0) as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISBLK(info.st_mode) or f"{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}" != disk_device:
            raise ValueError("whole-disk handle differs from the admitted sysfs parent")
        def read_at(offset, count):
            handle.seek(offset)
            return handle.read(count)
        if parse_gpt(read_at, layout["raw_size_bytes"], "bootstrap") != layout:
            raise ValueError("physical GPT differs from the factory media snapshot")
    return dict(schema_version=1, slot=slot, layout=layout, disk_device=disk_device,
                partitions={part["role"]: dict(number=part["number"], device=devices[part["number"]],
                            path="/dev/block/" + devices[part["number"]]) for part in layout["partitions"]})


def capture(root: Path = Path("/")) -> dict:
    """Recapture before each destructive boundary; this result is never a reusable authorization."""
    try:
        return _capture(root)
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
        raise ValueError(f"OS_MEDIA_HOLD: {exc}") from exc
