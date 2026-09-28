#!/usr/bin/env python3
"""Verify one signed ROSY OS image release before any disk is discovered."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


PRODUCT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PRODUCT_ROOT / "release"))

from signing import verify_release_files  # noqa: E402


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def verify_image_release(
    release_root: Path,
    public_key: Path,
    image: Path,
    release_id: str,
) -> dict[str, str]:
    release_root = release_root.resolve()
    public_key = public_key.resolve()
    image = image.resolve()
    if image.parent != release_root:
        raise ValueError("IMAGE_LOCATION: image must be a direct child of the release directory")

    rejections = verify_release_files(release_root, public_key)
    if rejections:
        raise ValueError("; ".join(str(item) for item in rejections))

    manifest_path = release_root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"MANIFEST_UNREADABLE: {exc}") from exc

    expected = {
        "schema_version", "release_id", "product", "board", "architecture", "image"
    }
    if not isinstance(manifest, dict) or set(manifest) != expected:
        raise ValueError("MANIFEST_FIELDS: image manifest shape is not supported")
    if manifest["schema_version"] != 1:
        raise ValueError("MANIFEST_SCHEMA: schema_version must be 1")
    identity = {
        "release_id": release_id,
        "product": "rosy-os",
        "board": "pinky_pro",
        "architecture": "arm64",
    }
    for field, wanted in identity.items():
        if manifest.get(field) != wanted:
            raise ValueError(f"MANIFEST_IDENTITY: {field} must be {wanted!r}")

    image_record = manifest.get("image")
    if not isinstance(image_record, dict) or set(image_record) != {"filename", "sha256"}:
        raise ValueError("MANIFEST_IMAGE: image record shape is not supported")
    if image_record["filename"] != image.name:
        raise ValueError("MANIFEST_IMAGE: signed image filename does not match")
    actual = sha256_file(image)
    if image_record["sha256"] != actual:
        raise ValueError("MANIFEST_IMAGE: signed image SHA-256 does not match")

    return {"ok": "true", "release_id": release_id, "image": image.name, "sha256": actual}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--public-key", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    args = parser.parse_args()
    try:
        result = verify_image_release(
            args.release_root, args.public_key, args.image, args.release_id
        )
    except ValueError as exc:
        print(f"REJECTED {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
