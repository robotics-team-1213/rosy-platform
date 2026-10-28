"""Public build trust with ephemeral certificates; no product key is generated."""
import hashlib
import importlib.util
from pathlib import Path
import shutil

import pytest
import yaml

from test_ab_image_layout import IMAGE, module as image_module
from os_rauc_fakes import signer, run, expired_pem

CERTIFICATE = "deploy/robot/pinky_pro/release/public-keys/rosy-os-cms-2026-01.pem"


def module():
    image_module()
    spec = importlib.util.spec_from_file_location("os_cms_trust_test", IMAGE / "os_cms_trust.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def case(tmp_path):
    m = module()
    key, certificate = signer(tmp_path / "ephemeral-cms")
    source = tmp_path / "source"
    target = source / CERTIFICATE
    target.parent.mkdir(parents=True)
    shutil.copyfile(certificate, target)
    section = dict(cms_certificate=CERTIFICATE, cms_certificate_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                   cms_signer_spki_sha256=m._spki(target.read_bytes()), cms_verified=True)
    return m, source, target, key, section


def test_installs_exact_pinned_public_certificate_without_private_material(tmp_path):
    m, source, target, _, section = case(tmp_path)
    root = tmp_path / "offline-root"
    root.mkdir()
    raw = m.verify(section, source)
    m.install(root, raw)
    installed = root / "etc/rauc/keyring.pem"
    assert installed.read_bytes() == target.read_bytes() == raw
    assert installed.stat().st_mode & 0o777 == 0o644
    assert "PRIVATE KEY" not in installed.read_text()
    m.install(root, raw)


@pytest.mark.parametrize("change", ["unverified", "null_hash", "null_spki", "hash", "spki", "expired", "private", "chain", "path", "symlink"])
def test_unapproved_or_invalid_certificate_never_becomes_build_trust(tmp_path, change):
    m, source, certificate, key, section = case(tmp_path)
    if change == "unverified": section["cms_verified"] = False
    if change == "null_hash": section["cms_certificate_sha256"] = None
    if change == "null_spki": section["cms_signer_spki_sha256"] = None
    if change == "hash": section["cms_certificate_sha256"] = "0" * 64
    if change == "spki": section["cms_signer_spki_sha256"] = "0" * 64
    if change == "expired":
        raw = expired_pem(certificate, key)
        certificate.write_bytes(raw)
        section["cms_certificate_sha256"] = hashlib.sha256(raw).hexdigest()
    if change == "private":
        certificate.write_bytes(key.read_bytes())
        section["cms_certificate_sha256"] = hashlib.sha256(certificate.read_bytes()).hexdigest()
    if change == "chain":
        certificate.write_bytes(certificate.read_bytes() * 2)
        section["cms_certificate_sha256"] = hashlib.sha256(certificate.read_bytes()).hexdigest()
    if change == "path": section["cms_certificate"] = "../outside.pem"
    if change == "symlink":
        certificate.unlink()
        certificate.symlink_to(key.parent / "fixture.cert.pem")
    with pytest.raises((ValueError, OSError)):
        m.verify(section, source)


@pytest.mark.parametrize("change", ["different", "symlink", "hardlink"])
def test_existing_trust_is_not_silently_replaced(tmp_path, change):
    m, _, certificate, _, _ = case(tmp_path)
    root = tmp_path / "offline-root"
    target = root / "etc/rauc/keyring.pem"
    target.parent.mkdir(parents=True)
    if change == "different": target.write_text("existing operator trust\n")
    if change == "symlink": target.symlink_to(certificate)
    if change == "hardlink":
        import os
        os.link(certificate, target)
    before = target.read_bytes()
    with pytest.raises((ValueError, OSError)):
        m.install(root, certificate.read_bytes())
    assert target.read_bytes() == before


def test_engineering_build_selects_exact_existing_public_cms_certificate():
    m = module()
    root = Path(__file__).resolve().parents[1]
    lock = yaml.safe_load((IMAGE / "inputs.lock.yaml").read_bytes())["os_updates"]
    assert lock["cms_verified"] is True
    assert lock["cms_certificate"] == CERTIFICATE
    raw = (root / CERTIFICATE).read_bytes()
    assert lock["cms_certificate_sha256"] == hashlib.sha256(raw).hexdigest() == "c9b715ef42497e1e1f746529a882604e7159f7957f652d25977d56f49d9104a1"
    assert lock["cms_signer_spki_sha256"] == m._spki(raw) == "f0a17ffa253b371ea1a5c8ea541730a7b359ced40d70ee83d63d08be24497a88"
    assert m.verify(lock, root) == raw


def test_build_cannot_resolve_or_customize_without_explicit_public_cms_pins():
    resolver = (IMAGE / "resolve-build-lock.py").read_text()
    assert 'verify_cms(lock["os_updates"]' in resolver
    for name in ("build-image.sh", "customize-rootfs.sh"):
        assert "os_cms_trust.py" in (IMAGE / name).read_text()
