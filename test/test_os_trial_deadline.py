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
