"""Two real root trees with shared backing directories and modeled bind metadata."""
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace

from os_state_fakes import projected_device


def shared_roots(tmp_path, monkeypatch):
    roots = [tmp_path / "root-a", tmp_path / "root-b"]
    tables = []
    for root, slot in zip(roots, ("a", "b")):
        (root / "etc/rosy").mkdir(parents=True)
        boot = root / "proc/sys/kernel/random/boot_id"
        boot.parent.mkdir(parents=True)
        boot.write_text("fixture")
        tables.append(projected_device(root, monkeypatch, slot=slot))
    common = tmp_path / "data"
    for root, destination in zip(roots, (common, tmp_path / "unused-b-factory")):
        original = root / "var/lib/rosy-device"
        assert original.resolve().is_relative_to(tmp_path.resolve())
        assert destination.absolute().is_relative_to(tmp_path.absolute())
        original.rename(destination)
    (common / "state/current.json").unlink()
    (common / "state/factory.json").write_text(json.dumps(dict(schema_version=1, state_schema=1,
        factory_id="d951d2aa-a022-4e72-8d56-82fdf428583c")), encoding="ascii")
    boot_volume = tmp_path / "boot-a"
    boot_volume.mkdir()
    bindings = {"var/lib/rosy-device": common, "run/rosy-provision-boot": boot_volume,
                "var/lib/rosy/provisioning": common / "provisioning",
                "var/lib/rosy/core": common / "core",
                "etc/NetworkManager/system-connections": common / "network/system-connections",
                "var/lib/rosy/ssh": common / "ssh", "home/rosy/.ssh": common / "operator-ssh"}
    mountpoints = set()
    for root, (_, host_table, local_table) in zip(roots, tables):
        (root / "run/rosy-os-state/ready.json").unlink()
        for relative, backing in bindings.items():
            backing.mkdir(parents=True, exist_ok=True)
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_dir():
                target.rmdir()  # only the empty provision mount fixture exists here
            target.symlink_to(backing, target_is_directory=True)
            mountpoints.add(str(target))
            if backing.is_relative_to(common) and backing != common:
                subpath = "/" + backing.relative_to(common).as_posix()
                with host_table.open("a", encoding="ascii") as handle:
                    handle.write(f"{300 + len(mountpoints)} 106 8:6 {subpath} /{relative} rw - ext4 /dev/sda6 rw\n")
        local_table.write_text(host_table.read_text(), encoding="ascii")
    original_lstat = os.lstat

    def bind_lstat(path, *args, **kwargs):
        if not isinstance(path, int) and os.fspath(path) in mountpoints:
            info = os.stat(path)
            fields = {name: getattr(info, name) for name in dir(info) if name.startswith("st_")}
            fields["st_mode"] = stat.S_IFDIR | stat.S_IMODE(info.st_mode)
            return SimpleNamespace(**fields)
        return original_lstat(path, *args, **kwargs)

    # Real binds look like directories to lstat. Only the explicitly modeled
    # mountpoints get this metadata; arbitrary symlinks keep their real type.
    monkeypatch.setattr(os, "lstat", bind_lstat)
    return roots[0], roots[1], common, boot_volume
