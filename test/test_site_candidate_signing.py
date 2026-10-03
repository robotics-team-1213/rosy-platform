from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from deploy.site.build_candidate import DEPLOY_FILES, DOC_FILES
from deploy.site import sign_candidate as signer_module
from deploy.site.candidate_signing import (
    CandidateSignatureError,
    sign_manifest_bytes,
    verify_manifest_signature,
)
from deploy.site.sign_candidate import sign_candidate
from deploy.site.verify_candidate import verify_candidate

COMMIT = "a" * 40
TEST_KEY_ID = "rosy-site-test-1"
SERVICES = ("fleet", "vision", "proxy")


def _generate_key(directory: Path, name: str) -> tuple[Path, Path]:
    private = directory / f"{name}.key"
    public = directory / f"{name}.pub.pem"
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(private)],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)],
        check=True, capture_output=True,
    )
    return private, public


@pytest.fixture(scope="module")
def site_keys(tmp_path_factory) -> tuple[Path, Path, Path, Path]:
    directory = tmp_path_factory.mktemp("site-signing-keys")
    private, public = _generate_key(directory, "site")
    other_private, other_public = _generate_key(directory, "other")
    return private, public, other_private, other_public


def _make_candidate(root: Path) -> dict[str, str]:
    deploy = root / "deploy" / "site"
    deploy.mkdir(parents=True)
    for name in DEPLOY_FILES:
        path = deploy / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"ROSY_SITE_IMAGE_TAG={COMMIT}\n" if name == ".env.example" else f"fixture:{name}\n",
            encoding="utf-8",
        )
    for name in DOC_FILES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"fixture:{name}\n", encoding="utf-8")

    images = {}
    image_ids = {}
    archive_members = {}
    docker_manifest = []
    for service in SERVICES:
        config = f'{{"os": "linux", "service": "{service}"}}'.encode()
        image_id = "sha256:" + hashlib.sha256(config).hexdigest()
        image_ids[service] = image_id
        archive_members[f"blobs/sha256/{image_id[7:]}"] = config
        docker_manifest.append({"Config": f"blobs/sha256/{image_id[7:]}",
                                "RepoTags": [f"rosy-site-{service}:{COMMIT}"]})
        sbom = root / "sbom" / f"{service}.spdx"
        sbom.parent.mkdir(parents=True, exist_ok=True)
        sbom.write_text(f"SPDX {service}\n", encoding="utf-8")
        images[service] = {
            "reference": f"rosy-site-{service}:{COMMIT}",
            "image_id": image_id,
            "platform": "linux/amd64",
            "sbom": f"sbom/{service}.spdx",
            "sbom_sha256": hashlib.sha256(sbom.read_bytes()).hexdigest(),
        }
    archive = root / "images.tar"
    import io
    import json
    import tarfile

    archive_members["manifest.json"] = json.dumps(docker_manifest).encode()
    with tarfile.open(archive, "w") as tar:
        for name, data in archive_members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

    manifest = {
        "manifest_version": 1,
        "source_commit": COMMIT,
        "image_tag": COMMIT,
        "platform": "linux/amd64",
        "images": images,
        "image_archive": "images.tar",
        "image_archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "deployment_file_sha256": {
            name: hashlib.sha256((deploy / name).read_bytes()).hexdigest()
            for name in DEPLOY_FILES
        } | {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in DOC_FILES
        },
    }
    (root / "release.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    return image_ids


def test_detached_signature_round_trips_exact_manifest_bytes(site_keys):
    private, public, _, _ = site_keys
    manifest = b'{"source_commit":"abc"}\n'

    envelope = sign_manifest_bytes(
        manifest, key_id="rosy-site-test-1", private_key=private, public_key=public,
    )

    verify_manifest_signature(
        manifest, envelope, trusted_key_id="rosy-site-test-1", public_key=public,
    )


def test_signature_binds_trusted_key_id(site_keys):
    private, public, _, _ = site_keys
    manifest = b'{"source_commit":"abc"}\n'
    envelope = sign_manifest_bytes(
        manifest, key_id="rosy-site-test-1", private_key=private, public_key=public,
    )

    with pytest.raises(CandidateSignatureError, match="key ID mismatch"):
        verify_manifest_signature(
            manifest, envelope, trusted_key_id="rosy-site-test-2", public_key=public,
        )


def test_signature_rejects_manifest_byte_changes(site_keys):
    private, public, _, _ = site_keys
    manifest = b'{"source_commit":"abc"}\n'
    envelope = sign_manifest_bytes(
        manifest, key_id="rosy-site-test-1", private_key=private, public_key=public,
    )

    with pytest.raises(CandidateSignatureError, match="signature verification failed"):
        verify_manifest_signature(
            manifest + b" ", envelope,
            trusted_key_id="rosy-site-test-1", public_key=public,
        )


def test_signer_refuses_a_public_key_that_does_not_match(site_keys):
    private, _, _, other_public = site_keys

    with pytest.raises(CandidateSignatureError, match="signature verification failed"):
        sign_manifest_bytes(
            b"manifest", key_id="rosy-site-test-1",
            private_key=private, public_key=other_public,
        )


@pytest.mark.parametrize("envelope", [b"", b"not json", b'{"signature_version":1}'])
def test_verifier_rejects_missing_or_malformed_envelopes(site_keys, envelope):
    _, public, _, _ = site_keys

    with pytest.raises(CandidateSignatureError):
        verify_manifest_signature(
            b"manifest", envelope, trusted_key_id="rosy-site-test-1", public_key=public,
        )


def test_offline_signer_and_host_verifier_round_trip_a_candidate(tmp_path, site_keys):
    private, public, _, _ = site_keys
    root = tmp_path / "candidate"
    root.mkdir()
    image_ids = _make_candidate(root)

    signed = sign_candidate(
        root, key_id=TEST_KEY_ID, private_key=private, public_key=public,
    )
    assert signed["signing_key_id"] == TEST_KEY_ID

    def runner(args, **kwargs):
        if "pkeyutl" in args:
            return subprocess.run(args, **kwargs)
        reference = args[-1]
        service = reference.split(":", 1)[0].removeprefix("rosy-site-")
        return SimpleNamespace(stdout=f"{image_ids[service]}|linux|amd64\n")

    verified = verify_candidate(
        root, trusted_key_id=TEST_KEY_ID, trusted_public_key=public, runner=runner,
    )
    assert verified["source_commit"] == COMMIT
    assert verified["image_ids"] == image_ids

    with pytest.raises(ValueError, match="signature already exists"):
        sign_candidate(root, key_id=TEST_KEY_ID, private_key=private, public_key=public)


def test_offline_signer_refuses_corrupt_contents_without_creating_signature(tmp_path, site_keys):
    private, public, _, _ = site_keys
    root = tmp_path / "candidate"
    root.mkdir()
    _make_candidate(root)
    (root / "images.tar").write_bytes(b"tampered archive")

    with pytest.raises(ValueError, match="image archive hash mismatch"):
        sign_candidate(root, key_id=TEST_KEY_ID, private_key=private, public_key=public)
    assert not (root / "release.json.sig").exists()


def test_offline_signer_rechecks_contents_after_signature_creation(tmp_path, site_keys, monkeypatch):
    private, public, _, _ = site_keys
    root = tmp_path / "candidate"
    root.mkdir()
    _make_candidate(root)

    def race_mutation(*args, **kwargs):
        (root / "deploy/site/compose.yaml").write_text("changed after initial check")
        return b"signature envelope"

    monkeypatch.setattr(signer_module, "sign_manifest_bytes", race_mutation)
    with pytest.raises(ValueError, match="compose.yaml"):
        signer_module.sign_candidate(
            root, key_id=TEST_KEY_ID, private_key=private, public_key=public,
        )
    assert not (root / "release.json.sig").exists()


def test_manifest_only_signature_lets_the_host_verifier_check_every_file(tmp_path, site_keys):
    private, public, _, _ = site_keys
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    image_ids = _make_candidate(candidate)
    station = tmp_path / "station"
    station.mkdir()
    manifest = station / "release.json"
    manifest.write_bytes((candidate / "release.json").read_bytes())

    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    signed = signer_module.sign_manifest_only(
        manifest, expected_commit=COMMIT, expected_manifest_sha256=digest, key_id=TEST_KEY_ID,
        private_key=private, public_key=public,
    )
    assert signed["source_commit"] == COMMIT
    assert signed["scope"] == "manifest-only"
    assert sorted(path.name for path in station.iterdir()) == ["release.json", "release.json.sig"]

    (candidate / "release.json.sig").write_bytes((station / "release.json.sig").read_bytes())
    verified = verify_candidate(
        candidate, trusted_key_id=TEST_KEY_ID, trusted_public_key=public,
        inspect_loaded_images=False,
    )
    assert verified["manifest_image_ids"] == image_ids

    (candidate / "images.tar").write_bytes(b"swapped after signing")
    with pytest.raises(ValueError, match="image archive hash mismatch"):
        verify_candidate(
            candidate, trusted_key_id=TEST_KEY_ID, trusted_public_key=public,
            inspect_loaded_images=False,
        )

    with pytest.raises(ValueError, match="signature already exists"):
        signer_module.sign_manifest_only(
            manifest, expected_commit=COMMIT, expected_manifest_sha256=digest,
            key_id=TEST_KEY_ID,
            private_key=private, public_key=public,
        )


@pytest.mark.parametrize(("source_commit", "expected", "message"), [
    ("abc123", "abc123", "expected commit must be"),
    ("A" * 40, COMMIT, "source commit is not a 40-character"),
    ("b" * 40, COMMIT, "differs from the expected commit"),
])
def test_manifest_only_signer_refuses_bad_or_unexpected_commits(
        tmp_path, site_keys, source_commit, expected, message):
    private, public, _, _ = site_keys
    manifest = tmp_path / "release.json"
    manifest.write_text(
        '{"manifest_version": 1, "source_commit": "%s", "image_tag": "%s", '
        '"platform": "linux/amd64"}\n' % (source_commit, source_commit),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        signer_module.sign_manifest_only(
            manifest, expected_commit=expected,
            expected_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
            key_id=TEST_KEY_ID,
            private_key=private, public_key=public,
        )
    assert not (tmp_path / "release.json.sig").exists()


def test_manifest_only_cli_requires_manifest_and_expected_commit(tmp_path, site_keys, capsys):
    private, public, _, _ = site_keys
    common = ["--signing-key-id", TEST_KEY_ID, "--private-key", str(private),
              "--public-key", str(public)]

    with pytest.raises(SystemExit):
        signer_module.main(["--manifest-only", "--manifest", str(tmp_path / "release.json"),
                            *common])
    with pytest.raises(SystemExit):
        signer_module.main(["--candidate-dir", str(tmp_path), "--expected-commit", COMMIT,
                            *common])

    candidate = tmp_path / "candidate"
    candidate.mkdir()
    _make_candidate(candidate)
    digest = hashlib.sha256((candidate / "release.json").read_bytes()).hexdigest()
    with pytest.raises(SystemExit):
        signer_module.main(["--manifest-only", "--manifest", str(candidate / "release.json"),
                            "--expected-commit", COMMIT, *common])
    assert signer_module.main([
        "--manifest-only", "--manifest", str(candidate / "release.json"),
        "--expected-commit", COMMIT, "--expected-manifest-sha256", digest, *common,
    ]) == 0
    assert '"scope": "manifest-only"' in capsys.readouterr().out


def test_manifest_only_signer_refuses_a_manifest_not_matching_the_ci_hash(tmp_path, site_keys):
    private, public, _, _ = site_keys
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    _make_candidate(candidate)
    manifest = candidate / "release.json"
    published = hashlib.sha256(manifest.read_bytes()).hexdigest()
    # Someone with release write access swaps release.json for one with the
    # same commit but a different archive hash.
    manifest.write_text(manifest.read_text(encoding="utf-8").replace(
        '"image_archive_sha256": "', '"image_archive_sha256": "0'), encoding="utf-8")

    for expected, message in ((published, "differs from the CI run"),
                              ("ABC", "must be 64 lowercase hex")):
        with pytest.raises(ValueError, match=message):
            signer_module.sign_manifest_only(
                manifest, expected_commit=COMMIT, expected_manifest_sha256=expected,
                key_id=TEST_KEY_ID, private_key=private, public_key=public,
            )
    assert not (candidate / "release.json.sig").exists()
