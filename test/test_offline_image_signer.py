"""Contracts for the offline image-release signer CLI."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from signing import build_sha256sums, verify_release_files, verify_signature


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


# --- D-225 2.2: the factory release's checksum list is signed with the same key.

FACTORY_ID = "2026.09.25-001"
FACTORY = f"factory-release/{FACTORY_ID}"


def _image_release(directory: Path, *, manifest_id: str = FACTORY_ID) -> Path:
    """An unsigned dist as create-image-manifest.py leaves it, factory export included."""
    root = directory / "release"
    factory = root / FACTORY
    factory.mkdir(parents=True)
    (root / "manifest.json").write_text('{"schema_version": 1}\n', encoding="utf-8")
    (root / "image.img.xz").write_bytes(b"verified image fixture")
    (factory / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "release_id": manifest_id}) + "\n", encoding="utf-8")
    (factory / "install.txt").write_text("payload\n", encoding="utf-8")
    (factory / "SHA256SUMS").write_bytes(build_sha256sums(factory, ["install.txt", "manifest.json"]))
    (factory / "install.txt").unlink()  # the payload lives in the image, not the dist
    (root / "SHA256SUMS").write_bytes(build_sha256sums(
        root, ["image.img.xz", "manifest.json", f"{FACTORY}/SHA256SUMS", f"{FACTORY}/manifest.json"]))
    return root


def test_offline_signer_signs_the_factory_list_and_covers_its_signature(tmp_path):
    root = _image_release(tmp_path)
    private, public = _keys(tmp_path, "release")
    factory_sums = (root / FACTORY / "SHA256SUMS").read_bytes()

    completed = _run(root, private, public)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(completed.stdout)
    assert report["factory_releases"] == [FACTORY_ID]
    assert verify_release_files(root, public) == []
    factory_sig = (root / FACTORY / "SHA256SUMS.sig").read_text(encoding="ascii")
    assert verify_signature(factory_sums, factory_sig, public) == []
    assert (root / FACTORY / "SHA256SUMS").read_bytes() == factory_sums
    listed = [line.split("  ", 1)[1] for line in (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines()]
    assert f"{FACTORY}/SHA256SUMS.sig" in listed and listed == sorted(listed)


def test_offline_signer_rolls_back_every_signature_when_the_key_does_not_match(tmp_path):
    root = _image_release(tmp_path)
    private, _ = _keys(tmp_path, "release")
    _, wrong_public = _keys(tmp_path, "wrong")
    original = (root / "SHA256SUMS").read_bytes()

    completed = _run(root, private, wrong_public)

    assert completed.returncode == 2
    assert "SIGNATURE_INVALID" in completed.stdout
    assert not (root / "SHA256SUMS.sig").exists()
    assert not (root / FACTORY / "SHA256SUMS.sig").exists()
    assert (root / "SHA256SUMS").read_bytes() == original


def test_offline_signer_refuses_an_already_signed_or_foreign_factory_release(tmp_path):
    private, public = _keys(tmp_path, "release")
    signed = _image_release(tmp_path / "a")
    (signed / FACTORY / "SHA256SUMS.sig").write_text("existing\n", encoding="ascii")
    foreign = _image_release(tmp_path / "b", manifest_id="2026.09.25-002")

    refused_signed = _run(signed, private, public)
    refused_foreign = _run(foreign, private, public)

    # A pre-existing factory signature is unlisted, so the outer check refuses first.
    assert refused_signed.returncode == 2 and "CHECKSUM_UNLISTED_FILE" in refused_signed.stdout
    assert (signed / FACTORY / "SHA256SUMS.sig").read_text(encoding="ascii") == "existing\n"
    assert refused_foreign.returncode == 2 and "FACTORY_RELEASE" in refused_foreign.stdout
    for root in (signed, foreign):
        assert not (root / "SHA256SUMS.sig").exists()
    assert not (foreign / FACTORY / "SHA256SUMS.sig").exists()
