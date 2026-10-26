"""Actual frozen staging and offline systemd parser; PID1 boot sequencing remains SYSTEM acceptance."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from test_os_frozen_firstboot import BASE, _prefix, _stage


@pytest.mark.parametrize("protocol", [1, 2])
def test_lifecycle_timer_and_units_are_frozen_and_installed_only_for_new_images(tmp_path, monkeypatch, protocol):
    from test_os_factory_release import _device, FACTORY_ID
    from test_os_ab_root_configuration import _configurer
    from test_image_layer_sync import sync_mod
    _, root, _, _, _, _, _ = _device(tmp_path, monkeypatch)
    slot = root / "etc/rosy/os-slot.json"
    slot.write_text(json.dumps(dict(json.loads(slot.read_text()), schema_version=protocol)))
    _stage(_prefix(root))
    _configurer().configure(root, FACTORY_ID)
    frozen = root / "opt/rosy/os-bootstrap/native-runtime"
    for name, destination in {
        "rosy-os-update.service": "etc/systemd/system/rosy-os-update.service",
        "rosy-os-update.timer": "etc/systemd/system/rosy-os-update.timer",
        "rosy-os-update-boot.conf": "etc/systemd/system/sysinit.target.d/20-rosy-os-update.conf",
    }.items():
        assert (frozen / name).is_file()
        if protocol == 2: assert (root / destination).read_bytes() == (frozen / name).read_bytes()
        else: assert not (root / destination).exists()
        with pytest.raises(ValueError, match="IMAGE_LAYER_DESTINATION"): sync_mod.check_destination(destination)
    result = subprocess.run([sys.executable, "-I", "-B", str(frozen / "os_update_controller.py"), "--help"],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0 and "resume" in result.stdout


def test_controller_unit_has_runtime_configuration_without_waiting_for_its_own_deadline():
    unit = (BASE / "native/rosy-os-update.service").read_text()
    assert "EnvironmentFile=/etc/rosy/runtime.env" in unit
    assert "os_update_controller.py resume" in unit
    assert "ConditionPathIsDirectory=/var/lib/rosy-device/os-update" in unit
    assert "ProtectSystem=strict" in unit and "DevicePolicy=closed" in unit
    assert "DeviceAllow=block-mmc r" in unit and "DeviceAllow=block-mmc rw" not in unit
    assert "PrivateDevices=true" not in unit
    assert "rosy-os-trial-deadline" not in unit  # Independent deadline cannot wait for this controller.


def test_actual_systemd_parser_checks_timer_and_boot_dependency_graph(tmp_path):
    units = tmp_path / "etc/systemd/system"
    units.mkdir(parents=True)
    for name in ("rosy-os-update.service", "rosy-os-update.timer", "rosy-os-trial-deadline.service", "rosy-os-trial-deadline.timer"):
        shutil.copyfile(BASE / "native" / name, units / name)
    for name in ("sysinit.target", "basic.target", "shutdown.target", "timers.target", "local-fs.target", "network-online.target"):
        (units / name).write_text("[Unit]\nDefaultDependencies=no\n")
    for name in ("rosy-os-storage.service", "rosy-os-motion-guard.service", "rosy-first-boot.service", "rosy-sd-provision.service",
                 "rosy-release-recover.service", "rosy-core.service", "rosy-io.service"):
        (units / name).write_text("[Unit]\nDefaultDependencies=no\n[Service]\nType=oneshot\nExecStart=/usr/bin/python3\n")
    dropin = units / "sysinit.target.d"
    dropin.mkdir()
    for source, target in (("rosy-os-deadline.conf", "10-rosy-os-deadline.conf"), ("rosy-os-update-boot.conf", "20-rosy-os-update.conf")):
        shutil.copyfile(BASE / "native" / source, dropin / target)
    binary = tmp_path / "usr/bin/python3"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    analyze = shutil.which("systemd-analyze")
    assert analyze
    result = subprocess.run([analyze, "verify", "--man=no", "--root=" + str(tmp_path), "sysinit.target", "rosy-os-update.service",
                             "rosy-os-update.timer", "rosy-os-trial-deadline.timer"], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
