"""Offline construction of the fixed Pinky GPT layout and device-neutral state."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import uuid

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "sd"))
sys.path.insert(0, str(BASE / "native"))
from media_layout import BASIC_DATA, LINUX_FS, ROLES, parse_gpt, validate_layout
from os_state_files import sync_directory
from os_state_io import _json_atomic, _write_atomic
from os_state_layout import COMMON, SHARED_BINDINGS, _guid, _path, _read

MIB = 1024**2
RAW_MIB = 29 * 1024
ROOT_MIB = 11 * 1024
DATA_DIRECTORIES = {
    "state": (0o700, 0, 0), "policy": (0o700, 0, 0), "policy/updates": (0o700, 0, 0),
    "provisioning": (0o755, 0, 0), "core": (0o750, 960, 960),
    "network": (0o700, 0, 0), "network/system-connections": (0o700, 0, 0),
    "ssh": (0o755, 0, 0), "operator-ssh": (0o700, 1001, 1001), "tls": (0o750, 0, 960),
    "tailscale": (0o700, 0, 0), "tailscale/machine": (0o700, 0, 0), "tailscale/join": (0o700, 0, 0),
    "maps": (0o2750, 961, 960), "models": (0o750, 0, 963), "pilot-recordings": (0o2750, 963, 960),
}


def plan() -> dict:
    sizes = (64, 512, 512, ROOT_MIB, ROOT_MIB)
    sizes = (*sizes, RAW_MIB - sum(sizes) - 2)
    start, partitions = 2048, []
    for number, (role, mib) in enumerate(zip(ROLES, sizes), 1):
        sectors = mib * MIB // 512
        partitions.append(dict(role=role, number=number, start_lba=start, size_lba=sectors,
            type_guid=BASIC_DATA if number <= 3 else LINUX_FS, unique_guid=str(uuid.uuid4())))
        start += sectors
    return validate_layout(dict(schema_version=1, scheme="gpt", sector_size=512,
        disk_guid=str(uuid.uuid4()), raw_size_bytes=RAW_MIB * MIB, provision_role="boot_a", partitions=partitions))


def sfdisk_script(layout: dict) -> str:
    layout = validate_layout(layout)
    lines = ["label: gpt", "unit: sectors", "label-id: " + layout["disk_guid"],
             "first-lba: 34", f"last-lba: {layout['raw_size_bytes'] // 512 - 34}", "table-length: 128", ""]
    for part in layout["partitions"]:
        lines.append(f"start={part['start_lba']}, size={part['size_lba']}, type={part['type_guid']}, "
                     f"uuid={part['unique_guid']}, name=\"{part['role']}\"")
    return "\n".join(lines) + "\n"


def _offline_directory(path: Path) -> Path:
    path = Path(path).absolute()
    if (path == Path(path.anchor) or ".." in path.parts or not path.is_dir()
            or any(parent.is_symlink() for parent in (path, *path.parents))):
        raise ValueError("an offline directory is required")
    info = path.stat()
    if info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise ValueError("offline directory owner or permissions differ")
    return path


def initialize_data(directory: Path, factory_id: str) -> None:
    factory_id = _guid(factory_id)
    directory = _offline_directory(directory)
    entries = list(directory.iterdir())
    if any(entry.name != "lost+found" or entry.is_symlink() or not entry.is_dir()
           or any(entry.iterdir()) for entry in entries):
        raise ValueError("factory data filesystem is not empty")
    owner = directory.stat().st_uid
    directory.chmod(0o700)
    for relative, (mode, uid, gid) in DATA_DIRECTORIES.items():
        target = directory / relative
        target.mkdir(mode=0o700)
        os.chown(target, owner if uid == 0 else uid, owner if gid == 0 else gid)
        target.chmod(mode)  # chown may clear setgid.
    _json_atomic(directory / "state/schema.json", dict(schema_version=1, state_schema=1), 0o600)
    _json_atomic(directory / "state/factory.json",
                 dict(schema_version=1, state_schema=1, factory_id=factory_id), 0o600)
    _json_atomic(directory / "policy/updates/config.json",
                 dict(enabled=True, repo="robotics-team-1213/rosy-platform"), 0o644)
    for relative in sorted(DATA_DIRECTORIES, key=lambda name: name.count("/"), reverse=True):
        sync_directory(directory / relative)
    sync_directory(directory)


def _fstab(layout: dict, slot: str, source: str) -> str:
    records = [line.split() for line in source.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    expected = {"/": "ext4", "/boot/firmware": "vfat"}
    if (len(records) != 2 or any(len(row) != 6 for row in records)
            or {row[1]: row[2] for row in records} != expected):
        raise ValueError("unsupported source fstab")
    parts = {part["role"]: part for part in layout["partitions"]}
    lines = ["# Generated fixed A/B layout; no partition auto-grow."]
    for role, point, filesystem, options, order in (
            ("root_" + slot, "/", "ext4", "defaults", 1),
            ("boot_" + slot, "/boot/firmware", "vfat", "defaults", 2),
            ("data", "/" + COMMON, "ext4", "defaults,nodev,nosuid", 2),
            ("boot_a", "/run/rosy-provision-boot", "vfat", "defaults", 2)):
        lines.append(f"PARTUUID={parts[role]['unique_guid']} {point} {filesystem} {options} 0 {order}")
    for target, subpath in SHARED_BINDINGS.items():
        lines.append(f"/{COMMON}{subpath} /{target} none bind,x-systemd.requires-mounts-for=/{COMMON} 0 0")
    return "\n".join(lines) + "\n"


def configure_slot(root: Path, boot: Path, layout: dict, slot: str) -> None:
    root, boot = _offline_directory(root), _offline_directory(boot)
    layout = validate_layout(layout)
    if slot not in ("a", "b") or root == boot:
        raise ValueError("invalid offline slot")
    owner = root.stat().st_uid
    fstab_path, cmdline_path = _path(root, "etc/fstab"), _path(boot, "cmdline.txt")
    fstab = _fstab(layout, slot, _read(fstab_path, 16384, owner).decode("utf-8"))
    cmdline = _read(cmdline_path, 16384, boot.stat().st_uid).decode("ascii")
    tokens = cmdline.split()
    if (len(cmdline.strip().splitlines()) != 1 or "\0" in cmdline
            or sum(word.startswith("root=") for word in tokens) != 1
            or any(word.startswith(("rosy.os_layout=", "rauc.slot=")) for word in tokens)):
        raise ValueError("unsupported source kernel command line")
    parts = {part["role"]: part for part in layout["partitions"]}
    descriptor = dict(schema_version=1, state_schema=1, slot=slot,
        root_partuuid=parts["root_" + slot]["unique_guid"], data_partuuid=parts["data"]["unique_guid"],
        provision_partuuid=parts["boot_a"]["unique_guid"])
    tokens = ["root=PARTUUID=" + descriptor["root_partuuid"] if word.startswith("root=") else word for word in tokens]
    tokens.append("rosy.os_layout=ab-v1")
    changes = {"etc/fstab": fstab,
               "etc/rosy/os-slot.json": json.dumps(descriptor, sort_keys=True) + "\n",
               "etc/cloud/cloud.cfg.d/99-rosy-fixed-layout.cfg": "growpart: {mode: 'off'}\nresize_rootfs: false\n"}
    targets = {relative: _path(root, relative) for relative in changes}
    for relative, target in targets.items():
        if target.exists() and relative != "etc/fstab":
            raise ValueError("offline slot metadata already exists")
        if target.exists() and target.stat().st_nlink != 1:
            raise ValueError("offline slot metadata is hard-linked")
    if cmdline_path.stat().st_nlink != 1:
        raise ValueError("offline kernel command line is hard-linked")
    for relative, target in targets.items():
        _write_atomic(target, changes[relative], 0o644)
    _write_atomic(cmdline_path, " ".join(tokens) + "\n", 0o644)


def capacity_report(free_bytes: int, payload_bytes: int) -> dict:
    if type(free_bytes) is not int or free_bytes < 0 or type(payload_bytes) is not int or payload_bytes <= 0:
        raise ValueError("invalid capacity measurement")
    # Factory is already copied; reserve current, previous, staging and the in-flight archive.
    required = 4 * payload_bytes + 512 * MIB
    if free_bytes < required:
        raise ValueError(f"insufficient root capacity: {free_bytes} available, {required} reserve required")
    return dict(available_bytes=free_bytes, baseline_payload_bytes=payload_bytes, reserve_required_bytes=required)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("plan")
    table = commands.add_parser("sfdisk")
    table.add_argument("--layout", type=Path, required=True)
    data = commands.add_parser("initialize-data")
    data.add_argument("--directory", type=Path, required=True)
    data.add_argument("--factory-id", required=True)
    slot = commands.add_parser("configure-slot")
    slot.add_argument("--layout", type=Path, required=True)
    slot.add_argument("--root", type=Path, required=True)
    slot.add_argument("--boot", type=Path, required=True)
    slot.add_argument("--slot", choices=("a", "b"), required=True)
    args = parser.parse_args(argv)
    if args.command == "plan":
        print(json.dumps(plan(), sort_keys=True))
    elif args.command == "initialize-data":
        initialize_data(args.directory, args.factory_id)
    else:
        layout = json.loads(args.layout.read_text(encoding="utf-8"))
        if args.command == "sfdisk":
            print(sfdisk_script(layout), end="")
        else:
            configure_slot(args.root, args.boot, layout, args.slot)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
