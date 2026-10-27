"""Exact Ed25519-authenticated OS metadata is distinct from native payload discovery."""
import importlib
import json

import pytest

from test_ab_image_layout import module
from test_factory_release_signature import _keys
from signing import sign_checksums

RELEASE = "2026.10.26-011"


def metadata():
    return dict(schema_version=1, kind="os-update", board="pinky_pro", arch="arm64",
        compatible="rosy-pinky-pro-ab-v2", release_id=RELEASE, source_revision="b" * 40,
        bundle=dict(filename=f"rosy-os-pinky-pro-{RELEASE}-arm64.raucb", sha256="d" * 64, size_bytes=16384),
        rootfs_bytes=1024, boot_bytes=512, native_factory=dict(release_id="2026.10.26-010", checksums_sha256="a" * 64),
        boot_abi=2, state_schema=dict(read_min=1, read_max=1, write=1), cms_signer_spki_sha256="c" * 64)


def _consumer():
    module()
    return importlib.import_module("os_update_manifest")


def test_exact_raw_os_metadata_is_verified_with_existing_ed25519_authority(tmp_path):
    m = _consumer()
    private, public = _keys(tmp_path / "ed", "distribution")
    value = metadata()
    raw = json.dumps(value, indent=2).encode()
    assert m.verify_metadata(raw, sign_checksums(raw, private), public) == value


def test_signature_is_checked_before_any_json_is_parsed(tmp_path, monkeypatch):
    m = _consumer()
    private, public = _keys(tmp_path / "ed", "distribution")
    raw = json.dumps(metadata()).encode()
    signature = sign_checksums(raw, private)
    monkeypatch.setattr(m.json, "loads", lambda *args, **kwargs: pytest.fail("untrusted JSON was parsed"))
    with pytest.raises(ValueError, match="OS_UPDATE_SIGNATURE"):
        m.verify_metadata(b"{" + raw, signature, public)


@pytest.mark.parametrize("case", ["boolean_schema", "unknown_field", "board", "arch", "kind", "compatible",
    "date", "revision", "bundle_path", "bundle_release", "bundle_boolean", "bundle_float", "bundle_digest",
    "root_size", "boot_size", "native_date", "native_hash", "abi", "reader", "writer", "bool_writer", "signer"])
def test_even_signed_metadata_must_match_the_exact_os_contract(tmp_path, case):
    m = _consumer()
    private, public = _keys(tmp_path / "ed", "distribution")
    value = metadata()
    if case == "boolean_schema": value["schema_version"] = True
    elif case == "unknown_field": value["execute"] = "ignored-command"
    elif case in ("board", "arch", "kind", "compatible"): value[case] = "unsupported"
    elif case == "date": value["release_id"] = "2026.02.31-011"
    elif case == "revision": value["source_revision"] = "main"
    elif case == "bundle_path": value["bundle"]["filename"] = "../bundle.raucb"
    elif case == "bundle_release": value["bundle"]["filename"] = value["bundle"]["filename"].replace("011", "012")
    elif case == "bundle_boolean": value["bundle"]["size_bytes"] = True
    elif case == "bundle_float": value["bundle"]["size_bytes"] = 16384.0
    elif case == "bundle_digest": value["bundle"]["sha256"] = "d" * 63
    elif case == "root_size": value["rootfs_bytes"] = -512
    elif case == "boot_size": value["boot_bytes"] = 513
    elif case == "native_date": value["native_factory"]["release_id"] = "latest"
    elif case == "native_hash": value["native_factory"]["checksums_sha256"] = "not-a-hash"
    elif case == "abi": value["boot_abi"] = 1
    elif case == "reader": value["state_schema"]["read_max"] = 2
    elif case == "writer": value["state_schema"]["write"] = 2
    elif case == "bool_writer": value["state_schema"]["write"] = True
    else: value["cms_signer_spki_sha256"] = "invalid"
    raw = json.dumps(value).encode()
    with pytest.raises(ValueError, match="OS_UPDATE_METADATA"):
        m.verify_metadata(raw, sign_checksums(raw, private), public)


def test_signed_duplicate_fields_are_never_silently_resolved(tmp_path):
    m = _consumer()
    private, public = _keys(tmp_path / "ed", "distribution")
    raw = json.dumps(metadata()).encode().replace(b'"schema_version": 1', b'"schema_version": 1, "schema_version": 1')
    with pytest.raises(ValueError, match="OS_UPDATE_METADATA"):
        m.verify_metadata(raw, sign_checksums(raw, private), public)
