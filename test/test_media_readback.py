"""Byte-for-byte verification of a flashed compressed disk image."""

from __future__ import annotations

import hashlib
import json
import lzma
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "deploy" / "sd" / "verify-media-readback.py"


def _run(image: Path, device: Path):
    return subprocess.run(
        [sys.executable, str(VERIFY), "--image", str(image), "--device", str(device)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_readback_accepts_exact_decompressed_image_prefix(tmp_path):
    raw = (b"rosy-media-readback\0" * 8192) + b"end"
    image = tmp_path / "rosy.img.xz"
    device = tmp_path / "physical-drive.fixture"
    image.write_bytes(lzma.compress(raw))
    device.write_bytes(raw + b"unused-card-tail")

    completed = _run(image, device)

    assert completed.returncode == 0, completed.stderr
    evidence = json.loads(completed.stdout)
    assert evidence == {
        "bytes_verified": len(raw),
        "device_sha256": hashlib.sha256(raw).hexdigest(),
        "image_raw_sha256": hashlib.sha256(raw).hexdigest(),
        "verified": True,
    }


def test_readback_rejects_first_different_byte(tmp_path):
    raw = b"expected bytes" * 4096
    different = bytearray(raw)
    different[len(different) // 2] ^= 0xFF
    image = tmp_path / "rosy.img.xz"
    device = tmp_path / "physical-drive.fixture"
    image.write_bytes(lzma.compress(raw))
    device.write_bytes(different)

    completed = _run(image, device)

    assert completed.returncode != 0
    assert "mismatch" in completed.stderr.lower()


def test_readback_rejects_truncated_device(tmp_path):
    raw = b"expected bytes" * 4096
    image = tmp_path / "rosy.img.xz"
    device = tmp_path / "physical-drive.fixture"
    image.write_bytes(lzma.compress(raw))
    device.write_bytes(raw[:-1])

    completed = _run(image, device)

    assert completed.returncode != 0
    assert "shorter" in completed.stderr.lower()
