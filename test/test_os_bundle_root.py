"""Offline native signature injection with real payload verification, no mounts or enrollment."""
import importlib.util
from importlib.machinery import ModuleSpec
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
    value["source_revision"] = (release / "source-revision.txt").read_text().strip()
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


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_mount_owner_detaches_before_readonly_reopen_and_preserves_failed_cleanup(tmp_path, monkeypatch, cleanup_fails):
    m = module()
    images = tmp_path / "images"
    images.mkdir()
    calls = []
    class Resources:
        def loop(self, image, *, readonly=False):
            calls.append(("loop", image.name, readonly))
            return str(image)
        def mount(self, device, target, *, readonly=False, filesystem="ext4"):
            target.mkdir()  # A stale mount directory must be explicitly removed before reopening.
            calls.append(("mount", target.name, readonly))
        def unmount_all(self): calls.append(("unmount",))
        def close(self):
            calls.append(("close",))
            if cleanup_fails: raise OSError("fixture still mounted")
    class Loader:
        def create_module(self, spec): return None
        def exec_module(self, target):
            target.ImageResources = Resources
            target._run = lambda *a, **k: calls.append(("fsck",))
    monkeypatch.setattr(m.importlib.util, "spec_from_file_location", lambda *a: ModuleSpec("owned_resources_fixture", Loader()))
    monkeypatch.setattr(m.os, "geteuid", lambda: 0)
    monkeypatch.setattr(m, "_read", lambda *a: b"modeled source metadata")
    monkeypatch.setattr(m, "rebase_files", lambda *a: calls.append(("validate-source",)))
    monkeypatch.setattr(m, "inject", lambda *a: calls.append(("inject",)))
    monkeypatch.setattr(m, "_verify", lambda *a: calls.append(("verify-ro",)))
    from test_os_update_manifest import metadata
    value = metadata()
    value.update(layout={}, images={"rootfs.ext4": {"size_bytes": 8192}, "boot.vfat": {"size_bytes": 512}})
    if cleanup_fails:
        with pytest.raises(RuntimeError, match="OS_SIGN_CLEANUP_HOLD"):
            m.prepare(images, value, tmp_path, tmp_path / "public", b"certificate")
        assert images.exists() and (tmp_path / "root-mount").exists()
    else:
        m.prepare(images, value, tmp_path, tmp_path / "public", b"certificate")
        assert calls.index(("close",)) < calls.index(("loop", "rootfs.ext4", True))
        assert ("mount", "root-mount", True) in calls and ("mount", "boot-mount", True) in calls
        assert calls.index(("inject",)) < calls.index(("verify-ro",))
