#!/usr/bin/env python3
"""Copy diagnosis files off a ROSY card without mounting it (D-174 F8, D-175).

Windows cannot mount the card's ext4 root, and ``wsl --mount`` fails on USB SD
readers (0x8007000f, leaving the disk offline). This tool opens the physical
disk (or a raw image file) read-only, finds the Linux root partition in the MBR,
parses ext4 in pure Python (``pip install ext4``) and copies a fixed set of
diagnosis files into an output folder, plus the D-175 black box ``rosy-diag/``
from the FAT32 boot partition. Nothing is ever written to the source.

Paths that ``rosy_diag_redact.is_denied_path`` denies (Wi-Fi connection files,
the provisioning bundle, tokens, keys) are never opened, and anything outside
the fixed set is never read. Copies are raw (the journal is binary), so the
output stays on the operator's PC like any other card evidence.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import sys
from typing import Callable

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "robot" / "native"))
from rosy_diag_redact import is_denied_path  # noqa: E402


SECTOR = 512
CHUNK = 1 << 20
MAX_FILE = 256 * 1024 * 1024
MAX_BOOT_PARTITION = 2 * 1024 * 1024 * 1024
MAX_DEPTH = 12
FAT32_TYPES = {0x0B, 0x0C}
LINUX_TYPE = 0x83
GPT_PROTECTIVE = 0xEE
BLACK_BOX = "rosy-diag"

FILES = ("/etc/hostname", "/etc/passwd")
TREES = ("/var/lib/rosy", "/etc/rosy", "/etc/systemd/system", "/var/log/journal")
LOG_DIR = "/var/log"  # only cloud-init*.log is taken from here
UNSAFE = set('<>:"\\|?*%')
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10))}


class RawDisk:
    """Read-only, 1 MiB-aligned, cached view of a physical disk or image file.

    Windows raw disk handles accept only sector-aligned reads, and ext4 needs
    read/peek/seek/tell with SEEK_END. ``size`` bounds every read so a chunk
    never runs past the end of the last partition.
    """

    def __init__(self, path: str, size: int | None = None) -> None:
        self._fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        self._pos = 0
        self._cache: dict[int, bytes] = {}
        self.size = size

    def _chunk(self, index: int) -> bytes:
        data = self._cache.get(index)
        if data is None:
            length = CHUNK
            if self.size is not None:
                remaining = self.size - index * CHUNK
                if remaining <= 0:
                    return b""
                length = min(CHUNK, -(-remaining // SECTOR) * SECTOR)
            os.lseek(self._fd, index * CHUNK, os.SEEK_SET)
            data = os.read(self._fd, length)
            if self.size is not None:
                data = data[:max(0, self.size - index * CHUNK)]
            if len(self._cache) > 256:
                self._cache.clear()
            self._cache[index] = data
        return data

    def read_at(self, position: int, size: int) -> bytes:
        out = bytearray()
        while size > 0:
            index, inner = divmod(position, CHUNK)
            data = self._chunk(index)[inner:inner + size]
            if not data:
                break
            out += data
            position += len(data)
            size -= len(data)
        return bytes(out)

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            if self.size is None:
                raise ValueError("read to end needs a known size")
            size = max(0, self.size - self._pos)
        data = self.read_at(self._pos, size)
        self._pos += len(data)
        return data

    def peek(self, size: int = 0) -> bytes:
        return self.read_at(self._pos, size or 1)

    def seek(self, position: int, whence: int = os.SEEK_SET) -> int:
        if whence == os.SEEK_SET:
            self._pos = position
        elif whence == os.SEEK_CUR:
            self._pos += position
        elif whence == os.SEEK_END:
            if self.size is None:
                raise ValueError("SEEK_END needs a known size")
            self._pos = self.size + position
        else:
            raise ValueError(f"invalid whence {whence}")
        return self._pos

    def tell(self) -> int:
        return self._pos

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def close(self) -> None:
        os.close(self._fd)


def device_path(value: str) -> str:
    """A bare disk number means that Windows physical drive."""
    return rf"\\.\PhysicalDrive{value}" if value.isdigit() else value


def select_partitions(head: bytes) -> tuple[tuple[int, int] | None, tuple[int, int]]:
    """Return ((boot offset, length) or None, (root offset, length)) in bytes."""
    if len(head) < SECTOR or head[510:512] != b"\x55\xaa":
        raise ValueError("no MBR partition table on this disk")
    entries = []
    for index in range(4):
        entry = head[446 + 16 * index:462 + 16 * index]
        start, sectors = struct.unpack_from("<II", entry, 8)
        if entry[4] and start and sectors:
            entries.append((entry[4], start * SECTOR, sectors * SECTOR))
    if any(kind == GPT_PROTECTIVE for kind, _, _ in entries):
        raise ValueError("GPT disks are not supported (protective MBR); ROSY cards use MBR")
    boot = next(((start, length) for kind, start, length in entries if kind in FAT32_TYPES), None)
    root = next(((start, length) for kind, start, length in entries if kind == LINUX_TYPE), None)
    if root is None:
        raise ValueError("no Linux root partition (type 0x83) in the MBR")
    return boot, root


def _safe_part(name: str) -> str:
    text = "".join(f"%{ord(char):02X}" if char in UNSAFE or ord(char) < 0x20 else char for char in name)
    if text.split(".", 1)[0].upper() in RESERVED:
        text = f"%{ord(text[0]):02X}{text[1:]}"
    if text.endswith((".", " ")):
        text = f"{text[:-1]}%{ord(text[-1]):02X}"
    return text


def _saved_as(prefix: str, path: str) -> str:
    return "/".join([prefix, *(_safe_part(part) for part in path.strip("/").split("/"))])


def _copy_stream(source, target: Path) -> tuple[int, str, bool]:
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    truncated = False
    with open(target, "xb") as sink:
        while True:
            block = source.read(CHUNK)
            if not block:
                break
            if size + len(block) > MAX_FILE:
                block = block[:MAX_FILE - size]
                truncated = True
            sink.write(block)
            digest.update(block)
            size += len(block)
            if truncated:
                break
    return size, digest.hexdigest(), truncated


class Ext4Tree:
    """Adapter from the ``ext4`` package to the small interface the walker uses."""

    def __init__(self, volume) -> None:
        import ext4

        self._ext4 = ext4
        self._volume = volume

    def kind(self, path: str) -> str:
        inode = self._volume.inode_at(path)
        if isinstance(inode, self._ext4.SymbolicLink):
            return "link"
        if isinstance(inode, self._ext4.Directory):
            return "dir"
        if isinstance(inode, self._ext4.File):
            return "file"
        return "other"

    def listdir(self, path: str) -> list[str]:
        names = []
        for dirent, _kind in self._volume.inode_at(path).opendir():
            try:
                name = dirent.name_str
            except UnicodeDecodeError:
                name = dirent.name_bytes.decode("utf-8", "replace")
            if name not in (".", ".."):
                names.append(name)
        return sorted(names)

    def open(self, path: str):
        return self._volume.inode_at(path).open()

    def readlink(self, path: str) -> str:
        return self._volume.inode_at(path).readlink().decode("utf-8", "replace")


def open_ext4(raw: RawDisk, offset: int, _length: int) -> Ext4Tree:
    try:
        import ext4
    except ImportError as error:
        raise SystemExit("the ext4 package is required: python -m pip install ext4") from error
    return Ext4Tree(ext4.Volume(raw, offset=offset, ignore_checksum=True))


def _new_report(source: str) -> dict:
    return {
        "tool": "read-card-diagnostics",
        "source": source,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "files": {},
        "links": {},
        "denied": [],
        "missing": [],
        "errors": {},
        "boot_diag": {"present": False, "files": {}},
    }


def _prepare_output(out: Path) -> None:
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise FileExistsError(f"output folder exists and is not empty: {out}")
    out.mkdir(parents=True, exist_ok=True)


def _copy_file(tree, path: str, out: Path, report: dict) -> None:
    saved = _saved_as("rootfs", path)
    try:
        with tree.open(path) as source:
            size, sha256, truncated = _copy_stream(source, out / saved)
    except Exception as error:  # keep going; the report says why
        report["errors"][path] = f"{type(error).__name__}: {error}"
        return
    entry = {"size": size, "sha256": sha256, "saved_as": saved}
    if truncated:
        entry["truncated_at"] = MAX_FILE
    report["files"][path] = entry


def _walk(tree, path: str, out: Path, report: dict, depth: int = 0) -> None:
    if is_denied_path(path):
        report["denied"].append(path)
        return
    try:
        kind = tree.kind(path)
    except FileNotFoundError:
        report["missing"].append(path)
        return
    except Exception as error:
        report["errors"][path] = f"{type(error).__name__}: {error}"
        return
    if kind == "link":
        try:
            report["links"][path] = tree.readlink(path)
        except Exception as error:
            report["errors"][path] = f"{type(error).__name__}: {error}"
    elif kind == "file":
        _copy_file(tree, path, out, report)
    elif kind == "dir":
        if depth >= MAX_DEPTH:
            report["errors"][path] = "directory depth limit"
            return
        try:
            names = tree.listdir(path)
        except Exception as error:
            report["errors"][path] = f"{type(error).__name__}: {error}"
            return
        for name in names:
            if name in ("", ".", "..") or "/" in name or "\0" in name:
                report["errors"][f"{path}/{name!r}"] = "unsafe directory entry name"
                continue
            _walk(tree, path.rstrip("/") + "/" + name, out, report, depth + 1)


def _walk_root(tree, out: Path, report: dict) -> None:
    for path in FILES:
        _walk(tree, path, out, report)
    for path in TREES:
        _walk(tree, path, out, report)
    try:
        names = tree.listdir(LOG_DIR)
    except Exception as error:
        report["errors"][LOG_DIR] = f"{type(error).__name__}: {error}"
        names = []
    for name in names:
        if name.startswith("cloud-init") and name.endswith(".log"):
            _walk(tree, f"{LOG_DIR}/{name}", out, report)


def _write_report(out: Path, report: dict) -> None:
    for key in ("denied", "missing"):
        report[key] = sorted(set(report[key]))
    (out / "extract-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def extract_tree(tree, out: Path, boot_diag: dict | None = None, source: str = "tree") -> dict:
    """Copy the diagnosis set from an already opened root filesystem."""
    out = Path(out)
    _prepare_output(out)
    report = _new_report(source)
    if boot_diag is not None:
        report["boot_diag"] = boot_diag
    _walk_root(tree, out, report)
    _write_report(out, report)
    return report


def _fat32_module():
    spec = importlib.util.spec_from_file_location("verify_media_readback", HERE / "verify-media-readback.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def copy_black_box(raw: RawDisk, boot: tuple[int, int], out: Path, report: dict) -> None:
    """Copy only ``rosy-diag/`` from the FAT32 boot partition."""
    offset, length = boot
    if length > MAX_BOOT_PARTITION:
        report["errors"]["boot:" + BLACK_BOX] = "boot partition is larger than expected"
        return
    try:
        fat = _fat32_module().Fat32(raw.read_at(offset, length))
        pending = [(BLACK_BOX, first) for name, is_dir, first, _size in fat.entries(fat.root)
                   if is_dir and name.lower() == BLACK_BOX and first]
    except Exception as error:
        report["errors"]["boot:" + BLACK_BOX] = f"{type(error).__name__}: {error}"
        return
    result = report["boot_diag"]
    result["present"] = bool(pending)
    while pending:
        prefix, cluster = pending.pop()
        if prefix.count("/") >= 3:
            continue
        for name, is_dir, first, size in fat.entries(cluster):
            relative = f"{prefix}/{name}"
            if is_denied_path("/boot/firmware/" + relative):
                report["denied"].append("/boot/firmware/" + relative)
            elif is_dir:
                if first:
                    pending.append((relative, first))
            else:
                content = fat.read(first, size) if first else b""
                saved = _saved_as("boot", relative)
                target = out / saved
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                result["files"][relative] = {
                    "size": len(content), "sha256": hashlib.sha256(content).hexdigest(), "saved_as": saved,
                }


def extract(disk: str, out: Path, open_tree: Callable[[RawDisk, int, int], object] = open_ext4) -> dict:
    """Read-only extraction from a physical disk path or raw image file."""
    out = Path(out)
    _prepare_output(out)
    report = _new_report(disk)
    raw = RawDisk(disk)
    try:
        boot, root = select_partitions(raw.read_at(0, SECTOR))
        raw.size = max(start + length for start, length in (root, boot or (0, 0)))
        report["partitions"] = {"root": {"offset": root[0], "length": root[1]}}
        if boot is not None:
            report["partitions"]["boot"] = {"offset": boot[0], "length": boot[1]}
            copy_black_box(raw, boot, out, report)
        else:
            report["boot_diag"]["reason"] = "no FAT32 partition"
        _walk_root(open_tree(raw, root[0], root[1]), out, report)
    finally:
        raw.close()
    _write_report(out, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Copy ROSY diagnosis files off a card read-only: provisioning state, /etc/rosy, "
            "systemd units, the journal, cloud-init logs and the FAT32 rosy-diag/ black box. "
            "Wi-Fi connection files and the provisioning bundle are never read. Run from an "
            "elevated (administrator) PowerShell for a physical disk; wsl --mount does not "
            "work with USB SD readers."
        ),
    )
    parser.add_argument("--disk", required=True,
                        help=r"Windows disk number (Get-Disk), \\.\PhysicalDriveN, or a raw image file")
    parser.add_argument("--out", required=True, type=Path, help="new or empty output folder")
    args = parser.parse_args(argv)
    try:
        report = extract(device_path(args.disk), args.out)
    except PermissionError as error:
        print(f"cannot open {args.disk} read-only ({error}); run from an administrator PowerShell",
              file=sys.stderr)
        return 1
    except (OSError, ValueError) as error:
        print(f"extraction failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps({
        "report": str(args.out / "extract-report.json"),
        "files": len(report["files"]),
        "black_box_files": len(report["boot_diag"]["files"]),
        "denied": len(report["denied"]),
        "errors": len(report["errors"]),
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
