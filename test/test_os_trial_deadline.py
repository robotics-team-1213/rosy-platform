"""Deadline executes no host reboot; DT/storage are modeled and systemd is parsed offline."""
import importlib
import json
from pathlib import Path
import struct
import subprocess

import pytest

from test_os_bootloader import _boot, _trial
from test_os_update_state import TRANSACTION, TRIAL_BOOT


def test_normal_boot_never_probes_failed_storage_or_reboots(tmp_path, monkeypatch):
    _, _, root, journal, _ = _boot(tmp_path, monkeypatch)
    module = importlib.import_module("os_trial_deadline")
    journal.unlink()
    def forbidden(*args):
        pytest.fail("normal boot must not inspect common state or request reboot")
    assert module.expire(root, probe=forbidden, run=forbidden) is False


@pytest.mark.parametrize("damage", ["pending", "journal", "descriptor", "bootstrap"])
def test_uncommitted_trial_requests_only_normal_nonforced_reboot(tmp_path, monkeypatch, damage):
    _, _, root, journal, config = _boot(tmp_path, monkeypatch, "ARMED")
    _trial(root)
    if damage == "journal": journal.unlink()
    elif damage == "descriptor": (root / "etc/rosy/os-slot.json").write_text("{")
    elif damage == "bootstrap": config.unlink()
    module = importlib.import_module("os_trial_deadline")
    calls = []
    assert module.expire(root, probe=module.committed, run=lambda argv: calls.append(argv)) is True
    assert calls == [["systemctl", "--no-block", "reboot"]]


def test_committed_same_boot_trial_flag_does_not_trigger_reboot(tmp_path, monkeypatch):
    boot, state, root, _, config = _boot(tmp_path, monkeypatch, "ARMED")
    _trial(root)
    for phase in ("TRIAL", "HEALTHY", "COMMIT_INTENT"):
        with state.locked(root) as store:
            store.transition(TRANSACTION, phase, TRIAL_BOOT,
                             health_sha256="b" * 64 if phase == "HEALTHY" else None)
    config.write_bytes(boot.autoboot("b"))
    with state.locked(root) as store:
        store.commit(TRANSACTION, TRIAL_BOOT)
    module = importlib.import_module("os_trial_deadline")
    calls = []
    assert module.expire(root, probe=module.committed, run=lambda argv: calls.append(argv)) is False
    assert calls == []


@pytest.mark.parametrize("raw", [b"", b"\x01", struct.pack(">I", 2)])
def test_unknown_firmware_flag_is_hold_without_reboot(tmp_path, monkeypatch, raw):
    _, _, root, _, _ = _boot(tmp_path, monkeypatch)
    (root / "proc/device-tree/chosen/bootloader/tryboot").write_bytes(raw)
    module = importlib.import_module("os_trial_deadline")
    calls = []
    with pytest.raises(ValueError):
        module.expire(root, probe=lambda r: False, run=lambda argv: calls.append(argv))
    assert calls == []


def test_storage_probe_timeout_kills_child_without_waiting_again(tmp_path, monkeypatch):
    module = importlib.import_module("os_trial_deadline")
    calls = []
    class Child:
        def wait(self, timeout):
            calls.append(("wait", timeout))
            raise subprocess.TimeoutExpired("fixture", timeout)
        def kill(self):
            calls.append(("kill",))
    def spawn(argv, **kwargs):
        assert argv[-3:] == ["committed", "--root", str(tmp_path)]
        assert kwargs["stdout"] == subprocess.DEVNULL and kwargs["stderr"] == subprocess.DEVNULL
        return Child()
    monkeypatch.setattr(module.subprocess, "Popen", spawn)
    assert module.probe_committed(tmp_path) is False
    assert calls == [("wait", 3), ("kill",)]


def test_test_root_cannot_accidentally_invoke_host_reboot(tmp_path, monkeypatch):
    _, _, root, _, _ = _boot(tmp_path, monkeypatch, "ARMED")
    _trial(root)
    module = importlib.import_module("os_trial_deadline")
    with pytest.raises(ValueError, match="real root"):
        module.expire(root, probe=lambda r: False)


@pytest.mark.parametrize("protocol", [1, 2])
def test_deadline_is_frozen_and_early_only_on_new_images(tmp_path, monkeypatch, protocol):
    from test_os_factory_release import _device, FACTORY_ID
    from test_os_frozen_firstboot import _prefix, _stage
    from test_os_ab_root_configuration import _configurer
    from test_image_layer_sync import sync_mod
    _, root, _, _, _, _, _ = _device(tmp_path, monkeypatch)
    slot = root / "etc/rosy/os-slot.json"
    slot.write_text(json.dumps(dict(json.loads(slot.read_text()), schema_version=protocol)))
    _stage(_prefix(root))
    _configurer().configure(root, FACTORY_ID)
    frozen = root / "opt/rosy/os-bootstrap/native-runtime"
    assert (frozen / "os_trial_deadline.py").is_file()
    assets = {"rosy-os-trial-deadline.service": "etc/systemd/system/rosy-os-trial-deadline.service",
              "rosy-os-trial-deadline.timer": "etc/systemd/system/rosy-os-trial-deadline.timer",
              "rosy-os-deadline.conf": "etc/systemd/system/sysinit.target.d/10-rosy-os-deadline.conf"}
    for source, target in assets.items():
        if protocol == 2:
            assert (root / target).read_bytes() == (frozen / source).read_bytes()
        else:
            assert not (root / target).exists()
        with pytest.raises(ValueError, match="IMAGE_LAYER_DESTINATION"):
            sync_mod.check_destination(target)
    timer = (frozen / "rosy-os-trial-deadline.timer").read_text()
    service = (frozen / "rosy-os-trial-deadline.service").read_text()
    assert "DefaultDependencies=no" in timer and "DefaultDependencies=no" in service
    assert "Before=local-fs.target" in timer and "OnBootSec=180s" in timer
    assert "AccuracySec=1s" in timer
    assert "Wants=rosy-os-trial-deadline.timer" in (frozen / "rosy-os-deadline.conf").read_text()
    assert not any(x in service for x in ("Requires=", "After=local-fs", "RequiresMountsFor=", "rosy-os-storage"))
    assert "os_trial_deadline.py expire" in service


def test_actual_stalled_child_is_bounded_and_reaped_only_by_test_cleanup(tmp_path, monkeypatch):
    import time
    module = importlib.import_module("os_trial_deadline")
    script = tmp_path / "stalled-probe.py"
    script.write_text("import time\ntime.sleep(60)\n")
    monkeypatch.setattr(module, "__file__", str(script))
    spawn, children = subprocess.Popen, []
    def tracked(*args, **kwargs):
        child = spawn(*args, **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(module.subprocess, "Popen", tracked)
    started = time.monotonic()
    try:
        assert module.probe_committed(tmp_path) is False
        assert time.monotonic() - started < 8
    finally:
        for child in children:
            child.kill()
            child.wait(timeout=3)


def test_real_systemd_parser_accepts_deadline_without_localfs_dependency(tmp_path):
    import shutil
    base = Path(__file__).resolve().parents[1] / "deploy/robot/pinky_pro/native"
    units = tmp_path / "etc/systemd/system"
    units.mkdir(parents=True)
    for name in ("rosy-os-trial-deadline.service", "rosy-os-trial-deadline.timer"):
        shutil.copyfile(base / name, units / name)
    for name in ("sysinit.target", "basic.target", "shutdown.target", "timers.target", "local-fs.target"):
        (units / name).write_text("[Unit]\nDefaultDependencies=no\n")
    dropin = units / "sysinit.target.d"
    dropin.mkdir()
    shutil.copyfile(base / "rosy-os-deadline.conf", dropin / "10-rosy-os-deadline.conf")
    binary = tmp_path / "usr/bin/python3"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    analyze = shutil.which("systemd-analyze")
    assert analyze
    result = subprocess.run([analyze, "verify", "--man=no", "--root=" + str(tmp_path),
        "sysinit.target", "rosy-os-trial-deadline.timer", "rosy-os-trial-deadline.service"],
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("is_committed", [False, True])
def test_committed_probe_runs_from_frozen_install_with_poisoned_mutable_sdk(tmp_path, monkeypatch, is_committed):
    import sys
    from test_os_frozen_firstboot import _prefix, _stage
    boot, state, root, _, config = _boot(tmp_path / "device", monkeypatch, "ARMED" if is_committed else None)
    if is_committed:
        _trial(root)
        for phase in ("TRIAL", "HEALTHY", "COMMIT_INTENT"):
            with state.locked(root) as store:
                store.transition(TRANSACTION, phase, TRIAL_BOOT,
                                 health_sha256="b" * 64 if phase == "HEALTHY" else None)
        config.write_bytes(boot.autoboot("b"))
        with state.locked(root) as store:
            store.commit(TRANSACTION, TRIAL_BOOT)
    prefix = _prefix(tmp_path / "installed")
    _stage(prefix)
    for folder in (prefix / "native-runtime", prefix / "deploy/sd"):
        for path in folder.glob("*.py"):
            path.write_text("raise RuntimeError('mutable SDK imported')\n")
    # Kernel mounts are modeled; actual frozen boot/state parsing and CLI execute.
    code = """
import sys
from pathlib import Path
frozen=Path(sys.argv[1])/'os-bootstrap/native-runtime'
sys.path[:0]=[str(frozen),str(Path(sys.argv[1])/'native-runtime')]
import os_update_state,os_trial_deadline
os_update_state.mount_facts=lambda *args: []
assert os_trial_deadline.main(['committed','--root',sys.argv[2]]) == int(sys.argv[3])
for name in ('os_trial_deadline','os_bootloader','os_update_state','os_state_layout','os_update_manifest','media_layout'):
    assert Path(sys.modules[name].__file__).is_relative_to(frozen)
"""
    result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(prefix), str(root), str(int(not is_committed))],
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
