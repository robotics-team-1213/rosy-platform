"""Moved A/B cards retain recovery access without transferring robot authority."""
import json

import pytest

from test_os_first_boot_state import SERIAL, _provision_a
from test_os_tailnet_state import _serial
from test_rebind_board import _fresh_bundle, _rebind


MOVED_SERIAL = "10000000abcdef02"


def test_staged_registration_cannot_resume_old_tailnet_on_original_board(tmp_path, monkeypatch):
    first, root, _, common, bundle = _provision_a(tmp_path, monkeypatch)
    result = first.FirstBootProvisioner(root=root).apply(bundle=bundle, hardware_serial=MOVED_SERIAL)
    assert result["state"] == "NEW_DEVICE_SETUP"
    _serial(root, SERIAL)
    with pytest.raises(ValueError, match="registration pending"):
        first._native_helper("os_state_storage").admit_tailnet(root, bind_machine=True)
    assert not (common / "tailscale/machine-binding.json").exists()


def test_repeated_moved_boots_keep_setup_identity_and_shared_recovery_state(tmp_path, monkeypatch):
    first, root, other, common, bundle = _provision_a(tmp_path, monkeypatch)
    gate = first._native_helper("os_state_storage")
    pointer = (common / "state/current.json").read_bytes()
    completion = (root / "var/lib/rosy/provisioning/complete.json").read_bytes()
    wifi = (root / "etc/NetworkManager/system-connections/rosy-site-sta.nmconnection").read_bytes()
    setup_name = None
    for target in (root, other, root, other):
        _serial(target, MOVED_SERIAL)
        applied = []
        report = first.FirstBootProvisioner(root=target, hostname_apply=applied.append).apply(
            bundle=bundle, hardware_serial=MOVED_SERIAL)
        assert report["state"] == "NEW_DEVICE_SETUP"
        assert report["ok"] is False
        setup_name = setup_name or report["device_name"]
        assert report["device_name"] == setup_name
        assert applied == []
        assert gate.admit_storage(target)["phase"] == "COMMITTED"
        with pytest.raises(ValueError, match="registration pending"):
            gate.admit_tailnet(target, bind_machine=True)
        assert (common / "state/current.json").read_bytes() == pointer
        assert (target / "var/lib/rosy/provisioning/complete.json").read_bytes() == completion
        assert (target / "etc/NetworkManager/system-connections/rosy-site-sta.nmconnection").read_bytes() == wifi
    pending = (root / "var/lib/rosy/provisioning/new-device-setup.json").read_bytes()
    with pytest.raises(ValueError, match="different board"):
        first.FirstBootProvisioner(root=root).apply(bundle=bundle, hardware_serial=SERIAL)
    assert (root / "var/lib/rosy/provisioning/new-device-setup.json").read_bytes() == pending
    assert json.loads(pending)["hardware_serial"] == MOVED_SERIAL


@pytest.mark.parametrize("marker", ["descriptor", "kernel_only", "malformed", "broken_link"])
def test_legacy_rebind_cannot_partially_move_shared_ab_state(tmp_path, monkeypatch, marker):
    _, root, _, common, _ = _provision_a(tmp_path, monkeypatch)
    fresh = _fresh_bundle(root)
    descriptor = root / "etc/rosy/os-slot.json"
    if marker == "kernel_only":
        descriptor.unlink()
    elif marker == "malformed":
        descriptor.write_text("{")
    elif marker == "broken_link":
        descriptor.unlink()
        descriptor.symlink_to(root / "missing-slot-descriptor")
    before = {p.relative_to(common): p.read_bytes() for p in common.rglob("*") if p.is_file()}
    with pytest.raises(ValueError, match="fresh.*card"):
        _rebind().quarantine_previous(root, fresh, MOVED_SERIAL)
    assert {p.relative_to(common): p.read_bytes() for p in common.rglob("*") if p.is_file()} == before
    assert not (root / "var/lib/rosy/previous-devices").exists()
