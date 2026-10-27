"""ARM SYSTEM firmware-input fixture; synthetic DT never represents Pi acceptance or a release build."""
import importlib
import os
import json
from pathlib import Path
import shlex
import io
from types import SimpleNamespace

import pytest


def module():
    return importlib.import_module("os_system_arm_vm")


def test_arm_guest_has_owned_virtio_card_and_kernel_nocloud_without_host_devices(tmp_path):
    guest = module().ArmGuest(tmp_path)
    argv = guest.command(22022, 22023)
    assert argv[0].endswith("/qemu-system-aarch64")
    assert argv[argv.index("-machine") + 1] == "virt-8.2,gic-version=3"
    assert "-dtb" in argv and str(tmp_path / "firmware.dtb") in argv
    assert "ds=nocloud-net;s=http://10.0.2.2:22023/" in argv[argv.index("-append") + 1]
    drives = [v for k, v in zip(argv, argv[1:]) if k == "-drive"]
    assert len(drives) == 3 and all(v.startswith("file=" + str(tmp_path) + "/") for v in drives)
    assert any("ab-media.raw" in v for v in drives)


def stopped_guest(tmp_path, monkeypatch):
    guest = module().ArmGuest(tmp_path)
    guest.process = SimpleNamespace(poll=lambda: 0, wait=lambda **k: 0)
    guest.stderr = io.BytesIO()
    guest.env = {}
    guest.server = SimpleNamespace(server_port=22023)
    guest.ssh_port = 22022
    calls = []
    monkeypatch.setattr(guest, "run", lambda command, **kw:
                        guest.instance_id if "instance-id" in command else "")
    monkeypatch.setattr(guest, "_ssh", lambda *a, **k: SimpleNamespace(returncode=0))
    monkeypatch.setattr(module().subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    def launch(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(poll=lambda: None)
    monkeypatch.setattr(module().subprocess, "Popen", launch)
    return guest, calls


def test_trial_start_can_observe_recovery_without_waiting_for_ssh(tmp_path, monkeypatch):
    guest, calls = stopped_guest(tmp_path, monkeypatch)
    monkeypatch.setattr(guest, "wait_boot", lambda: pytest.fail("trial recovery must not require SSH readiness"))
    guest.restart_slot("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "b", trial=True, wait=False)
    assert len(calls) == 1
    assert "rauc.slot=b" in calls[0][calls[0].index("-append") + 1]
    assert guest.slot == "b"


def test_observer_restarts_original_cloud_without_source_slot_recovery(tmp_path, monkeypatch):
    guest, calls = stopped_guest(tmp_path, monkeypatch)
    guest.slot = "b"
    ready = []
    monkeypatch.setattr(guest, "wait_boot", lambda: ready.append(True))
    guest.start_observer()
    assert ready == [True] and len(calls) == 1
    arguments = calls[0][calls[0].index("-append") + 1]
    assert arguments.startswith("root=/dev/vda1 ") and "rauc.slot=" not in arguments


@pytest.mark.parametrize("returncode", [None, -15])
def test_observer_refuses_live_or_abnormally_exited_guest(tmp_path, monkeypatch, returncode):
    guest, calls = stopped_guest(tmp_path, monkeypatch)
    guest.process = SimpleNamespace(poll=lambda: returncode)
    with pytest.raises(ValueError):
        guest.start_observer()
    assert calls == []


@pytest.mark.skipif(os.environ.get("ROSY_RUN_OS_SYSTEM_TESTS") != "1", reason="explicit disposable ARM SYSTEM guest opt-in")
@pytest.mark.parametrize("source_slot", ["a", "b"])
def test_actual_arm_kernel_exposes_strict_synthetic_boot_properties(tmp_path, source_slot):
    """Actual kernel/PID1/card/RAUC boundaries; DT, policy and native application are fixtures."""
    with module().ArmGuest(tmp_path) as guest:
        assert guest.run("uname -m").strip() == "aarch64"
        assert guest.run("cat /proc/1/comm").strip() == "systemd"
        assert guest.run("readlink -f /proc/device-tree").strip() == "/sys/firmware/devicetree/base"
        assert guest.run("od -An -tx1 /proc/device-tree/chosen/bootloader/partition").split() == ["00", "00", "00", "02"]
        assert guest.run("od -An -tx1 /proc/device-tree/chosen/bootloader/tryboot").split() == ["00", "00", "00", "00"]
        assert "virtio" in guest.run("readlink -f /sys/class/block/vdc/device")
        guest.provision_source(Path(__file__).resolve().parents[1])
        layout = json.loads(guest.run("cd /work/source && ROSY_OS_GUEST=1 python3 test/os_system_card.py "
                                     "--work /work/card --initial-slot " + source_slot, timeout=1800))
        scenario = ("cd /work/source && ROSY_OS_GUEST=1 python3 test/os_system_install.py "
                    "{command} --source-slot " + source_slot + " --instance-id " + shlex.quote(guest.instance_id))
        assert json.loads(guest.run(scenario.format(command="snapshot"), timeout=1800))["snapshot"] is True
        root_uuid = next(p["unique_guid"] for p in layout["partitions"] if p["role"] == "root_" + source_slot)
        guest.restart_slot(root_uuid, source_slot)
        assert guest.run("findmnt -n -o SOURCE /").strip() == ("/dev/vdc4" if source_slot == "a" else "/dev/vdc5")
        facts = guest.run("python3 -c \"import sys,json;sys.path.insert(0,'/opt/rosy/os-bootstrap/native-runtime');from os_media import capture;print(json.dumps(capture()))\"")
        media = json.loads(facts)
        assert media["slot"] == source_slot and media["layout"] == layout
        target_slot = "b" if source_slot == "a" else "a"
        installed = json.loads(guest.run(scenario.format(command="install"), timeout=5400))
        assert installed["installed"] is True
        assert installed["receipt"]["target_slot"] == target_slot
        assert installed["device_policy"]["probes"]["root_" + target_slot] is True
        assert installed["device_policy"]["probes"]["root_" + source_slot] is False
        mounted = installed["device_policy"]["mounted_devices"]
        assert media["partitions"]["boot_" + target_slot]["device"] not in mounted
        assert all(media["partitions"][role]["device"] in mounted for role in ("bootstrap", "data"))
        # Fault injection: select an installed but unarmed trial. Independent PID1 deadline must recover.
        target_root = next(p["unique_guid"] for p in layout["partitions"] if p["role"] == "root_" + target_slot)
        guest.restart_slot(target_root, target_slot, trial=True)
        assert guest.run("findmnt -n -o SOURCE /").strip() == ("/dev/vdc5" if target_slot == "b" else "/dev/vdc4")
        assert guest.run("od -An -tx1 /proc/device-tree/chosen/bootloader/tryboot").split() == ["00", "00", "00", "01"]
        assert guest.run("systemctl is-active rosy-os-trial-deadline.timer").strip() == "active"
        assert "OnBootSec=180s" in guest.run("systemctl cat rosy-os-trial-deadline.timer")
        boot = guest.run("cat /proc/sys/kernel/random/boot_id").strip()
        journal = guest._ssh("stdbuf -oL journalctl --boot --follow "
                             "--unit=rosy-os-trial-deadline.service --output=json --no-pager", timeout=240)
        importlib.import_module("os_system_vm").pid1_start(
            journal.stdout, "rosy-os-trial-deadline.service", boot, 180_000_000)
        assert guest.process.wait(timeout=90) == 0  # QEMU -no-reboot exits on the guest's reboot request.
        console = (tmp_path / "guest-console.log").read_text(errors="replace")
        assert "reboot: Restarting system" in console
