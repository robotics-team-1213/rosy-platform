"""Use visible aliases only when kernel mount records bind /dev to PID1's devtmpfs."""
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from os_state_boot_fakes import shared_roots
from os_state_layout import _layout, mount_facts


def _view(tmp_path, monkeypatch, *, change=None):
    root, _, _, _ = shared_roots(tmp_path, monkeypatch, protocol=2)
    host = root / "proc/1/mountinfo"
    local = root / "proc/self/mountinfo"
    host.write_text(host.read_text() + "900 1 0:5 / /dev rw - devtmpfs udev rw\n")
    local.write_text(local.read_text() + ("900 1 0:6 / /dev rw - tmpfs tmpfs rw\n"
                                        if change == "private" else "900 1 0:5 / /dev rw - devtmpfs udev rw\n"))
    visible = root / "dev/disk/by-partuuid"
    visible.mkdir(parents=True)
    hidden = root / "proc/1/root/dev/disk/by-partuuid"
    for p in hidden.iterdir():
        (visible / p.name).write_bytes(b"modeled device")
    if change == "ambiguous":
        first = next(visible.iterdir())
        (visible / first.name.upper()).write_bytes(b"duplicate alias")
    real_stat, real_listdir = os.stat, os.listdir

    def observed_stat(path, *args, **kwargs):
        p = None if isinstance(path, int) else Path(path)
        if p == root / "dev":
            info = real_stat(path, *args, **kwargs)
            return SimpleNamespace(**{**{n: getattr(info, n) for n in dir(info) if n.startswith("st_")},
                                      "st_dev": os.makedev(0, 7 if change == "directory" else 5)})
        if p is not None and p.parent == visible:
            info = real_stat(hidden / p.name, *args, **kwargs)
            if change == "wrong_device":
                return SimpleNamespace(st_mode=info.st_mode, st_rdev=os.makedev(8, 99))
            return info
        return real_stat(path, *args, **kwargs)

    def observed_listdir(path):
        if Path(path) == hidden:
            raise PermissionError("PID1 proc-root requires unavailable ptrace authority")
        return real_listdir(path)

    monkeypatch.setattr(os, "stat", observed_stat)
    monkeypatch.setattr(os, "listdir", observed_listdir)
    return root


def test_shared_devtmpfs_admits_without_pid1_proc_root_access(tmp_path, monkeypatch):
    root = _view(tmp_path, monkeypatch)
    assert [row["role"] for row in mount_facts(root, _layout(root)[0])] == ["root", "data", "provision"]


@pytest.mark.parametrize("change", ["private", "wrong_device", "ambiguous", "directory"])
def test_visible_device_view_cannot_replace_kernel_mount_or_partition_binding(tmp_path, monkeypatch, change):
    root = _view(tmp_path, monkeypatch, change=change)
    with pytest.raises((ValueError, PermissionError)):
        mount_facts(root, _layout(root)[0])
