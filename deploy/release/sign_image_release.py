#!/usr/bin/env python3
"""Offline-sign a verified image release checksum list.

D-225 2.2: an image release also carries ``factory-release/<id>/SHA256SUMS``,
the checksum list of the release installed inside the image. The image itself
stays unsigned (the key never reaches CI), so that list is signed here, with
the same key, into ``factory-release/<id>/SHA256SUMS.sig``. The SD writer
carries that signature to the card and first boot installs it next to the
factory release, which is what lets the robot roll back to it later.

Order: the outer list is verified as CI wrote it, each factory list is signed
and its signature checked, the outer list is re-rendered with one more entry
per factory signature (so ``find_unlisted_files`` and the outer signature
cover it), and only then is the outer list signed. Any failure removes every
signature this run wrote and restores the outer list byte for byte.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re

from signing import (
    CHECKSUM_FILENAME,
    SIGNATURE_FILENAME,
    find_unlisted_files,
    parse_sha256sums,
    sha256_file,
    sign_checksums,
    verify_checksums,
    verify_release_files,
    verify_signature,
)


FACTORY_DIR = "factory-release"
RELEASE_ID = re.compile(r"^[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]{3}$")


def _write_new(path: Path, text: str) -> None:
    with path.open("x", encoding="ascii", newline="\n") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())


def _replace(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def factory_releases(root: Path) -> list[str]:
    """The factory release ids an image release carries, validated for signing."""
    base = root / FACTORY_DIR
    if not base.exists() and not base.is_symlink():
        return []
    if base.is_symlink() or not base.is_dir():
        raise ValueError("FACTORY_RELEASE: factory-release must be a real directory")
    ids = []
    for entry in sorted(base.iterdir()):
        release_id = entry.name
        if entry.is_symlink() or not entry.is_dir() or not RELEASE_ID.fullmatch(release_id):
            raise ValueError(f"FACTORY_RELEASE: unexpected entry {FACTORY_DIR}/{release_id}")
        if (entry / SIGNATURE_FILENAME).exists():
            raise ValueError(f"FACTORY_SIGNATURE_EXISTS: {FACTORY_DIR}/{release_id} is already signed")
        sums = entry / CHECKSUM_FILENAME
        manifest = entry / "manifest.json"
        if not sums.is_file() or not manifest.is_file():
            raise ValueError(f"FACTORY_RELEASE: {FACTORY_DIR}/{release_id} needs SHA256SUMS and manifest.json")
        entries, rejections = parse_sha256sums(sums.read_bytes())
        if rejections:
            raise ValueError(f"FACTORY_RELEASE: {rejections[0]}")
        if entries.get("manifest.json") != sha256_file(manifest):
            raise ValueError(f"FACTORY_RELEASE: {FACTORY_DIR}/{release_id}/SHA256SUMS does not cover manifest.json")
        try:
            identity = json.loads(manifest.read_text(encoding="utf-8")).get("release_id")
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError) as exc:
            raise ValueError(f"FACTORY_RELEASE: {FACTORY_DIR}/{release_id}/manifest.json is unreadable") from exc
        if identity != release_id:
            raise ValueError(f"FACTORY_RELEASE: {FACTORY_DIR}/{release_id}/manifest.json names {identity!r}")
        ids.append(release_id)
    return ids


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

    original = sums_path.read_bytes()
    entries, rejections = parse_sha256sums(original)
    rejections += verify_checksums(root, entries)
    rejections += find_unlisted_files(root, entries)
    if rejections:
        raise ValueError(str(rejections[0]))
    factory_ids = factory_releases(root)

    written: list[Path] = []
    try:
        for release_id in factory_ids:
            factory = root / FACTORY_DIR / release_id
            factory_sums = (factory / CHECKSUM_FILENAME).read_bytes()
            factory_signature = factory / SIGNATURE_FILENAME
            encoded = sign_checksums(factory_sums, private_key)
            _write_new(factory_signature, encoded + "\n")
            written.append(factory_signature)
            rejections = verify_signature(factory_sums, encoded, public_key)
            if rejections:
                raise ValueError(f"FACTORY_{rejections[0]}")
            entries[factory_signature.relative_to(root).as_posix()] = sha256_file(factory_signature)
        if factory_ids:
            _replace(sums_path, "".join(
                f"{entries[relative]}  {relative}\n" for relative in sorted(entries)
            ).encode("utf-8"))
        sums = sums_path.read_bytes()

        encoded = sign_checksums(sums, private_key)
        _write_new(signature_path, encoded + "\n")
        written.append(signature_path)
        rejections = verify_release_files(root, public_key)
        if rejections:
            raise ValueError(str(rejections[0]))
    except BaseException:
        for path in written:
            path.unlink(missing_ok=True)
        if sums_path.read_bytes() != original:
            _replace(sums_path, original)
        raise

    return {
        "ok": True,
        "release_root": str(root),
        "signature": SIGNATURE_FILENAME,
        "files_verified": len(entries),
        "factory_releases": factory_ids,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
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
