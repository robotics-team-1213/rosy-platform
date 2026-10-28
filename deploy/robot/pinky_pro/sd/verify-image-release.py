#!/usr/bin/env python3
"""Verify one signed ROSY OS image release before any disk is discovered."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


PRODUCT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PRODUCT_ROOT / "release"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from signing import verify_release_checksums  # noqa: E402
from media_layout import inspect_image  # noqa: E402


def verify_image_release(
    release_root: Path,
    public_key: Path,
    image: Path,
    release_id: str,
    expected_source_revision: str | None = None,
) -> dict:
    if expected_source_revision is not None and not re.fullmatch(r"[0-9a-f]{40}", expected_source_revision):
        raise ValueError("SOURCE_REVISION: expected source must be a full lowercase Git commit")
    release_root = release_root.resolve()
    public_key = public_key.resolve()
    image = image.resolve()
    if image.parent != release_root:
        raise ValueError("IMAGE_LOCATION: image must be a direct child of the release directory")

    checksums, rejections = verify_release_checksums(release_root, public_key)
    if rejections:
        raise ValueError("; ".join(str(item) for item in rejections))

    manifest_path = release_root / "manifest.json"
    try:
        manifest_bytes = manifest_path.read_bytes()
        if checksums.get("manifest.json") != hashlib.sha256(manifest_bytes).hexdigest():
            raise ValueError("MANIFEST_CHECKSUM: manifest differs from authenticated snapshot")
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"MANIFEST_UNREADABLE: {exc}") from exc

    expected = {
        "schema_version", "release_id", "product", "board", "architecture", "image"
    }
    if not isinstance(manifest, dict):
        raise ValueError("MANIFEST_FIELDS: image manifest shape is not supported")
    version = manifest.get("schema_version")
    if type(version) is not int or version not in (1, 2):
        raise ValueError("MANIFEST_SCHEMA: schema_version must be 1 or 2")
    if version == 2:
        expected.add("layout")
    if set(manifest) != expected:
        raise ValueError("MANIFEST_FIELDS: image manifest shape is not supported")
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
    # Full release verification already hashed the image; bind to that signed entry.
    actual = checksums.get(image.name)
    if actual is None:
        raise ValueError("MANIFEST_IMAGE: image has no signed checksum entry")
    if image_record["sha256"] != actual:
        raise ValueError("MANIFEST_IMAGE: signed image SHA-256 does not match")

    metadata = {}
    try:
        for name in ("source-revision.txt", "build-provenance.json"):
            data = (release_root / name).read_bytes()
            if checksums.get(name) != hashlib.sha256(data).hexdigest():
                raise ValueError("SOURCE_CHECKSUM: source evidence must match its signed checksum")
            metadata[name] = data
        revision = metadata["source-revision.txt"].decode("ascii").strip()
        provenance = json.loads(metadata["build-provenance.json"].decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("SOURCE_EVIDENCE: signed source evidence is missing or unreadable") from exc
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("SOURCE_REVISION: signed source must be a full lowercase Git commit")
    if (not isinstance(provenance, dict) or provenance.get("source_revision") != revision
            or provenance.get("release_id") != release_id):
        raise ValueError("SOURCE_PROVENANCE: build provenance differs from the signed source or release")
    if expected_source_revision is not None and revision != expected_source_revision:
        raise ValueError(f"SOURCE_REVISION: expected {expected_source_revision}, signed image contains {revision}")

    result = {"ok": "true", "release_id": release_id, "image": image.name, "sha256": actual,
              "source_revision": revision}
    if version == 2:
        result["layout"] = inspect_image(image, manifest["layout"], actual)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--public-key", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--expected-source-revision", help="exact full Git commit required in the signed image")
    args = parser.parse_args()
    try:
        result = verify_image_release(
            args.release_root, args.public_key, args.image, args.release_id, args.expected_source_revision
        )
    except ValueError as exc:
        print(f"REJECTED {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
