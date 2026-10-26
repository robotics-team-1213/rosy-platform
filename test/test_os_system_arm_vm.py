"""ARM SYSTEM firmware-input fixture; synthetic DT never represents Pi acceptance or a release build."""
import importlib
import os

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


@pytest.mark.skipif(os.environ.get("ROSY_RUN_OS_SYSTEM_TESTS") != "1", reason="explicit disposable ARM SYSTEM guest opt-in")
def test_actual_arm_kernel_exposes_strict_synthetic_boot_properties(tmp_path):
    with module().ArmGuest(tmp_path) as guest:
        assert guest.run("uname -m").strip() == "aarch64"
        assert guest.run("cat /proc/1/comm").strip() == "systemd"
        assert guest.run("readlink -f /proc/device-tree").strip() == "/sys/firmware/devicetree/base"
        assert guest.run("od -An -tx1 /proc/device-tree/chosen/bootloader/partition").split() == ["00", "00", "00", "02"]
        assert guest.run("od -An -tx1 /proc/device-tree/chosen/bootloader/tryboot").split() == ["00", "00", "00", "00"]
        assert "virtio" in guest.run("readlink -f /sys/class/block/vdc/device")
