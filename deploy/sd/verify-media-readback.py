#!/usr/bin/env python3
"""Compare every uncompressed image byte with the flashed physical device."""

from __future__ import annotations

import argparse
import hashlib
import json
import lzma
from pathlib import Path
import sys


CHUNK_SIZE = 4 * 1024 * 1024


def hash_image(image: Path) -> dict[str, object]:
    if image.suffix != ".xz":
        raise ValueError("image must be an xz-compressed raw disk image")

    image_hash = hashlib.sha256()
    hashed = 0
    with lzma.open(image, "rb") as expected:
        while True:
            chunk = expected.read(CHUNK_SIZE)
            if not chunk:
                break
            image_hash.update(chunk)
            hashed += len(chunk)
    return {
        "bytes_hashed": hashed,
        "image_raw_sha256": image_hash.hexdigest(),
    }


def verify(image: Path, device: str) -> dict[str, object]:
    if image.suffix != ".xz":
        raise ValueError("image must be an xz-compressed raw disk image")

    image_hash = hashlib.sha256()
    device_hash = hashlib.sha256()
    verified = 0
    with lzma.open(image, "rb") as expected, open(device, "rb", buffering=0) as actual:
        while True:
            expected_chunk = expected.read(CHUNK_SIZE)
            if not expected_chunk:
                break
            actual_chunk = actual.read(len(expected_chunk))
            if len(actual_chunk) != len(expected_chunk):
                raise ValueError(
                    f"media is shorter than the image at byte offset {verified}"
                )
            if actual_chunk != expected_chunk:
                mismatch = next(
                    index for index, pair in enumerate(zip(expected_chunk, actual_chunk))
                    if pair[0] != pair[1]
                )
                raise ValueError(
                    f"media readback mismatch at byte offset {verified + mismatch}"
                )
            image_hash.update(expected_chunk)
            device_hash.update(actual_chunk)
            verified += len(expected_chunk)

    evidence = {
        "bytes_verified": verified,
        "device_sha256": device_hash.hexdigest(),
        "image_raw_sha256": image_hash.hexdigest(),
        "verified": True,
    }
    if evidence["device_sha256"] != evidence["image_raw_sha256"]:
        raise ValueError("media readback digest mismatch")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--device")
    parser.add_argument("--image-only", action="store_true")
    args = parser.parse_args()
    try:
        if args.image_only:
            if args.device:
                raise ValueError("--device cannot be combined with --image-only")
            evidence = hash_image(args.image)
        else:
            if not args.device:
                raise ValueError("--device is required unless --image-only is used")
            evidence = verify(args.image, args.device)
    except (OSError, EOFError, lzma.LZMAError, ValueError) as exc:
        print(f"MEDIA_READBACK_FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(evidence, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
