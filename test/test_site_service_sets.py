"""Authenticate known legacy/current sets without changing the four-image builder."""

import base64
import hashlib
import json
import subprocess
from types import SimpleNamespace

import pytest

from deploy.site.candidate_signing import sign_manifest_bytes
from deploy.site.verify_candidate import CandidateVerificationError, verify_candidate
from test_site_candidate_signing import site_keys
from test_site_candidate_verifier import COMMIT, TEST_KEY_ID, candidate, _write_images_tar


LEGACY = ("fleet", "vision", "proxy")
CURRENT = (*LEGACY, "postgres")


def signed_variant(candidate, site_keys, services):
    root, _, _, _ = candidate
    private, public, _, _ = site_keys
    ids = _write_images_tar(root / "images.tar", services=services)
    path = root / "release.json"
    manifest = json.loads(path.read_text())
    manifest["images"] = {}
    for service in services:
        sbom = root / "sbom" / f"{service}.spdx"
        sbom.write_text(f"SPDX for {service}\n")
        manifest["images"][service] = {
            "reference": f"rosy-site-{service}:{COMMIT}", "image_id": ids[service][0],
            "platform": "linux/amd64", "sbom": f"sbom/{service}.spdx",
            "sbom_sha256": hashlib.sha256(sbom.read_bytes()).hexdigest(),
        }
    manifest["image_archive_sha256"] = hashlib.sha256((root / "images.tar").read_bytes()).hexdigest()
    calls = []

    def seal():
        raw = json.dumps(manifest).encode()
        path.write_bytes(raw)
        (root / "release.json.sig").write_bytes(sign_manifest_bytes(
            raw, key_id=TEST_KEY_ID, private_key=private, public_key=public))

    def runner(args, **kwargs):
        calls.append(list(args))
        if "pkeyutl" in args:
            return subprocess.run(args, **kwargs)
        assert args[:3] == ["docker", "image", "inspect"]
        service = args[-1].split(":", 1)[0].removeprefix("rosy-site-")
        return SimpleNamespace(returncode=0, stdout=f"{ids[service][0]}|linux|amd64\n", stderr="")

    seal()
    return SimpleNamespace(root=root, public=public, manifest=manifest, ids=ids,
                           calls=calls, runner=runner, seal=seal)


def verify(material, loaded):
    return verify_candidate(material.root, trusted_key_id=TEST_KEY_ID,
                            trusted_public_key=material.public, runner=material.runner,
                            inspect_loaded_images=loaded)


@pytest.mark.parametrize("services", [LEGACY, CURRENT], ids=["legacy3", "current4"])
@pytest.mark.parametrize("loaded", [False, True], ids=["package", "loaded"])
def test_known_signed_set_is_reported_in_both_verification_modes(candidate, site_keys, services, loaded):
    material = signed_variant(candidate, site_keys, services)
    report = verify(material, loaded)
    assert report["source_commit"] == COMMIT
    assert report["verified_images"] == list(services)
    if loaded:
        assert set(report["accepted_image_ids"]) == set(services)
    else:
        assert report["manifest_image_ids"] == {s: material.ids[s][0] for s in services}
        assert all("docker" not in call for call in material.calls)


@pytest.mark.parametrize("services", [LEGACY[:2], (*CURRENT, "unexpected")], ids=["incomplete2", "extra5"])
@pytest.mark.parametrize("loaded", [False, True])
def test_other_self_consistent_signed_sets_are_rejected(candidate, site_keys, services, loaded):
    material = signed_variant(candidate, site_keys, services)
    with pytest.raises(CandidateVerificationError, match="image"):
        verify(material, loaded)
    assert all("docker" not in call for call in material.calls)


@pytest.mark.parametrize("loaded", [False, True])
def test_legacy_set_does_not_bypass_a_real_signature_failure(candidate, site_keys, loaded):
    material = signed_variant(candidate, site_keys, LEGACY)
    envelope = json.loads((material.root / "release.json.sig").read_text())
    envelope["signature"] = base64.b64encode(bytes(64)).decode("ascii")
    (material.root / "release.json.sig").write_text(json.dumps(envelope))
    with pytest.raises(CandidateVerificationError, match="signature|Signature"):
        verify(material, loaded)
    assert all("docker" not in call for call in material.calls)


def test_current_archive_cannot_omit_the_signed_postgres_image(candidate, site_keys):
    material = signed_variant(candidate, site_keys, CURRENT)
    _write_images_tar(material.root / "images.tar", services=LEGACY)
    material.manifest["image_archive_sha256"] = hashlib.sha256(
        (material.root / "images.tar").read_bytes()).hexdigest()
    material.seal()
    with pytest.raises(CandidateVerificationError, match="postgres|archive"):
        verify(material, True)
