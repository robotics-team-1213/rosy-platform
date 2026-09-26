import base64
import hashlib
import importlib
import json
import subprocess
from types import SimpleNamespace

import pytest

from deploy.site.build_candidate import DEPLOY_FILES, DOC_FILES


COMMIT = "a" * 40
SERVICES = ("fleet", "vision", "proxy")
TEST_KEY_ID = "rosy-site-test-1"


def _load_verifier():
    return importlib.import_module("deploy.site.verify_candidate")


@pytest.fixture
def candidate(tmp_path):
    root = tmp_path / "candidate"
    deploy = root / "deploy" / "site"
    sbom_dir = root / "sbom"
    docs = root / "docs" / "reference"
    deploy.mkdir(parents=True)
    sbom_dir.mkdir()
    docs.mkdir(parents=True)

    deploy_files = (*DEPLOY_FILES, "verify_candidate.py")
    for name in deploy_files:
        (deploy / name).write_text(f"candidate:{name}\n", encoding="utf-8")
    (deploy / ".env.example").write_text(
        f"ROSY_SITE_IMAGE_TAG={COMMIT}\n", encoding="utf-8")
    for name in DOC_FILES:
        (root / name).write_text(f"candidate:{name}\n", encoding="utf-8")

    image_rows = {}
    image_ids = {}
    for offset, service in enumerate(SERVICES, start=1):
        image_id = "sha256:" + str(offset) * 64
        image_ids[service] = image_id
        sbom_path = sbom_dir / f"{service}.spdx"
        sbom_path.write_text(f"SPDX for {service}\n", encoding="utf-8")
        image_rows[service] = {
            "reference": f"rosy-site-{service}:{COMMIT}",
            "image_id": image_id,
            "platform": "linux/amd64",
            "sbom": f"sbom/{service}.spdx",
            "sbom_sha256": hashlib.sha256(sbom_path.read_bytes()).hexdigest(),
        }

    archive = root / "images.tar"
    archive.write_bytes(b"candidate-image-archive")
    signature = {
        "signature_version": 1,
        "signing_key_id": TEST_KEY_ID,
        "signature": base64.b64encode(bytes(64)).decode("ascii"),
    }
    (root / "release.json.sig").write_text(json.dumps(signature), encoding="ascii")
    trusted_key = root / "test-trusted-site-key.pem"
    trusted_key.write_text("test public key fixture", encoding="ascii")
    file_hashes = {
        name: hashlib.sha256((deploy / name).read_bytes()).hexdigest()
        for name in deploy_files
    }
    file_hashes.update({
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in DOC_FILES
    })
    manifest = {
        "manifest_version": 1,
        "source_commit": COMMIT,
        "image_tag": COMMIT,
        "platform": "linux/amd64",
        "images": image_rows,
        "image_archive": "images.tar",
        "image_archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "deployment_file_sha256": file_hashes,
    }
    (root / "release.json").write_text(json.dumps(manifest), encoding="utf-8")

    def runner(args, **kwargs):
        if "pkeyutl" in args and "-verify" in args:
            return SimpleNamespace(returncode=0, stdout="Signature Verified Successfully\n")
        reference = args[-1]
        service = reference.split(":", 1)[0].removeprefix("rosy-site-")
        return SimpleNamespace(stdout=f"{image_ids[service]}|linux|amd64\n")

    return root, runner, image_ids, trusted_key


def _verify(candidate):
    root, runner, _, trusted_key = candidate
    return _load_verifier().verify_candidate(
        root, trusted_key_id=TEST_KEY_ID, trusted_public_key=trusted_key, runner=runner,
    )


def test_verifies_manifest_files_sboms_archive_and_loaded_image_ids(candidate):
    root, _, image_ids, _ = candidate
    summary = _verify(candidate)

    assert summary["source_commit"] == COMMIT
    assert summary["verified_images"] == list(SERVICES)
    assert summary["image_ids"] == image_ids


def test_signature_only_check_finishes_before_any_docker_inspect(candidate):
    root, _, image_ids, trusted_key = candidate

    def no_docker(args, **kwargs):
        assert "pkeyutl" in args and "-verify" in args
        return SimpleNamespace(returncode=0, stdout="")

    summary = _load_verifier().verify_candidate(
        root, trusted_key_id=TEST_KEY_ID, trusted_public_key=trusted_key,
        runner=no_docker, inspect_loaded_images=False,
    )
    assert summary["manifest_image_ids"] == image_ids
    assert "image_ids" not in summary


def test_content_check_uses_the_exact_manifest_bytes_that_were_verified(candidate, monkeypatch):
    root, _, _, trusted_key = candidate
    verifier = _load_verifier()
    original = (root / "release.json").read_bytes()

    def verify_then_replace(manifest_bytes, envelope_bytes, **kwargs):
        assert manifest_bytes == original
        (root / "release.json").write_bytes(b'{"manifest_version": 999}')

    monkeypatch.setattr(verifier, "verify_manifest_signature", verify_then_replace)
    result = verifier.verify_candidate(
        root, trusted_key_id=TEST_KEY_ID, trusted_public_key=trusted_key,
        runner=candidate[1], inspect_loaded_images=False,
    )
    assert result["source_commit"] == COMMIT


def test_rejects_changed_deployment_file(candidate):
    root, _, _, _ = candidate
    (root / "deploy/site/compose.yaml").write_text("changed\n", encoding="utf-8")

    with pytest.raises(ValueError, match="deployment file hash mismatch"):
        _verify(candidate)


def test_rejects_changed_image_archive(candidate):
    root, _, _, _ = candidate
    (root / "images.tar").write_bytes(b"changed")

    with pytest.raises(ValueError, match="image archive hash mismatch"):
        _verify(candidate)


def test_rejects_changed_sbom(candidate):
    root, _, _, _ = candidate
    (root / "sbom/fleet.spdx").write_text("changed\n", encoding="utf-8")

    with pytest.raises(ValueError, match="fleet SBOM hash mismatch"):
        _verify(candidate)


def test_rejects_unsafe_manifest_paths(candidate):
    root, _, _, _ = candidate
    manifest_path = root / "release.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["deployment_file_sha256"]["../outside"] = "b" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported deployment file path"):
        _verify(candidate)


def test_rejects_wrong_loaded_image_id(candidate):
    root, _, _, _ = candidate

    def runner(args, **kwargs):
        if "pkeyutl" in args:
            return SimpleNamespace(returncode=0, stdout="")
        reference = args[-1]
        service = reference.split(":", 1)[0].removeprefix("rosy-site-")
        if service == "fleet":
            return SimpleNamespace(stdout="sha256:" + "f" * 64 + "|linux|amd64\n")
        return candidate[1](args, **kwargs)

    with pytest.raises(ValueError, match="fleet loaded image ID mismatch"):
        _load_verifier().verify_candidate(
            root, trusted_key_id=TEST_KEY_ID, trusted_public_key=candidate[3], runner=runner,
        )


def test_rejects_wrong_loaded_image_platform(candidate):
    root, _, _, _ = candidate

    def wrong_arch(args, **kwargs):
        if "pkeyutl" in args:
            return SimpleNamespace(returncode=0, stdout="")
        result = candidate[1](args, **kwargs)
        if args[-1].startswith("rosy-site-vision:"):
            return SimpleNamespace(stdout=result.stdout.replace("amd64", "arm64"))
        return result

    with pytest.raises(ValueError, match="vision loaded platform mismatch"):
        _load_verifier().verify_candidate(
            root, trusted_key_id=TEST_KEY_ID, trusted_public_key=candidate[3], runner=wrong_arch,
        )


def test_reports_docker_inspect_failure_without_leaking_command_data(candidate):
    root, _, _, trusted_key = candidate

    def missing_image(args, **kwargs):
        if "pkeyutl" in args:
            return SimpleNamespace(returncode=0, stdout="")
        raise subprocess.CalledProcessError(1, args, stderr="No such image")

    with pytest.raises(ValueError, match="docker image inspection failed for fleet"):
        _load_verifier().verify_candidate(
            root, trusted_key_id=TEST_KEY_ID, trusted_public_key=trusted_key, runner=missing_image,
        )


def test_rejects_unsigned_candidate(candidate):
    root, _, _, _ = candidate
    (root / "release.json.sig").unlink()

    with pytest.raises(ValueError, match="release signature is missing"):
        _verify(candidate)


def test_rejects_signature_from_untrusted_key_id(candidate):
    root, _, _, trusted_key = candidate

    with pytest.raises(ValueError, match="trusted signing key ID mismatch"):
        _load_verifier().verify_candidate(
            root, trusted_key_id="untrusted-site-key", trusted_public_key=trusted_key,
            runner=candidate[1],
        )
