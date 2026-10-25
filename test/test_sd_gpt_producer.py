"""Unsigned GPT prototypes must be inspected and never pass production BUILD_GO."""
import hashlib
import json
import lzma
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from test_sd_gpt_layout import _table_image

ROOT = Path(__file__).resolve().parents[1]
IMAGE = ROOT / "deploy/robot/pinky_pro/image"
RELEASE = "2026.10.25-001"


@pytest.fixture
def producer(tmp_path):
    dist, payload = tmp_path / "dist", tmp_path / "payload"
    dist.mkdir()
    payload.mkdir()
    raw, layout = _table_image()
    image = dist / f"rosy-os-pinky-pro-{RELEASE}-arm64.img.xz"
    image.write_bytes(lzma.compress(raw))
    for name in ("deb-packages.txt", "rosy-packages.txt", "required-ros-packages.txt", "source-revision.txt"):
        (payload / name).write_text("", encoding="utf-8")
    factory = payload / "factory-release"
    factory.mkdir(parents=True)
    manifest = json.dumps({"release_id": RELEASE}).encode()
    (factory / "manifest.json").write_bytes(manifest)
    (factory / "SHA256SUMS").write_text(hashlib.sha256(manifest).hexdigest() + "  manifest.json\n")
    lock = tmp_path / "inputs.lock.yaml"
    lock.write_text("fixture: true\n")
    snapshot = tmp_path / "layout.json"
    snapshot.write_text(json.dumps(layout))
    return dist, payload, lock, snapshot, image, layout


def _produce(case, *extra):
    dist, payload, lock, *_ = case
    return subprocess.run([sys.executable, str(IMAGE / "create-image-manifest.py"),
                           "--dist", str(dist), "--payload", str(payload), "--lock", str(lock),
                           "--release-id", RELEASE, "--source-revision", "a" * 40, *map(str, extra)],
                          capture_output=True, text=True, timeout=30)


def test_producer_inspects_real_gpt_before_emitting_v2(producer):
    result = _produce(producer, "--layout-file", producer[3])
    assert result.returncode == 0, result.stderr
    manifest = json.loads((producer[0] / "manifest.json").read_text())
    assert manifest["schema_version"] == 2
    assert manifest["layout"] == producer[-1]
    sums = (producer[0] / "SHA256SUMS").read_text()
    assert hashlib.sha256((producer[0] / "manifest.json").read_bytes()).hexdigest() + "  manifest.json" in sums


def test_producer_does_not_seal_guessed_layout(producer):
    layout = producer[-1]
    layout["partitions"][0]["start_lba"] += 1
    producer[3].write_text(json.dumps(layout))
    result = _produce(producer, "--layout-file", producer[3])
    assert result.returncode != 0
    assert "LAYOUT" in result.stderr
    assert not (producer[0] / "manifest.json").exists()


def test_legacy_producer_stays_v1_without_layout(producer):
    result = _produce(producer)
    assert result.returncode == 0, result.stderr
    manifest = json.loads((producer[0] / "manifest.json").read_text())
    assert manifest["schema_version"] == 1
    assert "layout" not in manifest


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_production_gate_explicitly_refuses_ab_prototype_before_mount_or_key_use(producer):
    dist = producer[0]
    for name in ("SHA256SUMS", "SHA256SUMS.sig", "sbom.spdx.json", "release-notes.md", "fixture.bmap"):
        (dist / name).write_text("fixture\n")
    (dist / "manifest.json").write_text(json.dumps({"schema_version": 2, "layout": producer[-1]}))
    result = subprocess.run(["bash", str(IMAGE / "verify-artifacts.sh"), str(dist)],
                            capture_output=True, text=True, env=dict(os.environ, ROSY_PYTHON=sys.executable), timeout=30)
    assert result.returncode != 0
    assert "A/B prototype" in result.stderr
    assert "BUILD_GO checks passed" not in result.stdout
