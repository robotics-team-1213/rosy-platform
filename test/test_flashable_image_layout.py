"""Contracts for final `.img.xz` layout and unsigned release handoff."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
IMAGE_DIR = ROOT / "deploy" / "image"
FINALIZE = IMAGE_DIR / "finalize-image.sh"
MANIFEST = IMAGE_DIR / "create-image-manifest.py"
WORKFLOW = ROOT / ".github/workflows/build-pinky-image.yml"


def test_finalizer_checks_filesystem_before_deterministic_compression():
    text = FINALIZE.read_text(encoding="utf-8")
    assert "e2fsck -fn" in text
    assert "losetup --detach" in text
    assert text.index("losetup --detach") < text.index("xz --threads=0")
    assert "--check=crc64" in text and "-9e" in text
    assert "bmaptool create" in text
    assert "rm -f -- \"$RAW\"" in text


def test_manifest_builder_emits_exact_signed_handoff(tmp_path):
    release_id = "2026.09.22-001"
    revision = "a" * 40
    dist = tmp_path / "dist"
    payload = tmp_path / "payload"
    dist.mkdir()
    payload.mkdir()
    image = dist / f"rosy-os-pinky-pro-{release_id}-arm64.img.xz"
    image.write_bytes(b"compressed-image-fixture")
    (dist / f"rosy-os-pinky-pro-{release_id}-arm64.img.bmap").write_text("bmap\n", encoding="utf-8")
    (payload / "deb-packages.txt").write_text("python3\t3.12\n", encoding="utf-8")
    (payload / "rosy-packages.txt").write_text("core\ncontrol\n", encoding="utf-8")
    (payload / "required-ros-packages.txt").write_text("core\ncontrol\n", encoding="utf-8")
    (payload / "source-revision.txt").write_text(revision + "\n", encoding="utf-8")
    lock = tmp_path / "inputs.lock.yaml"
    lock.write_text("schema_version: 1\n", encoding="utf-8")

    completed = subprocess.run([
        sys.executable, str(MANIFEST), "--dist", str(dist), "--payload", str(payload),
        "--lock", str(lock), "--release-id", release_id,
        "--source-revision", revision,
    ], capture_output=True, text=True, check=False)

    assert completed.returncode == 0, completed.stderr
    required = {
        "manifest.json", "SHA256SUMS", "sbom.spdx.json", "deb-packages.txt",
        "rosy-packages.txt", "required-ros-packages.txt", "source-revision.txt",
        "base-image-provenance.json", "build-provenance.json", "artifact-report.md",
        "release-notes.md", image.name,
        f"rosy-os-pinky-pro-{release_id}-arm64.img.bmap",
    }
    assert required <= {path.name for path in dist.iterdir()}
    assert not (dist / "SHA256SUMS.sig").exists()
    manifest = json.loads((dist / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["board"] == "pinky_pro"
    assert manifest["architecture"] == "arm64"
    assert manifest["image"] == {
        "filename": image.name,
        "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
    }
    sums = (dist / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    listed = [line.split("  ", 1)[1] for line in sums]
    assert listed == sorted(required - {"SHA256SUMS"})
    assert "PENDING_OFFLINE" in (dist / "artifact-report.md").read_text(encoding="utf-8")


def test_native_arm64_workflow_builds_only_an_unsigned_handoff():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "runs-on: ubuntu-24.04-arm" in text
    assert "deploy/image/build-image.sh" in text
    assert "SHA256SUMS.sig" in text and "test ! -e" in text
    assert "private" not in text.lower()
    assert "actions/upload-artifact@v4" in text
    assert 'sudo git config --global --add safe.directory "$GITHUB_WORKSPACE"' in text
    assert text.index('sudo dpkg -i "$ros_source"') < text.index(
        "python3-colcon-common-extensions"
    )
