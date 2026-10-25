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
        accounts = [("rosy-core", 960), ("rosy-io", 961), ("rosy-display", 962), ("rosy-camera", 963), ("rosy", 1001)]
        (root / "etc/passwd").write_text("".join(
            f"{name}:x:{uid}:{uid}::{('/home/rosy' if name == 'rosy' else '/nonexistent')}:"
            f"{('/bin/bash' if name == 'rosy' else '/usr/sbin/nologin')}\n" for name, uid in accounts), encoding="ascii")
        (root / "etc/group").write_text("".join(f"{name}:x:{uid}:\n" for name, uid in accounts), encoding="ascii")
        zone = root / "usr/share/zoneinfo/Etc/UTC"
        zone.parent.mkdir(parents=True)
        zone.write_bytes(b"TZif synthetic UTC payload")
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
                "var/lib/rosy/ssh": common / "ssh", "home/rosy/.ssh": common / "operator-ssh",
                "etc/rosy/tls": common / "tls", "var/lib/tailscale": common / "tailscale/machine"}
    (common / "tailscale/join").mkdir(parents=True, mode=0o700)
    mountpoints = set()
    for root, (_, host_table, local_table) in zip(roots, tables):
        (root / "run/rosy-os-state/ready.json").unlink()
        for relative, backing in bindings.items():
            backing.mkdir(parents=True, exist_ok=True)
            if relative in ("var/lib/rosy/core", "home/rosy/.ssh"):
                backing.chmod(0o750 if relative == "var/lib/rosy/core" else 0o700)
            elif relative == "etc/rosy/tls":
                backing.chmod(0o750)
            elif relative == "var/lib/tailscale":
                backing.chmod(0o700)
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
    original_lstat, original_stat, original_open, original_fstat = os.lstat, os.stat, os.open, os.fstat

    def mount_key(path, dir_fd=None):
        if isinstance(path, int):
            return None
        name = os.fsdecode(path)
        if dir_fd is not None and not os.path.isabs(name):
            name = os.path.join(os.readlink(f"/proc/self/fd/{dir_fd}"), name)
        return os.path.abspath(name)

    def bind_stat(path, *args, **kwargs):
        key = mount_key(path, kwargs.get("dir_fd"))
        if key in mountpoints:
            kwargs = {**kwargs, "follow_symlinks": True}
        info = original_stat(path, *args, **kwargs)
        if key in mountpoints and not key.endswith("/run/rosy-provision-boot"):
            fields = {name: getattr(info, name) for name in dir(info) if name.startswith("st_")}
            fields["st_dev"] = os.makedev(8, 6)
            if key.endswith("/var/lib/rosy/core"):
                fields.update(st_uid=960, st_gid=960)
            elif key.endswith("/home/rosy/.ssh"):
                fields.update(st_uid=1001, st_gid=1001)
            elif key.endswith("/etc/rosy/tls"):
                fields.update(st_gid=960)
            return SimpleNamespace(**fields)
        return info

    def bind_open(path, flags, *args, **kwargs):
        if mount_key(path, kwargs.get("dir_fd")) in mountpoints:
            flags &= ~getattr(os, "O_NOFOLLOW", 0)
        return original_open(path, flags, *args, **kwargs)

    def bind_lstat(path, *args, **kwargs):
        if not isinstance(path, int) and os.fspath(path) in mountpoints:
            info = os.stat(path)
            fields = {name: getattr(info, name) for name in dir(info) if name.startswith("st_")}
            fields["st_mode"] = stat.S_IFDIR | stat.S_IMODE(info.st_mode)
            return SimpleNamespace(**fields)
        return original_lstat(path, *args, **kwargs)

    def bind_fstat(descriptor):
        info = original_fstat(descriptor)
        path = os.readlink(f"/proc/self/fd/{descriptor}")
        identity = {str(common / "core"): (960, 960), str(common / "operator-ssh"): (1001, 1001),
                    str(common / "tls"): (common.stat().st_uid, 960)}.get(path)
        if identity is None:
            return info
        fields = {name: getattr(info, name) for name in dir(info) if name.startswith("st_")}
        fields.update(st_uid=identity[0], st_gid=identity[1], st_dev=os.makedev(8, 6))
        return SimpleNamespace(**fields)

    # Real binds look like directories to lstat. Only the explicitly modeled
    # mountpoints get this metadata; arbitrary symlinks keep their real type.
    monkeypatch.setattr(os, "lstat", bind_lstat)
    monkeypatch.setattr(os, "stat", bind_stat)
    monkeypatch.setattr(os, "open", bind_open)
    monkeypatch.setattr(os, "fstat", bind_fstat)
    capabilities = set(os.supports_dir_fd)
    if original_open in capabilities:
        capabilities.add(bind_open)
    if original_stat in capabilities:
        capabilities.add(bind_stat)
    monkeypatch.setattr(os, "supports_dir_fd", capabilities)
    return roots[0], roots[1], common, boot_volume
