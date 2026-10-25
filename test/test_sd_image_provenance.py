"""Real signatures bind the SD image's source, not the operator checkout."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from signing import sign_checksums


ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "deploy/robot/pinky_pro/sd/verify-image-release.py"
REVISION = "a" * 40
RELEASE = "2026.10.25-001"


@pytest.fixture
def verifier():
    spec = importlib.util.spec_from_file_location("sd_image_provenance", VERIFIER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def signed_image(tmp_path):
    private, public = tmp_path / "private.pem", tmp_path / "public.pem"
    for command in (
        ["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(private)],
        ["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)],
    ):
        subprocess.run(command, check=True, capture_output=True, timeout=30)
    dist = tmp_path / "dist"
    dist.mkdir()
    image = dist / f"rosy-os-pinky-pro-{RELEASE}-arm64.img.xz"
    image.write_bytes(b"fixture compressed image")
    manifest = {"schema_version": 1, "release_id": RELEASE, "product": "rosy-os",
                "board": "pinky_pro", "architecture": "arm64",
                "image": {"filename": image.name, "sha256": hashlib.sha256(image.read_bytes()).hexdigest()}}
    (dist / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (dist / "source-revision.txt").write_text(REVISION + "\n", encoding="ascii")
    provenance = {"release_id": RELEASE, "source_revision": REVISION,
                  "architecture": "aarch64", "builder": "native-arm64"}
    (dist / "build-provenance.json").write_text(json.dumps(provenance), encoding="utf-8")

    def seal():
        names = sorted(p.name for p in dist.iterdir() if p.name not in {"SHA256SUMS", "SHA256SUMS.sig"})
        sums = "".join(f"{hashlib.sha256((dist / name).read_bytes()).hexdigest()}  {name}\n" for name in names)
        (dist / "SHA256SUMS").write_text(sums, encoding="ascii")
        signature = dist / "SHA256SUMS.sig"
        signature.unlink(missing_ok=True)
        signature.write_text(sign_checksums(sums.encode("ascii"), private), encoding="ascii")

    seal()
    return dist, public, image, seal


def test_returns_the_signed_image_source(verifier, signed_image):
    dist, public, image, _ = signed_image
    report = verifier.verify_image_release(dist, public, image, RELEASE)
    assert report["source_revision"] == REVISION


@pytest.mark.parametrize("name", ["source-revision.txt", "build-provenance.json"])
def test_missing_source_evidence_fails_even_when_release_is_signed(verifier, signed_image, name):
    dist, public, image, seal = signed_image
    (dist / name).unlink()
    seal()
    with pytest.raises(ValueError, match="SOURCE"):
        verifier.verify_image_release(dist, public, image, RELEASE)


@pytest.mark.parametrize("change", ["revision", "release", "malformed-source", "malformed-provenance"])
def test_signed_but_inconsistent_provenance_is_rejected(verifier, signed_image, change):
    dist, public, image, seal = signed_image
    if change == "malformed-source":
        (dist / "source-revision.txt").write_text("HEAD\n", encoding="ascii")
    elif change == "malformed-provenance":
        (dist / "build-provenance.json").write_text("[]", encoding="ascii")
    else:
        path = dist / "build-provenance.json"
        data = json.loads(path.read_text())
        data["source_revision" if change == "revision" else "release_id"] = "b" * 40
        path.write_text(json.dumps(data), encoding="utf-8")
    seal()
    with pytest.raises(ValueError, match="SOURCE"):
        verifier.verify_image_release(dist, public, image, RELEASE)


def test_expected_source_is_an_exact_release_pin(verifier, signed_image):
    dist, public, image, _ = signed_image
    assert verifier.verify_image_release(dist, public, image, RELEASE, REVISION)["source_revision"] == REVISION
    with pytest.raises(ValueError, match="SOURCE_REVISION"):
        verifier.verify_image_release(dist, public, image, RELEASE, "b" * 40)
    with pytest.raises(ValueError, match="SOURCE_REVISION"):
        verifier.verify_image_release(dist, public, image, RELEASE, "HEAD")


def test_unsigned_source_edit_is_rejected(verifier, signed_image):
    dist, public, image, _ = signed_image
    (dist / "source-revision.txt").write_text("b" * 40 + "\n", encoding="ascii")
    with pytest.raises(ValueError):
        verifier.verify_image_release(dist, public, image, RELEASE)


def test_aba_checksum_replacement_cannot_authenticate_a_different_snapshot(verifier, signed_image, monkeypatch):
    dist, public, image, _ = signed_image
    trusted = {p.name: p.read_bytes() for p in dist.iterdir()}
    image.write_bytes(b"unsigned replacement image")
    source = "b" * 40
    (dist / "source-revision.txt").write_text(source, encoding="ascii")
    path = dist / "build-provenance.json"
    data = json.loads(path.read_text())
    data["source_revision"] = source
    path.write_text(json.dumps(data), encoding="utf-8")
    path = dist / "manifest.json"
    data = json.loads(path.read_text())
    data["image"]["sha256"] = hashlib.sha256(image.read_bytes()).hexdigest()
    path.write_text(json.dumps(data), encoding="utf-8")
    sums = dist / "SHA256SUMS"
    names = sorted(name for name in trusted if name not in {"SHA256SUMS", "SHA256SUMS.sig"})
    sums.write_text("".join(f"{hashlib.sha256((dist / name).read_bytes()).hexdigest()}  {name}\n"
                            for name in names), encoding="ascii")
    forged = {p.name: p.read_bytes() for p in dist.iterdir()}
    original_read = Path.read_bytes
    reads = 0

    def swap_at_checksum_read(path):
        nonlocal reads
        if path == sums:
            reads += 1
            snapshot = trusted if reads == 2 else forged if reads == 3 else None
            if snapshot:
                for name, content in snapshot.items():
                    (dist / name).write_bytes(content)
        return original_read(path)

    monkeypatch.setattr(Path, "read_bytes", swap_at_checksum_read)
    with pytest.raises(ValueError, match="SIGNATURE|CHECKSUM"):
        verifier.verify_image_release(dist, public, image, RELEASE, source)


@pytest.mark.parametrize("broken", ["signature", "image"])
def test_shared_verifier_never_returns_unverified_entries(signed_image, broken):
    import signing

    dist, public, image, _ = signed_image
    if broken == "signature":
        (dist / "SHA256SUMS.sig").write_text("invalid signature", encoding="ascii")
    else:
        image.write_bytes(b"unsigned changes")
    entries, rejections = signing.verify_release_checksums(dist, public)
    assert rejections
    assert entries == {}


def test_cli_checks_the_expected_source_and_reports_it(signed_image):
    dist, public, image, _ = signed_image
    command = [sys.executable, str(VERIFIER), "--release-root", str(dist), "--public-key", str(public),
               "--image", str(image), "--release-id", RELEASE, "--expected-source-revision"]
    good = subprocess.run([*command, REVISION], capture_output=True, text=True, timeout=30)
    assert good.returncode == 0, good.stderr
    assert json.loads(good.stdout)["source_revision"] == REVISION
    stale = subprocess.run([*command, "b" * 40], capture_output=True, text=True, timeout=30)
    assert stale.returncode == 1
    assert "SOURCE_REVISION" in stale.stderr


def test_image_is_read_once_and_tampering_still_fails(verifier, signed_image, monkeypatch):
    dist, public, image, _ = signed_image
    original_open = Path.open
    reads = []

    def observe(path, mode="r", *args, **kwargs):
        if path == image and mode == "rb":
            reads.append(path)
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", observe)
    verifier.verify_image_release(dist, public, image, RELEASE)
    assert len(reads) == 1, "the release verifier already checks every image byte"
    image.write_bytes(b"tampered image")
    with pytest.raises(ValueError):
        verifier.verify_image_release(dist, public, image, RELEASE)
