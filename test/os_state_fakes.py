"""A file-only model of PID1 and sandbox mount views; never mounts a device."""
import hashlib
import json
import os
import stat
from types import SimpleNamespace

from auto_update_fakes import BOOT, REPO, write_json
from test_os_state_admission import DESCRIPTOR

GENERATION = "a87be39d-02d8-4a95-9208-570ed7506cd2"


def projected_device(root, monkeypatch):
    descriptor = root / "etc/rosy/os-slot.json"
    write_json(descriptor, DESCRIPTOR)
    (root / "proc/cmdline").write_text(
        f"root=PARTUUID={DESCRIPTOR['root_partuuid']} rosy.os_layout=ab-v1\n", encoding="ascii")
    mounts = []
    lines = []
    device_stats = {}
    for role, mountpoint, device, guid, filesystem, number in [
        ("root", "/", "8:1", DESCRIPTOR["root_partuuid"], "ext4", 1),
        ("data", "/var/lib/rosy-device", "8:6", DESCRIPTOR["data_partuuid"], "ext4", 6),
        ("provision", "/run/rosy-provision-boot", "8:2", DESCRIPTOR["provision_partuuid"], "vfat", 2),
    ]:
        mount_id = 100 + number
        mounts.append(dict(role=role, mount_id=mount_id, device=device, root="/", mountpoint=mountpoint,
                           filesystem=filesystem, options=["rw", "relatime"], super_options=["rw"]))
        lines.append(f"{mount_id} 0 {device} / {mountpoint} rw,relatime - {filesystem} /dev/sda{number} rw\n")
        target = root / mountpoint.lstrip("/")
        target.mkdir(parents=True, exist_ok=True)
        device_stats[str(target)] = (os.makedev(8, number), None)
        node = root / "proc/1/root/dev/disk/by-partuuid" / guid
        node.parent.mkdir(parents=True, exist_ok=True)
        node.write_bytes(b"not a real device")
        device_stats[str(node)] = (None, os.makedev(8, number))
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
               boot_id=BOOT, slot="a", descriptor_sha256=hashlib.sha256(descriptor.read_bytes()).hexdigest(),
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
