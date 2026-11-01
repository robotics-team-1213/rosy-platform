#!/usr/bin/env python3
"""Read one public host key without mounting or writing the card.

The caller must obtain --layout-file from verify-image-release.py and device-name
from its reviewed plan. The name labels that plan; no card identity file is read.
This tool does not verify a signature or install an SSH trust pin.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import uuid
import zlib

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from media_layout import ENTRY_SIZE, SECTOR, _header, validate_layout
from personalization import DEVICE_NAME_PATTERN

spec = importlib.util.spec_from_file_location("card_hostkey_readonly", HERE / "read-card-diagnostics.py")
diag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)

PUBLIC = "/ssh-hostkeys/ssh_host_ed25519_key.pub"
MAX_PUBLIC = 4096


def data_partition(raw, expected: dict, capacity: int) -> dict:
    """Validate actual GPT copies and bind every partition to the authenticated mapping."""
    if type(capacity) is not int or capacity < expected["raw_size_bytes"] or capacity % SECTOR:
        raise ValueError("invalid physical capacity")
    mbr, primary_bytes = raw.read_at(0, SECTOR), raw.read_at(SECTOR, SECTOR)
    if len(mbr) != SECTOR or len(primary_bytes) != SECTOR or mbr[510:] != b"\x55\xaa":
        raise ValueError("missing protective GPT metadata")
    entries = [mbr[446 + 16 * i:462 + 16 * i] for i in range(4)]
    protected = struct.unpack_from("<II", entries[0], 8)
    spans = {min(size // SECTOR - 1, 0xFFFFFFFF) for size in (capacity, expected["raw_size_bytes"])}
    if (entries[0][0] or entries[0][4] != 0xEE or protected[0] != 1 or protected[1] not in spans
            or any(any(entry) for entry in entries[1:])):
        raise ValueError("unsupported protective or hybrid MBR")
    sectors = struct.unpack_from("<Q", primary_bytes, 32)[0] + 1
    if sectors * SECTOR not in (capacity, expected["raw_size_bytes"]):
        raise ValueError("GPT backup extent differs")
    primary = _header(primary_bytes, 1, sectors - 1, sectors)
    backup = _header(raw.read_at((sectors - 1) * SECTOR, SECTOR), sectors - 1, 1, sectors)
    if any(primary[k] != backup[k] for k in ("guid", "first", "last", "count", "array_crc")):
        raise ValueError("GPT headers disagree")
    table = raw.read_at(primary["table"] * SECTOR, primary["count"] * ENTRY_SIZE)
    if (len(table) != primary["count"] * ENTRY_SIZE or zlib.crc32(table) != primary["array_crc"]
            or table != raw.read_at(backup["table"] * SECTOR, len(table))
            or primary["guid"] != expected["disk_guid"]):
        raise ValueError("GPT table or disk GUID differs")
    pinned = bytearray(len(table))
    for i, part in enumerate(expected["partitions"]):
        start, end = part["start_lba"], part["start_lba"] + part["size_lba"] - 1
        if not primary["first"] <= start <= end <= primary["last"]:
            raise ValueError("partition outside usable GPT range")
        struct.pack_into("<16s16sQQQ72s", pinned, i * ENTRY_SIZE,
                         uuid.UUID(part["type_guid"]).bytes_le, uuid.UUID(part["unique_guid"]).bytes_le,
                         start, end, 0, part["role"].encode("utf-16-le"))
    if table != pinned:
        raise ValueError("GPT partition mapping differs from signed layout")
    return expected["partitions"][-1]


def public_identity(value: bytes) -> dict:
    if len(value) > MAX_PUBLIC:
        raise ValueError("public key exceeds bound")
    text = value.decode("ascii").strip()
    if not text or any(not 32 <= ord(c) <= 126 for c in text):
        raise ValueError("public key must be one printable line")
    parts = text.split()
    if len(parts) < 2 or parts[0] != "ssh-ed25519":
        raise ValueError("expected an Ed25519 public key")
    blob = base64.b64decode(parts[1], validate=True)
    if (len(blob) != 51 or blob[:15] != struct.pack(">I", 11) + b"ssh-ed25519"
            or blob[15:19] != struct.pack(">I", 32)):
        raise ValueError("invalid Ed25519 wire key")
    return dict(public_key="ssh-ed25519 " + base64.b64encode(blob).decode("ascii"),
                fingerprint="SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode("ascii").rstrip("="))


def extract(disk: str, capacity: int, layout: dict, device_name: str, receipt: Path, *, open_tree=diag.open_ext4) -> dict:
    expected = validate_layout(layout)
    if not DEVICE_NAME_PATTERN.fullmatch(device_name):
        raise ValueError("invalid reviewed device name")
    if receipt.exists():
        raise FileExistsError("receipt already exists")
    raw = diag.RawDisk(disk, size=capacity)
    try:
        part = data_partition(raw, expected, capacity)
        tree = open_tree(raw, part["start_lba"] * SECTOR, part["size_lba"] * SECTOR)
        if tree.kind("/ssh-hostkeys") != "dir" or tree.kind(PUBLIC) != "file":
            raise ValueError("public key path must be a regular file without symlinks")
        with tree.open(PUBLIC) as stream:
            identity = public_identity(stream.read(MAX_PUBLIC + 1))
    finally:
        raw.close()
    result = dict(device_name=device_name, **identity)
    with receipt.open("x", encoding="utf-8") as output:
        output.write(json.dumps(result, sort_keys=True) + "\n")
        output.flush()
        os.fsync(output.fileno())
    return result


def probe_usb(serial: str) -> tuple[str, int]:
    """Fresh serial selection before the read-only handle is opened; no serial is printed."""
    if not serial or len(serial) > 256 or serial.strip() != serial or any(not 32 <= ord(c) <= 126 for c in serial):
        raise ValueError("invalid USB serial selector")
    script = r"""
$ErrorActionPreference = 'Stop'
$serial = [Console]::In.ReadToEnd()
$rows = @(Get-Disk | Where-Object { $_.SerialNumber -and $_.SerialNumber.Trim() -ceq $serial } |
    Select-Object Number, Size, @{Name='BusType'; Expression={[string]$_.BusType}}, IsBoot, IsSystem, IsOffline)
ConvertTo-Json -InputObject $rows -Compress
"""
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                            input=serial, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise ValueError("USB disk discovery failed")
    rows = json.loads(result.stdout)
    if not isinstance(rows, list) or len(rows) != 1:
        raise ValueError("USB serial must select exactly one disk")
    row = rows[0]
    if (not isinstance(row, dict) or row.get("BusType") != "USB"
            or any(row.get(k) is not False for k in ("IsBoot", "IsSystem", "IsOffline"))
            or type(row.get("Number")) is not int or not 0 <= row["Number"] <= 255
            or type(row.get("Size")) is not int or not 0 < row["Size"] <= 2**63 - 1 or row["Size"] % SECTOR):
        raise ValueError("selected disk is not a readable non-system USB disk")
    return rf"\\.\PhysicalDrive{row['Number']}", row["Size"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--disk-serial")
    source.add_argument("--fixture-device", type=Path)
    parser.add_argument("--capacity-bytes", type=int, help="file-backed fixtures only")
    parser.add_argument("--layout-file", type=Path, required=True, help="authenticated snapshot from verify-image-release.py")
    parser.add_argument("--device-name", required=True, help="public name from the reviewed plan, not card-attested identity")
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    try:
        layout = validate_layout(json.loads(args.layout_file.read_text(encoding="utf-8-sig")))
        if args.fixture_device:
            if args.fixture_device.is_symlink() or not args.fixture_device.is_file() or args.capacity_bytes is None:
                raise ValueError("fixture source requires an existing regular file and capacity")
            disk, capacity = str(args.fixture_device), args.capacity_bytes
        else:
            if args.capacity_bytes is not None:
                raise ValueError("physical capacity must come from fresh USB discovery")
            disk, capacity = probe_usb(args.disk_serial)
        extract(disk, capacity, layout, args.device_name, args.receipt)
    except (ValueError, OSError, KeyError, TypeError, struct.error, subprocess.TimeoutExpired):
        print("PUBLIC_HOSTKEY_EXTRACTION_REFUSED", file=sys.stderr)
        return 1
    print("PUBLIC_HOSTKEY_RECEIPT_WRITTEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
