"""Real signed factories may cross slots only when release, checksum and key match."""
import hashlib
import json
import os
import shutil

import pytest

from build_payload_release import seal_release
from signing import sign_checksums
from os_state_boot_fakes import shared_roots
from test_factory_release_signature import FACTORY_ID, IMAGE_RUNTIME, _bundle, _keys, _payload
from test_first_boot_provisioning import _module
from test_os_first_boot_state import SERIAL
from test_os_tailnet_state import _serial


def _factory(root, release_id, private, public, *, signed=False):
    release = root / "opt/rosy/releases" / release_id
    _payload(release, release_id)
    shutil.rmtree(release / "image-overlay")
    seal_release(release, release_id)
    signature = sign_checksums((release / "SHA256SUMS").read_bytes(), private)
    if signed:
        (release / "SHA256SUMS.sig").write_text(signature + "\n")
    key = root / "etc/rosy/trusted-release-keys" / public.name
    key.parent.mkdir(parents=True, exist_ok=True)
    key.write_bytes(public.read_bytes())
    runtime = root / "usr/local/share/rosy/python-runtime.sha256"
    runtime.parent.mkdir(parents=True, exist_ok=True)
    runtime.write_text(IMAGE_RUNTIME + "\n")
    descriptor = dict(schema_version=1, release_id=release_id,
                      checksums_sha256=hashlib.sha256((release / "SHA256SUMS").read_bytes()).hexdigest())
    (root / "etc/rosy/os-factory-release.json").write_text(json.dumps(descriptor))
    return release, dict(release_id=release_id, sha256sums_sig_b64=signature)


def _device(tmp_path, monkeypatch):
    root, other, common, _ = shared_roots(tmp_path, monkeypatch)
    private, public = _keys(tmp_path / "offline", "fixture")
    release, record = _factory(root, FACTORY_ID, private, public)
    _factory(other, FACTORY_ID, private, public)
    bundle = root / "run/rosy-provision-boot/rosy-provision/provision.json"
    bundle.parent.mkdir()
    bundle.write_text(json.dumps(_bundle(record)))
    first = _module()
    assert first.FirstBootProvisioner(root=root, network_activate=lambda _: True).apply(
        bundle=bundle, hardware_serial=SERIAL)["ok"]
    for target in (root, other):
        _serial(target)
        (target / "proc/sys/kernel/hostname").write_text("rosy-pinky-k7m4\n")
    assert first.FirstBootProvisioner(root=other).apply(bundle=bundle, hardware_serial=SERIAL)["ok"]
    for target in (root, other):
        first._native_helper("os_state_ready").publish_ready(target)
    return first, root, other, common, private, public, release


def test_initial_signature_is_saved_before_bundle_consumption_and_installed_in_b(tmp_path, monkeypatch):
    first, root, other, common, _, _, release = _device(tmp_path, monkeypatch)
    capsules = list((common / "state/factory-signatures").glob("*.json"))
    assert len(capsules) == 1, "the consumed bundle's signature must remain available to B"
    assert capsules[0].stat().st_mode & 0o777 == 0o600
    helper = first._native_helper("os_factory_release")
    report = helper.prepare_factory(other)
    assert report["phase"] == "FACTORY_VERIFIED"
    assert report["release_id"] == FACTORY_ID
    assert (other / "opt/rosy/releases" / FACTORY_ID / "SHA256SUMS.sig").read_bytes() == (
        release / "SHA256SUMS.sig").read_bytes()
    assert helper.prepare_factory(root)["release_id"] == FACTORY_ID


def test_new_os_factory_uses_its_own_signature_without_changing_device_completion(tmp_path, monkeypatch):
    first, root, other, common, private, public, _ = _device(tmp_path, monkeypatch)
    completion = (common / "provisioning/complete.json").read_bytes()
    _factory(other, "2026.10.26-001", private, public, signed=True)
    helper = first._native_helper("os_factory_release")
    assert helper.prepare_factory(other)["release_id"] == "2026.10.26-001"
    assert helper.prepare_factory(root)["release_id"] == FACTORY_ID
    assert (common / "provisioning/complete.json").read_bytes() == completion


@pytest.mark.parametrize("change", ["new_unsigned_factory", "corrupt_capsule", "foreign_key", "changed_payload"])
def test_old_or_corrupt_signatures_cannot_authorize_a_root(tmp_path, monkeypatch, change):
    first, _, other, common, private, public, _ = _device(tmp_path, monkeypatch)
    release = other / "opt/rosy/releases" / FACTORY_ID
    if change == "new_unsigned_factory":
        release, _ = _factory(other, "2026.10.26-002", private, public)
    elif change == "corrupt_capsule":
        capsule = next((common / "state/factory-signatures").glob("*.json"))
        record = json.loads(capsule.read_text())
        record["sha256sums_sig_b64"] = "A" * 86 + "=="
        capsule.write_text(json.dumps(record))
    elif change == "foreign_key":
        _, foreign = _keys(tmp_path / "foreign", "fixture")
        (other / "etc/rosy/trusted-release-keys" / public.name).write_bytes(foreign.read_bytes())
    elif change == "changed_payload":
        (release / "source-revision.txt").write_text("foreign revision\n")
    with pytest.raises(ValueError):
        first._native_helper("os_factory_release").prepare_factory(other)
    assert not (release / "SHA256SUMS.sig").exists()


def test_signature_cache_failure_does_not_consume_the_one_time_bundle(tmp_path, monkeypatch):
    helper = _module()._native_helper("os_factory_release")

    def failed_cache(*_args):
        raise OSError("fixture signature cache write failed")

    with monkeypatch.context() as scoped:
        scoped.setattr(helper, "cache_signature", failed_cache)
        with pytest.raises(OSError, match="cache write failed"):
            _device(tmp_path, monkeypatch)
    root = tmp_path / "root-a"
    bundle = root / "run/rosy-provision-boot/rosy-provision/provision.json"
    assert bundle.exists()
    assert not (root / "var/lib/rosy/provisioning/complete.json").exists()
    assert _module().FirstBootProvisioner(root=root, network_activate=lambda _: True).apply(
        bundle=bundle, hardware_serial=SERIAL)["ok"]
    assert not bundle.exists()


def test_updater_pruning_keeps_the_root_factory_after_payload_updates(tmp_path, monkeypatch):
    from auto_update_fakes import FakeHost, upd
    _, root, _, _, _, _, release = _device(tmp_path, monkeypatch)
    host = FakeHost(root, current="2026.10.26-003")
    host.links["previous"] = "2026.10.26-002"
    obsolete = root / "opt/rosy/releases/2026.09.24-001"
    for path in (release, obsolete, release.parent / host.links["current"], release.parent / host.links["previous"]):
        path.mkdir(exist_ok=True)
        os.utime(path, (0, 0))
    upd.Updater(host)._prune({})
    assert release.is_dir(), "the OS factory remains the root-local fallback"
    assert not obsolete.exists()


@pytest.mark.parametrize("change", ["hardlink", "writable"])
def test_unsafe_existing_signature_is_not_adopted_or_replaced(tmp_path, monkeypatch, change):
    first, _, other, _, _, _, release = _device(tmp_path, monkeypatch)
    target = other / "opt/rosy/releases" / FACTORY_ID / "SHA256SUMS.sig"
    target.write_bytes((release / "SHA256SUMS.sig").read_bytes())
    if change == "hardlink":
        os.link(target, other / "signature-alias")
    else:
        target.chmod(0o666)
    before = target.read_bytes()
    with pytest.raises(ValueError):
        first._native_helper("os_factory_release").prepare_factory(other)
    assert target.read_bytes() == before
