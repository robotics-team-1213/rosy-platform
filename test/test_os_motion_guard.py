"""Durable pending state reconstructs motion inhibition; no hardware is commanded."""
import importlib
import json
from pathlib import Path

import pytest

from test_os_bootloader import _boot, _trial
from test_os_update_state import _advance, TRANSACTION, TRIAL_BOOT


def test_pending_reconstructs_no_drive_after_runtime_directory_is_lost(tmp_path, monkeypatch):
    _, _, root, _, _ = _boot(tmp_path, monkeypatch, "INSTALLING")
    guard = importlib.import_module("os_motion_guard")
    assert guard.reconcile(root) is True
    environment = root / guard.ENVIRONMENT
    assert environment.read_text() == "ROSY_IO_DRIVE_ENABLED=false\n"
    assert environment.stat().st_mode & 0o777 == 0o600
    assert environment.parent.stat().st_mode & 0o777 == 0o700
    with pytest.raises(ValueError, match="OS_MOTION_HOLD"):
        guard.allow_navigation(root)
    environment.unlink()
    assert guard.reconcile(root) is True
    assert environment.read_text() == "ROSY_IO_DRIVE_ENABLED=false\n"


@pytest.mark.parametrize("damage", ["missing", "corrupt", "wrong_default"])
def test_unknown_state_fails_closed_and_keeps_false_environment(tmp_path, monkeypatch, damage):
    _, _, root, journal, config = _boot(tmp_path, monkeypatch)
    guard = importlib.import_module("os_motion_guard")
    if damage == "missing": journal.unlink()
    elif damage == "corrupt": journal.write_text("{")
    else: config.write_text("unknown")
    with pytest.raises(ValueError):
        guard.reconcile(root)
    assert (root / guard.ENVIRONMENT).read_text() == "ROSY_IO_DRIVE_ENABLED=false\n"
    with pytest.raises(ValueError):
        guard.allow_navigation(root)


def test_committed_trial_restores_operator_controls_without_rewriting_them(tmp_path, monkeypatch):
    _, state, root, _, config = _boot(tmp_path, monkeypatch, "ARMED")
    guard = importlib.import_module("os_motion_guard")
    operator = root / "etc/rosy/runtime.env"
    operator.write_text("ROSY_IO_DRIVE_ENABLED=true\n")
    _trial(root)
    assert guard.reconcile(root) is True
    _advance(state, root, "COMMIT_INTENT")
    from os_bootloader import autoboot
    config.write_bytes(autoboot("b"))
    with state.locked(root) as store:
        store.commit(TRANSACTION, TRIAL_BOOT)
    assert guard.reconcile(root) is False
    assert not (root / guard.ENVIRONMENT).exists()
    assert operator.read_text() == "ROSY_IO_DRIVE_ENABLED=true\n"
    guard.allow_navigation(root)


@pytest.mark.parametrize("damage", ["symlink", "hardlink", "foreign", "wide_directory"])
def test_guard_refuses_foreign_runtime_state(tmp_path, monkeypatch, damage):
    _, _, root, _, _ = _boot(tmp_path, monkeypatch)
    guard = importlib.import_module("os_motion_guard")
    assert guard.reconcile(root) is False
    path = root / guard.ENVIRONMENT
    if damage == "wide_directory":
        path.parent.chmod(0o755)
    elif damage == "symlink":
        victim = root / "victim"
        victim.write_text("untouched")
        path.symlink_to(victim)
    elif damage == "hardlink":
        path.write_text("ROSY_IO_DRIVE_ENABLED=false\n")
        path.chmod(0o600)
        import os
        os.link(path, path.with_suffix(".alias"))
    else:
        path.write_text("ROSY_IO_DRIVE_ENABLED=true\n")
        path.chmod(0o600)
    with pytest.raises(ValueError):
        guard.reconcile(root)
    if damage == "symlink":
        assert victim.read_text() == "untouched"


def test_image_owns_guard_and_final_environmentfile_after_operator_environment(tmp_path, monkeypatch):
    from test_os_factory_release import _device, FACTORY_ID
    from test_os_frozen_firstboot import _prefix, _stage
    from test_os_ab_root_configuration import _configurer
    from test_image_layer_sync import sync_mod
    _, root, _, _, _, _, _ = _device(tmp_path, monkeypatch)
    slot = root / "etc/rosy/os-slot.json"
    slot.write_text(json.dumps(dict(json.loads(slot.read_text()), schema_version=2)))
    _stage(_prefix(root))
    _configurer().configure(root, FACTORY_ID)
    frozen = root / "opt/rosy/os-bootstrap/native-runtime"
    assert (frozen / "os_motion_guard.py").is_file()
    for unit, source in (("core", "rosy-os-core-guard.conf"), ("io", "rosy-os-io-guard.conf"),
                         ("navigation", "rosy-os-navigation-guard.conf")):
        relative = f"etc/systemd/system/rosy-{unit}.service.d/zz-rosy-os-guard.conf"
        content = (root / relative).read_text()
        assert content == (frozen / source).read_text()
        assert "Requires=rosy-os-motion-guard.service" in content
        assert "After=rosy-os-motion-guard.service" in content
        with pytest.raises(ValueError, match="IMAGE_LAYER_DESTINATION"):
            sync_mod.check_destination(relative)
        with pytest.raises(ValueError, match="IMAGE_LAYER_DESTINATION"):
            sync_mod.check_destination(f"etc/systemd/system/rosy-{unit}.service.d/zzz-override.conf")
    io = (frozen / "rosy-os-io-guard.conf").read_text()
    assert "EnvironmentFile=-/run/rosy-os-update/motion.env" in io
    nav = (frozen / "rosy-os-navigation-guard.conf").read_text()
    assert "os_motion_guard.py navigation" in nav
    unit = (root / "etc/systemd/system/rosy-os-motion-guard.service").read_text()
    assert unit == (frozen / "rosy-os-motion-guard.service").read_text()
    assert "After=rosy-os-storage.service" in unit
    assert "Before=rosy-core.service rosy-io.service rosy-navigation.service" in unit
    assert "os_motion_guard.py reconcile" in unit
