import base64
import hashlib
import importlib
import json
import io
import subprocess
import tarfile
from types import SimpleNamespace

import pytest

from deploy.site.build_candidate import DEPLOY_FILES, DOC_FILES


COMMIT = "a" * 40
SERVICES = ("fleet", "vision", "proxy")
TEST_KEY_ID = "rosy-site-test-1"


def _load_verifier():
    return importlib.import_module("deploy.site.verify_candidate")


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _image_blobs(service: str, config_digest: str | None = None):
    """Config blob and an OCI image manifest blob that names a config digest."""
    config = json.dumps({"architecture": "amd64", "os": "linux", "service": service}).encode()
    image_manifest = json.dumps({
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "config": {"mediaType": "application/vnd.oci.image.config.v1+json",
                   "digest": config_digest or _sha(config), "size": len(config)},
        "layers": [],
    }).encode()
    return config, image_manifest


def _write_images_tar(path, *, with_index=True, overrides=None):
    """Write a docker-save shaped archive; return {service: (config_id, manifest_id)}.

    overrides[service] may set "manifest" (bytes stored as the manifest blob) or
    "index_digest" (digest written into index.json) to build bad archives.
    """
    overrides = overrides or {}
    files: dict[str, bytes] = {}
    docker_manifest, index_rows, ids = [], [], {}
    for service in SERVICES:
        reference = f"rosy-site-{service}:{COMMIT}"
        config, image_manifest = _image_blobs(service)
        config_id, manifest_id = _sha(config), _sha(image_manifest)
        ids[service] = (config_id, manifest_id)
        override = overrides.get(service, {})
        files[f"blobs/sha256/{config_id[7:]}"] = config
        index_digest = override.get("index_digest", manifest_id)
        files[f"blobs/sha256/{index_digest[7:]}"] = override.get("manifest", image_manifest)
        docker_manifest.append({"Config": f"blobs/sha256/{config_id[7:]}",
                                "RepoTags": [reference], "Layers": []})
        index_rows.append({
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "digest": index_digest,
            "size": len(image_manifest),
            "annotations": {"io.containerd.image.name": f"docker.io/library/{reference}",
                            "org.opencontainers.image.ref.name": COMMIT},
        })
    files["manifest.json"] = json.dumps(docker_manifest).encode()
    if with_index:
        files["index.json"] = json.dumps({"schemaVersion": 2, "manifests": index_rows}).encode()
    with tarfile.open(path, "w") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return ids


def _reseal_archive(root):
    """Record the rewritten archive hash, as a re-signed manifest would."""
    manifest_path = root / "release.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["image_archive_sha256"] = hashlib.sha256(
        (root / "images.tar").read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def _verify_with(candidate, loaded_ids):
    root, _, _, trusted_key = candidate

    def runner(args, **kwargs):
        if "pkeyutl" in args:
            return SimpleNamespace(returncode=0, stdout="")
        service = args[-1].split(":", 1)[0].removeprefix("rosy-site-")
        return SimpleNamespace(stdout=f"{loaded_ids[service]}|linux|amd64\n")

    return _load_verifier().verify_candidate(
        root, trusted_key_id=TEST_KEY_ID, trusted_public_key=trusted_key, runner=runner,
    )


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

    archive = root / "images.tar"
    archive_ids = _write_images_tar(archive)
    image_rows = {}
    image_ids = {}
    for service in SERVICES:
        image_id = archive_ids[service][0]
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


def test_classic_store_config_digest_id_passes(candidate):
    image_ids = candidate[2]
    summary = _verify_with(candidate, image_ids)

    assert summary["image_ids"] == image_ids
    assert summary["id_form"] == {service: "config" for service in SERVICES}


def test_containerd_store_oci_manifest_digest_id_passes(candidate):
    root = candidate[0]
    ids = _write_images_tar(root / "images.tar")
    _reseal_archive(root)
    loaded = {service: ids[service][1] for service in SERVICES}

    summary = _verify_with(candidate, loaded)

    assert summary["image_ids"] == loaded
    assert summary["id_form"] == {service: "oci-manifest" for service in SERVICES}


def test_archive_without_index_accepts_only_config_form(candidate):
    root = candidate[0]
    ids = _write_images_tar(root / "images.tar", with_index=False)
    _reseal_archive(root)

    assert _verify_with(candidate, candidate[2])["id_form"]["fleet"] == "config"
    loaded = {service: ids[service][1] for service in SERVICES}
    with pytest.raises(ValueError, match="fleet loaded image ID mismatch"):
        _verify_with(candidate, loaded)


def test_loaded_id_equal_to_another_archive_digest_fails(candidate):
    root = candidate[0]
    ids = _write_images_tar(root / "images.tar")
    _reseal_archive(root)
    loaded = dict(candidate[2])
    loaded["vision"] = ids["fleet"][1]

    with pytest.raises(ValueError, match="vision loaded image ID mismatch"):
        _verify_with(candidate, loaded)


def test_index_manifest_whose_config_is_not_the_signed_image_id_fails(candidate):
    root = candidate[0]
    _, other = _image_blobs("fleet", config_digest="sha256:" + "e" * 64)
    _write_images_tar(root / "images.tar", overrides={
        "fleet": {"manifest": other, "index_digest": _sha(other)}})
    _reseal_archive(root)

    with pytest.raises(ValueError, match="fleet image archive/manifest mismatch"):
        _verify_with(candidate, candidate[2])


def test_manifest_blob_not_matching_index_digest_fails(candidate):
    root = candidate[0]
    _, tampered = _image_blobs("proxy", config_digest="sha256:" + "d" * 64)
    _write_images_tar(root / "images.tar", overrides={"proxy": {"manifest": tampered}})
    _reseal_archive(root)

    with pytest.raises(ValueError, match="blob digest mismatch: proxy image manifest"):
        _verify_with(candidate, candidate[2])


def test_archive_member_link_is_rejected(candidate):
    root = candidate[0]
    archive = root / "images.tar"
    data = archive.read_bytes()
    with tarfile.open(archive, "w") as tar:
        with tarfile.open(fileobj=io.BytesIO(data)) as source:
            for member in source:
                if member.name == "index.json":
                    link = tarfile.TarInfo("index.json")
                    link.type = tarfile.SYMTYPE
                    link.linkname = "manifest.json"
                    tar.addfile(link)
                else:
                    tar.addfile(member, source.extractfile(member))
    _reseal_archive(root)

    with pytest.raises(ValueError, match="unsafe image archive member: index.json"):
        _verify_with(candidate, candidate[2])


def test_archive_is_not_parsed_before_its_signed_hash_matches(candidate, monkeypatch):
    root = candidate[0]
    verifier = _load_verifier()
    (root / "images.tar").write_bytes(b"not a tar")

    def must_not_parse(*args, **kwargs):
        raise AssertionError("archive parsed before hash check")

    monkeypatch.setattr(verifier, "_archive_image_ids", must_not_parse)
    with pytest.raises(ValueError, match="image archive hash mismatch"):
        _verify(candidate)
