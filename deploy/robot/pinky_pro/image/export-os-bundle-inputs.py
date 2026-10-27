#!/usr/bin/env python3
"""Export unsigned, compressed slot-A inputs before the native raw image is removed."""
from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ab_image_layout as ab
from os_state_layout import _pairs, _read
from os_update_manifest import release_id as validate_release_id
from signing import parse_sha256sums, sha256_file

CHUNK = 2 * 1024**2


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
            info.st_mode, info.st_uid, info.st_nlink)


def _extract(source, offset, size, destination):
    digest = hashlib.sha256()
    source.seek(offset)
    remaining = size
    with destination.open("xb") as output:
        with lzma.LZMAFile(output, "w", format=lzma.FORMAT_XZ, check=lzma.CHECK_CRC64, preset=6) as archive:
            while remaining:
                data = source.read(min(CHUNK, remaining))
                if not data:
                    raise ValueError("raw image ended inside an OS partition")
                digest.update(data)
                archive.write(data)
                remaining -= len(data)
        output.flush()
        os.fchmod(output.fileno(), 0o644)
        os.fsync(output.fileno())
    return dict(filename=destination.name, size_bytes=size, sha256=digest.hexdigest(),
                archive_bytes=destination.stat().st_size, archive_sha256=sha256_file(destination))


def export(raw: Path, layout: dict, output: Path, factory: Path, release_id: str, revision: str) -> dict:
    validate_release_id(release_id)
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("OS inputs need an exact source revision")
    raw, output, factory = Path(raw).absolute(), Path(output).absolute(), Path(factory).absolute()
    ab._offline_directory(raw.parent)
    ab._offline_directory(output.parent)
    ab._offline_directory(factory)
    if output.exists() or output.is_symlink() or ".." in output.parts:
        raise ValueError("OS bundle export requires a new output directory")
    layout = ab.validate_layout(layout)
    if layout["provision_role"] != "bootstrap":
        raise ValueError("OS bundle export requires the persistent-bootstrap layout")
    sums = _read(factory / "SHA256SUMS", 16 * 1024**2, os.geteuid())
    manifest = _read(factory / "manifest.json", 1024**2, os.geteuid())
    entries, errors = parse_sha256sums(sums)
    if errors or entries.get("manifest.json") != hashlib.sha256(manifest).hexdigest():
        raise ValueError("factory checksum does not bind its manifest")
    # The native manifest has its own evolving fields; only its release identity is needed here.
    value = json.loads(manifest, object_pairs_hook=_pairs)
    if not isinstance(value, dict) or value.get("release_id") != release_id:
        raise ValueError("factory belongs to another OS release")
    with os.fdopen(os.open(raw, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as source:
        before = os.fstat(source.fileno())
        if (not stat.S_ISREG(before.st_mode) or before.st_size != layout["raw_size_bytes"]
                or before.st_uid != os.geteuid() or before.st_mode & 0o022 or before.st_nlink != 1):
            raise ValueError("OS raw image type, size or ownership differs")
        def read_at(offset, size):
            source.seek(offset)
            return source.read(size)
        if ab.parse_gpt(read_at, before.st_size, "bootstrap") != layout:
            raise ValueError("actual GPT differs from the OS assembly snapshot")
        work = Path(tempfile.mkdtemp(prefix=".os-bundle-inputs-", dir=output.parent))
        try:
            images = {}
            for name, role in (("rootfs.ext4", "root_a"), ("boot.vfat", "boot_a")):
                part = next(p for p in layout["partitions"] if p["role"] == role)
                images[name] = _extract(source, part["start_lba"] * 512, part["size_lba"] * 512,
                                        work / (name + ".xz"))
            if (_identity(os.fstat(source.fileno())) != _identity(before)
                    or _identity(raw.stat()) != _identity(before)):
                raise ValueError("raw image changed while exporting OS inputs")
            result = dict(schema_version=1, kind="os-bundle-inputs", board="pinky_pro", arch="arm64",
                release_id=release_id, source_revision=revision, boot_abi=2,
                state_schema=dict(read_min=1, read_max=1, write=1), layout=layout,
                native_factory=dict(release_id=release_id, checksums_sha256=hashlib.sha256(sums).hexdigest()),
                images=images)
            ab._json_atomic(work / "inputs.json", result, 0o644)
            ab.sync_directory(work)
            os.rename(work, output)
            ab.sync_directory(output.parent)
            return result
        finally:
            if work.exists():
                shutil.rmtree(work)  # Only the fresh directory allocated by this invocation.


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("raw-image", "layout", "output", "factory"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--source-revision", required=True)
    args = parser.parse_args(argv)
    if platform.machine() != "aarch64":
        parser.error("release OS inputs require the native ARM64 image builder")
    result = export(args.raw_image, json.loads(args.layout.read_bytes()), args.output, args.factory,
                    args.release_id, args.source_revision)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
