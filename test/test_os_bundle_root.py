"""Offline native signature injection with real payload verification, no mounts or enrollment."""
import importlib.util
import shutil

import pytest

from test_ab_image_layout import IMAGE, module as image_module
from test_os_installed_factory import _installed
from os_rauc_fakes import signer


def module():
    image_module()
    spec = importlib.util.spec_from_file_location("os_bundle_root_test", IMAGE.parent / "release/os_bundle_root.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.mark.parametrize("damage", [None, "payload", "signature", "trust"])
def test_injects_only_verified_supplied_native_signature_and_refuses_foreign_payload(tmp_path, damage):
    m = module()
    _, target, release, value, _, public = _installed(tmp_path)
    factory = tmp_path / "signed-factory"
    factory.mkdir()
    for name in ("SHA256SUMS", "SHA256SUMS.sig", "manifest.json"):
        shutil.copyfile(release / name, factory / name)
    (release / "SHA256SUMS.sig").unlink()
    _, certificate = signer(tmp_path / "cms")
    ring = target / "etc/rauc/keyring.pem"
    ring.parent.mkdir(parents=True)
    ring.write_bytes(certificate.read_bytes())
    if damage == "payload": (release / "install/.rosy-release").write_text("tampered")
    if damage == "signature": (factory / "SHA256SUMS.sig").write_text("tampered")
    if damage == "trust": ring.write_text("foreign")
    if damage:
        with pytest.raises(ValueError):
            m.inject(target, factory, public, certificate.read_bytes(), value)
    else:
        m.inject(target, factory, public, certificate.read_bytes(), value)
        assert (release / "SHA256SUMS.sig").read_bytes() == (factory / "SHA256SUMS.sig").read_bytes()
    assert not (target / "var/lib/rosy-device").exists()
    if damage in {"signature", "trust"}: assert not (release / "SHA256SUMS.sig").exists()
