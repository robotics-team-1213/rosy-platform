"""Real CMS/verity and Ed metadata checks in private fixture staging, never an install."""
import hashlib
import importlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from test_ab_image_layout import module
from test_factory_release_signature import _keys
from test_os_update_manifest import metadata
from signing import sign_checksums
from os_rauc_fakes import rauc_tool, signer, make_bundle, manifest, run


def _consumer(monkeypatch, tool):
    module()
    m = importlib.import_module("os_rauc")
    monkeypatch.setattr(m, "RAUC", str(tool))
    return m


def _case(tmp_path, tool, *, text=None, foreign=False, expired=False):
    root = tmp_path / "device"
    public_dir = root / "etc/rosy/trusted-release-keys"
    private, public = _keys(public_dir, "distribution")
    key, certificate = signer(tmp_path / "cms")
    if expired:
        old = certificate.with_name("expired.pem")
        run(["openssl", "x509", "-in", certificate, "-signkey", key, "-days", "-1", "-out", old])
        certificate = old
    bundle_key, bundle_cert = signer(tmp_path / "foreign") if foreign else (key, certificate)
    produced, _ = make_bundle(tmp_path / "producer", tool, bundle_key, bundle_cert, text, verify_creation=not expired)
    ring = root / "etc/rauc/keyring.pem"
    ring.parent.mkdir(parents=True)
    shutil.copy2(certificate, ring)
    value = metadata()
    value["rootfs_bytes"] = 8192
    value["bundle"]["sha256"] = hashlib.sha256(produced.read_bytes()).hexdigest()
    value["bundle"]["size_bytes"] = produced.stat().st_size
    pub = run(["openssl", "x509", "-in", certificate, "-pubkey", "-noout"])
    der = run(["openssl", "pkey", "-pubin", "-outform", "DER"], data=pub)
    value["cms_signer_spki_sha256"] = hashlib.sha256(der).hexdigest()
    stage = root / "var/lib/rosy-device/os-update/staging" / value["release_id"]
    stage.mkdir(parents=True, mode=0o700)
    bundle = stage / value["bundle"]["filename"]
    shutil.copy2(produced, bundle)
    bundle.chmod(0o400)
    raw = json.dumps(value).encode()
    signature = sign_checksums(raw, private)
    return root, bundle, raw, signature, private, ring


def test_real_cms_verity_and_exact_outer_metadata_are_accepted(tmp_path, monkeypatch, rauc_tool):
    m = _consumer(monkeypatch, rauc_tool)
    root, bundle, raw, signature, _, _ = _case(tmp_path, rauc_tool)
    before = bundle.read_bytes()
    facts = m.verify_bundle(root, bundle, raw, signature)
    assert facts["metadata"] == json.loads(raw)
    assert facts["images"]["rootfs"]["size"] == 8192
    assert facts["images"]["boot"]["size"] == 512
    assert bundle.read_bytes() == before


def test_frozen_verifier_works_after_the_mutable_sdk_is_poisoned(tmp_path, rauc_tool):
    from test_os_frozen_firstboot import _prefix, _stage
    root, bundle, raw, signature, _, _ = _case(tmp_path, rauc_tool)
    prefix = _prefix(tmp_path / "isolated")
    _stage(prefix)
    for directory in (prefix / "native-runtime", prefix / "deploy/sd"):
        for path in directory.glob("*.py"):
            path.write_text('raise RuntimeError("poisoned mutable SDK")\n')
    metadata_file, signature_file = bundle.parent / "os-update.json", bundle.parent / "os-update.json.sig"
    metadata_file.write_bytes(raw)
    signature_file.write_text(signature)
    code = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import os_rauc, os_update_manifest, signing
assert all(Path(m.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve())
           for m in (os_rauc, os_update_manifest, signing))
os_rauc.RAUC = sys.argv[2]
result = os_rauc.verify_bundle(Path(sys.argv[3]), Path(sys.argv[4]),
                              Path(sys.argv[5]).read_bytes(), Path(sys.argv[6]).read_text())
assert result['images']['rootfs']['size'] == 8192
"""
    result = subprocess.run([sys.executable, "-I", "-B", "-c", code,
        str(prefix / "os-bootstrap/native-runtime"), str(rauc_tool), str(root), str(bundle),
        str(metadata_file), str(signature_file)], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr


def test_cms_size_is_bounded_before_starting_a_parser(tmp_path, monkeypatch, rauc_tool):
    m = _consumer(monkeypatch, rauc_tool)
    root, bundle, raw, _, private, _ = _case(tmp_path, rauc_tool)
    bundle.chmod(0o600)
    value = bundle.read_bytes()[:-8] + (65537).to_bytes(8, "big")
    bundle.write_bytes(value); bundle.chmod(0o400)
    metadata_value = json.loads(raw)
    metadata_value["bundle"]["sha256"] = hashlib.sha256(value).hexdigest()
    raw = json.dumps(metadata_value).encode()
    monkeypatch.setattr(m, "_inspect", lambda *args: pytest.fail("oversized CMS reached RAUC"))
    with pytest.raises(ValueError, match="CMS footer"):
        m.verify_bundle(root, bundle, raw, sign_checksums(raw, private))


@pytest.mark.parametrize("case", ["signature", "hash", "signer_pin", "foreign_cms", "expired", "no_keyring", "writable", "outside"])
def test_bad_distribution_or_cms_never_becomes_installable(tmp_path, monkeypatch, rauc_tool, case):
    m = _consumer(monkeypatch, rauc_tool)
    root, bundle, raw, signature, private, ring = _case(tmp_path, rauc_tool, foreign=case == "foreign_cms", expired=case == "expired")
    if case == "signature":
        raw += b" "
    elif case == "hash":
        bundle.chmod(0o600)
        value = bytearray(bundle.read_bytes()); value[100] ^= 1
        bundle.write_bytes(value); bundle.chmod(0o400)
    elif case == "signer_pin":
        value = json.loads(raw); value["cms_signer_spki_sha256"] = "f" * 64
        raw = json.dumps(value).encode(); signature = sign_checksums(raw, private)
    elif case == "no_keyring":
        ring.unlink()
    elif case == "writable":
        bundle.chmod(0o666)
    elif case == "outside":
        other = tmp_path / bundle.name
        shutil.copy2(bundle, other); bundle = other
    before = bundle.read_bytes()
    with pytest.raises(ValueError):
        m.verify_bundle(root, bundle, raw, signature)
    assert bundle.read_bytes() == before


@pytest.mark.parametrize("case", ["board", "version", "revision", "abi", "state", "native_factory", "native_digest", "hooks", "handler", "data_class"])
def test_real_signed_cms_metadata_must_agree_with_outer_contract(tmp_path, monkeypatch, rauc_tool, case):
    m = _consumer(monkeypatch, rauc_tool)
    text = manifest()
    if case == "board": text = text.replace("rosy-pinky-pro-ab-v2", "foreign-board")
    elif case == "version": text = text.replace("version=2026.10.26-011", "version=2026.10.26-012")
    elif case == "revision": text = text.replace("build=" + "b" * 40, "build=" + "c" * 40)
    elif case == "abi": text = text.replace("boot_abi=2", "boot_abi=1")
    elif case == "state": text = text.replace("state_write=1", "state_write=2")
    elif case == "native_factory": text = text.replace("native_factory_release_id=2026.10.26-010", "native_factory_release_id=2026.10.26-009")
    elif case == "native_digest": text = text.replace("native_factory_checksums_sha256=" + "a" * 64, "native_factory_checksums_sha256=" + "c" * 64)
    elif case == "hooks": text += "[hooks]\nfilename=hook.sh\nhooks=install-check\n"
    elif case == "handler": text += "[handler]\nfilename=handler.sh\n"
    else: text = text.replace("[image.boot]", "[image.data]")
    root, bundle, raw, signature, _, _ = _case(tmp_path, rauc_tool, text=text)
    with pytest.raises(ValueError):
        m.verify_bundle(root, bundle, raw, signature)
