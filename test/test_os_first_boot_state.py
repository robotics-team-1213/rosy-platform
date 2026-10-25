"""Firstboot consumers must prepare each root, even when common completion exists."""
import json

import pytest

from os_state_boot_fakes import shared_roots
from test_first_boot_provisioning import _bundle, _module

SERIAL = "10000000abcdef01"


def _provision_a(tmp_path, monkeypatch):
    root_a, root_b, common, boot = shared_roots(tmp_path, monkeypatch)
    bundle = boot / "rosy-provision/provision.json"
    bundle.parent.mkdir()
    bundle.write_text(json.dumps(_bundle()), encoding="utf-8")
    module = _module()
    first = module.FirstBootProvisioner(root=root_a, network_activate=lambda _: True)
    report = first.apply(bundle=bundle, hardware_serial=SERIAL)
    assert report["state"] == "PROVISIONED", report
    assert not bundle.exists()
    assert (root_b / "var/lib/rosy/provisioning/complete.json").exists()
    return module, root_a, root_b, common, bundle


def test_committed_identity_and_runtime_are_projected_before_b_is_already_provisioned(tmp_path, monkeypatch):
    module, root_a, root_b, _, bundle = _provision_a(tmp_path, monkeypatch)
    report = module.FirstBootProvisioner(root=root_b, network_activate=lambda _: True).apply(
        bundle=bundle, hardware_serial=SERIAL)
    assert report["ok"] is True, report
    for name in ("etc/rosy/device-identity.json", "etc/rosy/runtime.env", "etc/hostname"):
        target = root_b / name
        assert target.is_file(), f"common completion did not prepare B: {name}"
        assert target.read_bytes() == (root_a / name).read_bytes()
    assert not bundle.exists(), "B must recover from committed state without a new card bundle"


def test_common_completion_without_its_committed_generation_is_a_hold(tmp_path, monkeypatch):
    module, _, root_b, common, bundle = _provision_a(tmp_path, monkeypatch)
    (common / "state/current.json").unlink(missing_ok=True)
    with pytest.raises(ValueError, match="OS_STATE_HOLD"):
        module.FirstBootProvisioner(root=root_b, network_activate=lambda _: True).apply(
            bundle=bundle, hardware_serial=SERIAL)


def test_another_identity_cached_in_b_does_not_gain_common_completion(tmp_path, monkeypatch):
    module, _, root_b, _, bundle = _provision_a(tmp_path, monkeypatch)
    identity = _bundle()["device_identity"]
    identity["device_uid"] = "118cc587-047a-455d-babe-75573533a736"
    (root_b / "etc/rosy/device-identity.json").write_text(json.dumps(identity), encoding="ascii")
    with pytest.raises(ValueError, match="OS_STATE_HOLD"):
        module.FirstBootProvisioner(root=root_b, network_activate=lambda _: True).apply(
            bundle=bundle, hardware_serial=SERIAL)


def test_bind_fixture_does_not_allow_an_unmanaged_core_symlink(tmp_path, monkeypatch):
    root_a, _, common, boot = shared_roots(tmp_path, monkeypatch)
    external = tmp_path / "unmanaged-core"
    external.mkdir()
    (common / "core/.rosy").symlink_to(external, target_is_directory=True)
    bundle = boot / "rosy-provision/provision.json"
    bundle.parent.mkdir()
    bundle.write_text(json.dumps(_bundle()), encoding="utf-8")
    with pytest.raises(ValueError, match="symlink|not a directory|OS_STATE_HOLD"):
        _module().FirstBootProvisioner(root=root_a, network_activate=lambda _: True).apply(
            bundle=bundle, hardware_serial=SERIAL)
    assert list(external.iterdir()) == []
