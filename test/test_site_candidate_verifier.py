import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from deploy.site.build_candidate import DEPLOY_FILES, DOC_FILES


COMMIT = "a" * 40
SERVICES = ("fleet", "vision", "proxy")


def _load_verifier():
    module_path = Path(__file__).resolve().parents[1] / "deploy" / "site" / "verify_candidate.py"
    assert module_path.is_file(), "site candidate host verifier is missing"
    spec = importlib.util.spec_from_file_location("site_verify_candidate", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
        reference = args[-1]
        service = reference.split(":", 1)[0].removeprefix("rosy-site-")
        return SimpleNamespace(stdout=f"{image_ids[service]}|linux|amd64\n")

    return root, runner, image_ids


def test_verifies_manifest_files_sboms_archive_and_loaded_image_ids(candidate):
    root, runner, image_ids = candidate
    summary = _load_verifier().verify_candidate(root, runner=runner)

    assert summary["source_commit"] == COMMIT
    assert summary["verified_images"] == list(SERVICES)
    assert summary["image_ids"] == image_ids


def test_rejects_changed_deployment_file(candidate):
    root, runner, _ = candidate
    (root / "deploy/site/compose.yaml").write_text("changed\n", encoding="utf-8")

    with pytest.raises(ValueError, match="deployment file hash mismatch"):
        _load_verifier().verify_candidate(root, runner=runner)


def test_rejects_changed_image_archive(candidate):
    root, runner, _ = candidate
    (root / "images.tar").write_bytes(b"changed")

    with pytest.raises(ValueError, match="image archive hash mismatch"):
        _load_verifier().verify_candidate(root, runner=runner)


def test_rejects_changed_sbom(candidate):
    root, runner, _ = candidate
    (root / "sbom/fleet.spdx").write_text("changed\n", encoding="utf-8")

    with pytest.raises(ValueError, match="fleet SBOM hash mismatch"):
        _load_verifier().verify_candidate(root, runner=runner)


def test_rejects_unsafe_manifest_paths(candidate):
    root, runner, _ = candidate
    manifest_path = root / "release.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["deployment_file_sha256"]["../outside"] = "b" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported deployment file path"):
        _load_verifier().verify_candidate(root, runner=runner)


def test_rejects_wrong_loaded_image_id(candidate):
    root, runner, _ = candidate

    def wrong_id(args, **kwargs):
        result = runner(args, **kwargs)
        if args[-1].startswith("rosy-site-fleet:"):
            return SimpleNamespace(stdout="sha256:" + "f" * 64 + "|linux|amd64\n")
        return result

    with pytest.raises(ValueError, match="fleet loaded image ID mismatch"):
        _load_verifier().verify_candidate(root, runner=wrong_id)


def test_rejects_wrong_loaded_image_platform(candidate):
    root, runner, _ = candidate

    def wrong_arch(args, **kwargs):
        result = runner(args, **kwargs)
        if args[-1].startswith("rosy-site-vision:"):
            return SimpleNamespace(stdout=result.stdout.replace("amd64", "arm64"))
        return result

    with pytest.raises(ValueError, match="vision loaded platform mismatch"):
        _load_verifier().verify_candidate(root, runner=wrong_arch)


def test_reports_docker_inspect_failure_without_leaking_command_data(candidate):
    root, _, _ = candidate

    def missing_image(args, **kwargs):
        raise subprocess.CalledProcessError(1, args, stderr="No such image")

    with pytest.raises(ValueError, match="docker image inspection failed for fleet"):
        _load_verifier().verify_candidate(root, runner=missing_image)
