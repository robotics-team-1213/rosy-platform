"""Durable pending state reconstructs motion inhibition; no hardware is commanded."""
import importlib
import json

import pytest

from test_os_bootloader import _boot, _trial
from test_os_update_state import TRANSACTION, TRIAL_BOOT


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
    for phase in ("TRIAL", "HEALTHY", "COMMIT_INTENT"):
        with state.locked(root) as store:
            store.transition(TRANSACTION, phase, TRIAL_BOOT,
                             health_sha256="b" * 64 if phase == "HEALTHY" else None)
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
    installer = (frozen / "rosy-os-rauc.service").read_text()
    assert "rosy-os-motion-guard.service" in next(line for line in installer.splitlines() if line.startswith("Requires="))
    assert "Conflicts=rosy-io.service rosy-navigation.service" in installer
    assert "After=rosy-io.service rosy-navigation.service" in installer
    starts = [line for line in installer.splitlines() if line.startswith("ExecStartPre=")]
    assert "os_motion_guard.py reconcile" in starts[0]
    assert "os_rauc_service.py check" in starts[1]


def test_guard_units_and_privileged_preconditions_parse_with_real_systemd(tmp_path):
    import shutil
    import subprocess
    from pathlib import Path
    base = Path(__file__).resolve().parents[1] / "deploy/robot/pinky_pro/native"
    units = tmp_path / "etc/systemd/system"
    units.mkdir(parents=True)
    shutil.copyfile(base / "rosy-os-motion-guard.service", units / "rosy-os-motion-guard.service")
    for name in ("sysinit.target", "basic.target", "shutdown.target", "sockets.target", "local-fs.target"):
        (units / name).write_text("[Unit]\nDefaultDependencies=no\n")
    (units / "rosy-os-storage.service").write_text(
        "[Unit]\nDefaultDependencies=no\nAfter=local-fs.target\n[Service]\nType=oneshot\nExecStart=/usr/bin/true\n")
    for name in ("core", "io", "navigation"):
        unit = f"rosy-{name}.service"
        (units / unit).write_text("[Service]\nExecStart=/usr/bin/true\nEnvironmentFile=-/etc/rosy/runtime.env\n")
        dropin = units / (unit + ".d")
        dropin.mkdir()
        shutil.copyfile(base / f"rosy-os-{name}-guard.conf", dropin / "zz-rosy-os-guard.conf")
    binaries = tmp_path / "usr/bin"
    binaries.mkdir(parents=True)
    for name in ("python3", "true"):
        path = binaries / name
        path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o755)
    analyze = shutil.which("systemd-analyze")
    assert analyze, "systemd parser is required in the Ubuntu test environment"
    result = subprocess.run([analyze, "verify", "--man=no", "--root=" + str(tmp_path),
        "rosy-os-motion-guard.service", "rosy-core.service", "rosy-io.service", "rosy-navigation.service"],
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
