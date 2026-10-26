"""Real bounded GPT reads with modeled Linux mounts/sysfs/block identity; no device writes."""
import importlib
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from test_ab_image_layout import module
from test_sd_gpt_layout import _table_image


def _card(tmp_path, monkeypatch, slot="a"):
    module()  # source native/sd import roots, as in the image builder
    m = importlib.import_module("os_media")
    raw, layout = _table_image()
    layout["provision_role"] = "bootstrap"
    root = tmp_path / "root"
    (root / "etc/rosy").mkdir(parents=True)
    (root / "proc").mkdir()
    parts = {p["role"]: p for p in layout["partitions"]}
    descriptor = dict(schema_version=2, state_schema=1, slot=slot,
        root_partuuid=parts["root_" + slot]["unique_guid"], data_partuuid=parts["data"]["unique_guid"],
        provision_partuuid=parts["bootstrap"]["unique_guid"])
    (root / "etc/rosy/os-slot.json").write_text(json.dumps(descriptor))
    (root / "etc/rosy/os-media.json").write_text(json.dumps(layout))
    (root / "proc/cmdline").write_text(f"root=PARTUUID={descriptor['root_partuuid']} rosy.os_layout=ab-v2 rauc.slot={slot}\n")
    disk = root / "sys/devices/virtual/block/sda"
    disk.mkdir(parents=True)
    (disk / "dev").write_text("8:0\n")
    (disk / "size").write_text(str(len(raw) // 512 + 4096))
    aliases = root / "sys/dev/block"
    aliases.mkdir(parents=True)
    for number in range(1, 7):
        part = disk / ("sda" + str(number))
        part.mkdir()
        (part / "partition").write_text(str(number))
        (part / "dev").write_text(f"8:{number}")
        (part / "start").write_text(str(layout["partitions"][number - 1]["start_lba"]))
        (part / "size").write_text(str(layout["partitions"][number - 1]["size_lba"]))
        (aliases / f"8:{number}").symlink_to(part, target_is_directory=True)
    device = root / "proc/1/root/dev/block/8:0"
    device.parent.mkdir(parents=True)
    device.write_bytes(raw)
    boot = 2 if slot == "a" else 3
    rows = [f"1 0 8:{4 if slot == 'a' else 5} / / rw - ext4 /dev/root rw\n",
            f"2 0 8:{boot} / /boot/firmware rw - vfat /dev/boot rw\n",
            "3 0 8:1 / /run/rosy-provision-boot rw - vfat /dev/provision rw\n",
            "4 0 8:6 / /var/lib/rosy-device rw - ext4 /dev/data rw\n"]
    for view in ("1", "self"):
        path = root / f"proc/{view}/mountinfo"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(rows))
    (root / "boot/firmware").mkdir(parents=True)
    admitted = []
    def mount_facts(observed_root, observed_layout):
        assert observed_root == root and observed_layout == descriptor
        admitted.append(True)
        return [dict(role="root", device=f"8:{4 if slot == 'a' else 5}")]
    monkeypatch.setattr(m, "mount_facts", mount_facts)
    actual_stat, actual_fstat = os.stat, os.fstat
    def changed(info, **values):
        return SimpleNamespace(**{**{n: getattr(info, n) for n in dir(info) if n.startswith("st_")}, **values})
    def fixture_stat(path, *args, **kwargs):
        info = actual_stat(path, *args, **kwargs)
        return changed(info, st_dev=os.makedev(8, boot)) if os.fspath(path) == str(root / "boot/firmware") else info
    def fixture_fstat(fd):
        info = actual_fstat(fd)
        path = os.readlink(f"/proc/self/fd/{fd}")
        if path == str(device):
            return changed(info, st_mode=stat.S_IFBLK | 0o600, st_rdev=os.makedev(8, 0))
        if Path(path).is_relative_to(root / "sys"):
            return changed(info, st_size=4096)
        return info
    monkeypatch.setattr(os, "stat", fixture_stat)
    monkeypatch.setattr(os, "fstat", fixture_fstat)
    return m, root, layout, disk, device, admitted


@pytest.mark.parametrize("slot", ["a", "b"])
def test_capture_reads_actual_gpt_and_identifies_inactive_root_and_boot(tmp_path, monkeypatch, slot):
    m, root, layout, _, device, admitted = _card(tmp_path, monkeypatch, slot)
    before = device.read_bytes()
    snapshot = m.capture(root)
    assert admitted
    assert snapshot["layout"] == layout and snapshot["slot"] == slot
    assert snapshot["disk_device"] == "8:0"
    assert snapshot["partitions"]["root_b"]["device"] == "8:5"
    assert snapshot["partitions"]["boot_a"]["path"] == "/dev/block/8:2"
    assert device.read_bytes() == before


@pytest.mark.parametrize("number", range(1, 7))
@pytest.mark.parametrize("attribute", ["start", "size"])
def test_unchanged_gpt_cannot_authorize_stale_kernel_partition_ranges(tmp_path, monkeypatch, number, attribute):
    m, root, _, disk, device, _ = _card(tmp_path, monkeypatch)
    path = disk / ("sda" + str(number)) / attribute
    path.write_text(str(int(path.read_text()) + 1))
    before = device.read_bytes()
    with pytest.raises(ValueError, match="kernel partition range"):
        m.capture(root)
    assert device.read_bytes() == before


@pytest.mark.parametrize("case", ["bad_gpt", "foreign_snapshot", "wrong_descriptor", "old_protocol",
    "wrong_boot", "mounted_inactive_root", "mounted_inactive_boot", "private_inactive_mount",
    "small_disk", "duplicate_device", "wrong_parent", "wrong_rauc_slot"])
def test_capture_refuses_unsafe_or_ambiguous_media(tmp_path, monkeypatch, case):
    m, root, layout, disk, device, _ = _card(tmp_path, monkeypatch)
    if case == "bad_gpt":
        raw = bytearray(device.read_bytes()); raw[-512 + 16] ^= 1; device.write_bytes(raw)
    elif case == "foreign_snapshot":
        layout["disk_guid"] = "757086a0-ec11-43f8-87ab-6fdebf513636"
        (root / "etc/rosy/os-media.json").write_text(json.dumps(layout))
    elif case == "wrong_descriptor":
        path = root / "etc/rosy/os-slot.json"
        value = json.loads(path.read_text()); value["provision_partuuid"] = layout["partitions"][1]["unique_guid"]
        path.write_text(json.dumps(value))
    elif case == "old_protocol":
        layout["provision_role"] = "boot_a"
        (root / "etc/rosy/os-media.json").write_text(json.dumps(layout))
    elif case == "wrong_boot":
        path = root / "proc/1/mountinfo"
        path.write_text(path.read_text().replace("8:2", "8:3"))
    elif case in ("mounted_inactive_root", "mounted_inactive_boot", "private_inactive_mount"):
        view = "self" if case == "private_inactive_mount" else "1"
        number = 3 if case == "mounted_inactive_boot" else 5
        with (root / f"proc/{view}/mountinfo").open("a") as handle:
            handle.write(f"99 0 8:{number} / /foreign rw - ext4 /dev/foreign rw\n")
    elif case == "small_disk":
        (disk / "size").write_text("64")
    elif case == "duplicate_device":
        (disk / "sda5/dev").write_text("8:4")
    elif case == "wrong_parent":
        (disk / "dev").write_text("8:16")
    else:
        path = root / "proc/cmdline"
        path.write_text(path.read_text().replace("rauc.slot=a", "rauc.slot=b"))
    before = device.read_bytes()
    with pytest.raises(ValueError):
        m.capture(root)
    assert device.read_bytes() == before
