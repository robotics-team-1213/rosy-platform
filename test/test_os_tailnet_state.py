"""Tailnet identity may cross slots, never the hardware binding of a moved card."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from os_state_boot_fakes import shared_roots
from test_first_boot_provisioning import _module
from test_os_first_boot_state import SERIAL, _provision_a


def _serial(root, value=SERIAL):
    target = root / "proc/device-tree/serial-number"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(value.encode("ascii") + b"\0")


def test_same_board_keeps_machine_identity_across_a_b_a(tmp_path, monkeypatch):
    first, root_a, root_b, common, bundle = _provision_a(tmp_path, monkeypatch)
    gate = first._native_helper("os_state_storage")
    _serial(root_a)
    assert gate.admit_tailnet(root_a, bind_machine=True)["phase"] == "TAILNET_BOUND"
    binding = (common / "tailscale/machine-binding.json").read_bytes()
    (root_a / "var/lib/tailscale/tailscaled.state").write_bytes(b"fixture-machine-credential")
    for root in (root_b, root_a):
        _serial(root)
        assert first.FirstBootProvisioner(root=root).apply(bundle=bundle, hardware_serial=SERIAL)["ok"]
        assert gate.admit_tailnet(root)["phase"] == "TAILNET_BOUND"
        assert (root / "var/lib/tailscale/tailscaled.state").read_bytes() == b"fixture-machine-credential"
        assert (common / "tailscale/machine-binding.json").read_bytes() == binding


@pytest.mark.parametrize("change", ["different_board", "missing_serial", "foreign_uid", "unbound_state"])
def test_tailnet_cannot_adopt_old_or_unbound_machine_authority(tmp_path, monkeypatch, change):
    first, root, _, common, _ = _provision_a(tmp_path, monkeypatch)
    gate = first._native_helper("os_state_storage")
    _serial(root)
    gate.admit_tailnet(root, bind_machine=True)
    path = common / "tailscale/machine-binding.json"
    if change == "different_board":
        _serial(root, "10000000abcdef02")
    elif change == "missing_serial":
        (root / "proc/device-tree/serial-number").unlink()
    elif change == "foreign_uid":
        record = json.loads(path.read_text())
        record["device_uid"] = "62ad707c-7a54-4413-b1e2-3c909b54ae4e"
        path.write_text(json.dumps(record))
    else:
        path.unlink()
    state = common / "tailscale/machine/tailscaled.state"
    state.write_bytes(b"fixture-machine-credential")
    before = path.read_bytes() if path.exists() else None
    with pytest.raises((OSError, ValueError)):
        gate.admit_tailnet(root, bind_machine=True)
    assert state.read_bytes() == b"fixture-machine-credential"
    assert (path.read_bytes() if path.exists() else None) == before


def test_factory_network_can_start_but_tailnet_requires_committed_identity(tmp_path, monkeypatch):
    root, _, _, _ = shared_roots(tmp_path, monkeypatch)
    gate = _module()._native_helper("os_state_storage")
    _serial(root)
    assert gate.admit_storage(root)["phase"] == "FACTORY_EMPTY"
    with pytest.raises(ValueError, match="committed"):
        gate.admit_tailnet(root, bind_machine=True)


def test_missing_machine_bind_is_rejected_before_network_storage_admission(tmp_path, monkeypatch):
    root, _, _, _ = shared_roots(tmp_path, monkeypatch)
    for relative in ("proc/1/mountinfo", "proc/self/mountinfo"):
        path = root / relative
        path.write_text("\n".join(line for line in path.read_text().splitlines()
                                  if " /var/lib/tailscale " not in line) + "\n")
    with pytest.raises(ValueError, match="OS_STATE_HOLD"):
        _module()._native_helper("os_state_storage").admit_storage(root)


def test_offline_enable_requires_tailnet_gate_for_daemon_and_join(tmp_path):
    native = Path(__file__).resolve().parents[1] / "deploy/robot/pinky_pro/native"
    directory = tmp_path / "etc/systemd/system"
    directory.mkdir(parents=True)
    unit = "rosy-os-tailnet.service"
    shutil.copy2(native / unit, directory / unit)
    result = subprocess.run(["systemctl", "--root", str(tmp_path), "enable", unit],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    for consumer in ("tailscaled.service", "rosy-tailscale-join.service"):
        assert (directory / (consumer + ".requires") / unit).is_symlink()
    text = (directory / unit).read_text()
    assert "Before=tailscaled.service rosy-tailscale-join.service" in text
    assert "--tailnet" in text and "PartOf=tailscaled.service" in text
    assert "Requires=rosy-os-storage.service" in text
    assert "Wants=rosy-first-boot.service" in text


def test_successful_firstboot_retries_tailnet_without_waiting_on_its_dependents():
    source = Path(__file__).resolve().parents[1] / "deploy/robot/pinky_pro/image/first-boot"
    text = (source / "rosy-first-boot.service").read_text()
    assert "ExecStartPost=-/usr/bin/systemctl start --no-block tailscaled.service rosy-tailscale-join.service" in text
