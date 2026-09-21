"""Contracts for the offline image-release signer CLI."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from signing import build_sha256sums, verify_release_files


ROOT = Path(__file__).resolve().parents[1]
SIGNER = ROOT / "deploy" / "release" / "sign_image_release.py"


def _keys(directory: Path, name: str) -> tuple[Path, Path]:
    private = directory / f"{name}.private.pem"
    public = directory / f"{name}.public.pem"
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(private)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)],
        check=True,
        capture_output=True,
    )
    return private, public


def _release(directory: Path) -> Path:
    root = directory / "release"
    root.mkdir()
    (root / "manifest.json").write_text('{"schema_version": 1}\n', encoding="utf-8")
    (root / "image.img.xz").write_bytes(b"verified image fixture")
    sums = build_sha256sums(root, ["image.img.xz", "manifest.json"])
    (root / "SHA256SUMS").write_bytes(sums)
    return root


def _run(root: Path, private: Path, public: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SIGNER),
            str(root),
            "--private-key",
            str(private),
            "--public-key",
            str(public),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_offline_signer_verifies_payload_then_writes_a_valid_signature(tmp_path):
    root = _release(tmp_path)
    private, public = _keys(tmp_path, "release")

    completed = _run(root, private, public)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(completed.stdout)
    assert report["ok"] is True and report["files_verified"] == 2
    assert verify_release_files(root, public) == []


def test_offline_signer_rejects_tampering_before_creating_a_signature(tmp_path):
    root = _release(tmp_path)
    private, public = _keys(tmp_path, "release")
    (root / "image.img.xz").write_bytes(b"tampered")

    completed = _run(root, private, public)

    assert completed.returncode == 2
    assert "CHECKSUM_MISMATCH" in completed.stdout
    assert not (root / "SHA256SUMS.sig").exists()


def test_offline_signer_removes_signature_when_public_key_does_not_match(tmp_path):
    root = _release(tmp_path)
    private, _ = _keys(tmp_path, "release")
    _, wrong_public = _keys(tmp_path, "wrong")

    completed = _run(root, private, wrong_public)

    assert completed.returncode == 2
    assert "SIGNATURE_INVALID" in completed.stdout
    assert not (root / "SHA256SUMS.sig").exists()


def test_offline_signer_never_replaces_an_existing_signature(tmp_path):
    root = _release(tmp_path)
    private, public = _keys(tmp_path, "release")
    signature = root / "SHA256SUMS.sig"
    signature.write_text("existing\n", encoding="ascii")

    completed = _run(root, private, public)

    assert completed.returncode == 2
    assert "SIGNATURE_EXISTS" in completed.stdout
    assert signature.read_text(encoding="ascii") == "existing\n"
