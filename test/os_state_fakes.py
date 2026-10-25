"""A file-only model of PID1 and sandbox mount views; never mounts a device."""
import hashlib
import json
import os
import stat
from types import SimpleNamespace

from auto_update_fakes import REPO, write_json
from test_os_state_admission import DESCRIPTOR

GENERATION = "a87be39d-02d8-4a95-9208-570ed7506cd2"
BOOT = "a8f1b6c8-678f-43fe-bdfc-a93d2465a1c8"


def projected_device(root, monkeypatch, *, slot="a", split_disk=False):
    layout = dict(DESCRIPTOR, slot=slot)
    if slot == "b":
        layout["root_partuuid"] = "c26f0d91-9c91-48fe-a1c2-fcb14ec3ed5c"
    descriptor = root / "etc/rosy/os-slot.json"
    (root / "proc/sys/kernel/random/boot_id").write_text(BOOT + "\n", encoding="ascii")
    write_json(descriptor, layout)
    (root / "proc/cmdline").write_text(
        f"root=PARTUUID={layout['root_partuuid']} rosy.os_layout=ab-v1\n", encoding="ascii")
    mounts = []
    lines = []
    device_stats = {}
    for role, mountpoint, device, guid, filesystem, number in [
        ("root", "/", "8:4" if slot == "a" else "8:5", layout["root_partuuid"], "ext4", 4 if slot == "a" else 5),
        ("data", "/var/lib/rosy-device", "8:22" if split_disk else "8:6", layout["data_partuuid"], "ext4", 6),
        ("provision", "/run/rosy-provision-boot", "8:2", layout["provision_partuuid"], "vfat", 2),
    ]:
        mount_id = 100 + number
        mounts.append(dict(role=role, mount_id=mount_id, device=device, root="/", mountpoint=mountpoint,
                           filesystem=filesystem, options=["relatime", "rw"], super_options=["rw"]))
        disk = "sdb" if split_disk and role == "data" else "sda"
        lines.append(f"{mount_id} 0 {device} / {mountpoint} rw,relatime - {filesystem} /dev/{disk}{number} rw\n")
        partition = root / f"sys/devices/platform/fixture/block/{disk}/{disk}{number}"
        partition.mkdir(parents=True, exist_ok=True)
        (partition / "partition").write_text(str(number) + "\n", encoding="ascii")
        syslink = root / "sys/dev/block" / device
        syslink.parent.mkdir(parents=True, exist_ok=True)
        syslink.symlink_to(partition, target_is_directory=True)
        major, minor = map(int, device.split(":"))
        target = root / mountpoint.lstrip("/")
        target.mkdir(parents=True, exist_ok=True)
        device_stats[str(target)] = (os.makedev(major, minor), None)
        node = root / "proc/1/root/dev/disk/by-partuuid" / guid
        node.parent.mkdir(parents=True, exist_ok=True)
        node.write_bytes(b"not a real device")
        device_stats[str(node)] = (None, os.makedev(major, minor))
    host_mountinfo = root / "proc/1/mountinfo"
    host_mountinfo.parent.mkdir(parents=True, exist_ok=True)
    host_mountinfo.write_text("".join(lines), encoding="ascii")
    self_mountinfo = root / "proc/self/mountinfo"
    self_mountinfo.parent.mkdir(parents=True, exist_ok=True)
    self_mountinfo.write_text("".join(lines).replace(" rw,relatime -", " ro,relatime -"), encoding="ascii")
    common = root / "var/lib/rosy-device"
    write_json(common / "state/schema.json", dict(schema_version=1, state_schema=1))
    write_json(common / "state/current.json", dict(schema_version=1, state_schema=1,
               generation=GENERATION, manifest_sha256="a" * 64))
    write_json(common / "policy/updates/config.json", dict(enabled=False, repo=REPO))
    write_json(root / "run/rosy-os-state/ready.json", dict(schema_version=1, phase="PROJECTED",
               boot_id=BOOT, slot=slot, descriptor_sha256=hashlib.sha256(descriptor.read_bytes()).hexdigest(),
               generation=GENERATION, projection_sha256="a" * 64, mounts=mounts))
    original = os.stat

    def fake_stat(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        values = device_stats.get(os.fspath(path)) if not isinstance(path, int) else None
        if values is None:
            return result
        fields = {name: getattr(result, name) for name in dir(result) if name.startswith("st_")}
        if values[0] is not None:
            fields["st_dev"] = values[0]
        if values[1] is not None:
            fields.update(st_mode=stat.S_IFBLK | 0o600, st_rdev=values[1])
        return SimpleNamespace(**fields)

    monkeypatch.setattr(os, "stat", fake_stat)
    return common, host_mountinfo, self_mountinfo
