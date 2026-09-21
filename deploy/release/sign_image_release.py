#!/usr/bin/env python3
"""Offline-sign a verified image release checksum list."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from signing import (
    CHECKSUM_FILENAME,
    SIGNATURE_FILENAME,
    find_unlisted_files,
    parse_sha256sums,
    sign_checksums,
    verify_checksums,
    verify_release_files,
)


def sign_image_release(root: Path, private_key: Path, public_key: Path) -> dict[str, object]:
    root = root.resolve(strict=True)
    private_key = private_key.resolve(strict=True)
    public_key = public_key.resolve(strict=True)
    if not root.is_dir() or root.is_symlink():
        raise ValueError("RELEASE_ROOT: release root must be a real directory")
    if private_key.is_symlink() or public_key.is_symlink():
        raise ValueError("KEY_PATH: signing keys must not be symlinks")
    if root == private_key.parent or root in private_key.parents:
        raise ValueError("PRIVATE_KEY_LOCATION: private key must remain outside the release")

    sums_path = root / CHECKSUM_FILENAME
    signature_path = root / SIGNATURE_FILENAME
    if signature_path.exists():
        raise ValueError("SIGNATURE_EXISTS: refusing to replace an existing signature")
    if not sums_path.is_file() or sums_path.is_symlink():
        raise ValueError("SHA256SUMS_MISSING: checksum list is unavailable")

    sums = sums_path.read_bytes()
    entries, rejections = parse_sha256sums(sums)
    rejections += verify_checksums(root, entries)
    rejections += find_unlisted_files(root, entries)
    if rejections:
        raise ValueError(str(rejections[0]))

    encoded = sign_checksums(sums, private_key)
    try:
        with signature_path.open("x", encoding="ascii", newline="\n") as stream:
            stream.write(encoded + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        rejections = verify_release_files(root, public_key)
        if rejections:
            raise ValueError(str(rejections[0]))
    except BaseException:
        signature_path.unlink(missing_ok=True)
        raise

    return {
        "ok": True,
        "release_root": str(root),
        "signature": SIGNATURE_FILENAME,
        "files_verified": len(entries),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release_root", type=Path)
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--public-key", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = sign_image_release(args.release_root, args.private_key, args.public_key)
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
