"""Read-only watchdog admission uses modeled firmware/sysfs/PID1 observations."""
import importlib
import json
import subprocess

import pytest

from test_os_bootloader import _boot
from test_os_update_state import SOURCE_BOOT

IDENTITY = "Broadcom BCM2835 Watchdog timer"
CONFIG = "# ROSY A/B kernel watchdog\n[all]\nkernel_watchdog_timeout=180\n"


def _watchdog(tmp_path, monkeypatch):
    _, _, root, _, _ = _boot(tmp_path, monkeypatch)
    module = importlib.import_module("os_update_watchdog")
    (root / "boot/firmware/config.txt").write_text("[pi5]\n" + CONFIG)
    command = root / "proc/cmdline"
    (root / "boot/firmware/cmdline.txt").write_text(command.read_text())
    command.write_text(command.read_text().strip() + " watchdog.open_timeout=180\n")
    values = {"sys/module/watchdog/parameters/open_timeout": "180",
              "sys/class/watchdog/watchdog0/state": "active",
              "sys/class/watchdog/watchdog0/timeout": "10",
              "sys/class/watchdog/watchdog0/identity": IDENTITY}
    for name, value in values.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value + "\n")
    properties = dict(RuntimeWatchdogUSec="10s", RebootWatchdogUSec="10s",
                      WatchdogDevice="/dev/watchdog0", Version="255.4-1ubuntu8.12")
    logs = [dict(_BOOT_ID=SOURCE_BOOT.replace("-", ""), _PID="1", _UID="0", _COMM="systemd",
                 __MONOTONIC_TIMESTAMP=str(i), MESSAGE=message) for i, message in enumerate([
        f"Using hardware watchdog '{IDENTITY}', version 0, device /dev/watchdog0",
        "Watchdog running with a timeout of 10s."], 100)]
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        if argv[0] == "/usr/bin/systemctl":
            data = "\n".join(k + "=" + v for k, v in properties.items())
        else:
            assert argv[0] == "/usr/bin/journalctl" and "_PID=1" in argv
            assert "--boot=" + SOURCE_BOOT.replace("-", "") in argv
            data = "\n".join(json.dumps(row) for row in logs)
        return subprocess.CompletedProcess(argv, 0, data, "")
    return module, root, properties, logs, calls, run


def test_live_watchdog_proof_is_boot_bound_and_never_opens_a_device(tmp_path, monkeypatch):
    module, root, _, _, calls, run = _watchdog(tmp_path, monkeypatch)
    result = module.admit(root, run=run)
    assert result["boot_id"] == SOURCE_BOOT and result["timeout_seconds"] == 10
    assert result["device"] == "/dev/watchdog0" and result["identity"] == IDENTITY
    assert len(calls) == 2
    assert all(argv[0] in ("/usr/bin/systemctl", "/usr/bin/journalctl") for argv in calls)
    assert not (root / "dev/watchdog0").exists()


@pytest.mark.parametrize("damage", ["firmware_missing", "firmware_duplicate", "file_injected", "config",
    "open_timeout", "state", "timeout", "identity", "manager_runtime", "manager_reboot", "manager_device",
    "version", "journal_missing", "journal_boot", "journal_pid", "journal_uid", "journal_order",
    "journal_failure", "journal_timeout"])
def test_unknown_or_inconsistent_watchdog_support_never_authorizes_arm(tmp_path, monkeypatch, damage):
    module, root, properties, logs, _, run = _watchdog(tmp_path, monkeypatch)
    if damage == "firmware_missing":
        (root / "proc/cmdline").write_text((root / "boot/firmware/cmdline.txt").read_text())
    elif damage == "firmware_duplicate":
        path = root / "proc/cmdline"
        path.write_text(path.read_text().strip() + " watchdog.open_timeout=180\n")
    elif damage == "file_injected":
        (root / "boot/firmware/cmdline.txt").write_text((root / "proc/cmdline").read_text())
    elif damage == "config": (root / "boot/firmware/config.txt").write_text("kernel_watchdog_timeout=0\n")
    elif damage in ("open_timeout", "state", "timeout", "identity"):
        name = "sys/module/watchdog/parameters/open_timeout" if damage == "open_timeout" else "sys/class/watchdog/watchdog0/" + damage
        (root / name).write_text("unknown\n")
    elif damage.startswith("manager_"):
        key = {"manager_runtime": "RuntimeWatchdogUSec", "manager_reboot": "RebootWatchdogUSec", "manager_device": "WatchdogDevice"}[damage]
        properties[key] = "0"
    elif damage == "version": properties["Version"] = "256"
    elif damage == "journal_missing": logs.clear()
    elif damage == "journal_boot": logs[1]["_BOOT_ID"] = "0" * 32
    elif damage == "journal_pid": logs[1]["_PID"] = "2"
    elif damage == "journal_uid": logs[1]["_UID"] = "1000"
    elif damage == "journal_order": logs.reverse()
    elif damage == "journal_failure":
        logs.append(dict(logs[-1], __MONOTONIC_TIMESTAMP="102", MESSAGE="Failed to ping watchdog"))
    else: logs[1]["MESSAGE"] = "Watchdog running with a timeout of 15s."
    with pytest.raises(ValueError, match="OS_WATCHDOG_HOLD"):
        module.admit(root, run=run)


@pytest.mark.parametrize("source", [b"\xff", b"bad\0config", b"x" * 65537])
def test_invalid_offline_boot_config_is_rejected(source):
    module = importlib.import_module("os_update_watchdog")
    with pytest.raises(ValueError):
        module.render_boot_config(source)


def test_watchdog_boot_config_preserves_overlays_and_ends_in_unconditional_handoff():
    module = importlib.import_module("os_update_watchdog")
    source = b"[pi5]\ndtoverlay=uart0-pi5\nkernel_watchdog_timeout=0\n"
    rendered = module.render_boot_config(source)
    assert rendered.startswith(source.decode()) and rendered.endswith(CONFIG)
    assert module.render_boot_config(rendered.encode()) == rendered


@pytest.mark.parametrize("protocol", [1, 2])
def test_image_installs_watchdog_and_stops_active_root_apt_only_for_protocol2(tmp_path, monkeypatch, protocol):
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
    assert (frozen / "os_update_watchdog.py").is_file()
    destination = "etc/systemd/system.conf.d/90-rosy-os-watchdog.conf"
    if protocol == 2:
        assert (root / destination).read_bytes() == (frozen / "rosy-os-watchdog.conf").read_bytes()
        text = (root / destination).read_text()
        assert "RuntimeWatchdogSec=10s" in text and "RebootWatchdogSec=10s" in text
        assert "WatchdogDevice=/dev/watchdog0" in text
    else: assert not (root / destination).exists()
    with pytest.raises(ValueError, match="IMAGE_LAYER_DESTINATION"):
        sync_mod.check_destination(destination)
    for unit in ("apt-daily.timer", "apt-daily.service", "apt-daily-upgrade.timer",
                 "apt-daily-upgrade.service", "unattended-upgrades.service"):
        destination = f"etc/systemd/system/{unit}.d/90-rosy-os.conf"
        if protocol == 2:
            assert (root / destination).read_bytes() == (frozen / "rosy-os-no-apt.conf").read_bytes()
            assert "ConditionPathExists=!/etc/rosy/os-slot.json" in (root / destination).read_text()
        else: assert not (root / destination).exists()
        with pytest.raises(ValueError, match="IMAGE_LAYER_DESTINATION"):
            sync_mod.check_destination(destination)
