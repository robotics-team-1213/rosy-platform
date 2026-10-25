"""Offline A/B root assembly installs OS-owned overrides, not legacy global changes."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

from test_os_factory_release import _device, FACTORY_ID
from test_os_frozen_firstboot import _prefix, _stage, BASE


def _configurer():
    spec = importlib.util.spec_from_file_location("configure_ab_root", BASE / "image/configure-ab-root.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_offline_root_installs_frozen_boot_and_recovery_with_its_factory_binding(tmp_path, monkeypatch):
    _, root, _, _, _, _, release = _device(tmp_path, monkeypatch)
    _stage(_prefix(root))
    _configurer().configure(root, FACTORY_ID)
    descriptor = json.loads((root / "etc/rosy/os-factory-release.json").read_text())
    assert descriptor == dict(schema_version=1, release_id=FACTORY_ID,
        checksums_sha256=hashlib.sha256((release / "SHA256SUMS").read_bytes()).hexdigest())
    units = root / "etc/systemd/system"
    first = (units / "rosy-first-boot.service.d/10-rosy-os.conf").read_text()
    recover = (units / "rosy-release-recover.service.d/10-rosy-os.conf").read_text()
    assert "os_storage_dispatch.py --first-boot" in first
    assert "os_boot_recover.py" in recover
    assert "Wants=rosy-sd-provision.service" in recover
    assert "After=rosy-sd-provision.service" in recover
    assert "Requires=rosy-sd-provision.service" not in recover
    assert "ProtectHome=read-only" in recover
    _configurer().configure(root, FACTORY_ID)  # Identical assembly is idempotent.


@pytest.mark.parametrize("change", ["foreign_override", "invalid_slot", "duplicate_partuuid", "hardlink_descriptor"])
def test_offline_root_refuses_conflicting_or_invalid_boot_configuration(tmp_path, monkeypatch, change):
    _, root, _, _, _, _, _ = _device(tmp_path, monkeypatch)
    _stage(_prefix(root))
    if change == "foreign_override":
        path = root / "etc/systemd/system/rosy-release-recover.service.d/10-rosy-os.conf"
        path.parent.mkdir(parents=True)
        path.write_text("[Service]\nExecStart=/foreign/command\n")
    elif change == "hardlink_descriptor":
        os.link(root / "etc/rosy/os-factory-release.json", root / "factory-descriptor-alias")
    else:
        path = root / "etc/rosy/os-slot.json"
        value = json.loads(path.read_text())
        if change == "invalid_slot":
            value["slot"] = "c"
        else:
            value["data_partuuid"] = value["root_partuuid"]
        path.write_text(json.dumps(value))
    before = (root / "etc/rosy/os-factory-release.json").read_bytes()
    with pytest.raises(ValueError):
        _configurer().configure(root, FACTORY_ID)
    assert not (root / "etc/systemd/system/rosy-first-boot.service.d/10-rosy-os.conf").exists()
    assert (root / "etc/rosy/os-factory-release.json").read_bytes() == before
