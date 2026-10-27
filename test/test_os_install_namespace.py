"""Denied PID1 namespace links still require kernel proof of a separate mount tree."""
import importlib
import os
from pathlib import Path
import sys

import pytest

BASE = Path(__file__).resolve().parents[1] / "deploy/robot/pinky_pro"
sys.path.insert(0, str(BASE / "sd"))
sys.path.insert(0, str(BASE / "native"))


def _view(root, monkeypatch, fault=None):
    module = importlib.import_module("os_update_install")
    for name, identity in (("self", 2), ("1", 1)):
        path = root / f"proc/{name}/ns/mnt"
        path.parent.mkdir(parents=True)
        path.symlink_to(f"mnt:[{identity}]")
    host = "1 0 8:4 / / rw - ext4 /dev/vda1 rw\n"
    local = "2 0 8:4 / / ro - ext4 /dev/vda1 rw\n"
    if fault == "same": local = local.replace("2 0", "1 0")
    if fault == "bound_root": host += "2 1 8:4 / /bound rw - ext4 /dev/vda1 rw\n"
    if fault == "device": local = local.replace("8:4", "8:6")
    if fault == "missing_host": host = host.replace("/ / rw", "/ /elsewhere rw")
    if fault == "missing_local": local = local.replace("/ / ro", "/ /elsewhere ro")
    (root / "proc/1/mountinfo").write_text(host)
    (root / "proc/self/mountinfo").write_text(local)
    readlink, table = os.readlink, module._mount_table
    reads = []
    def limited_readlink(path, *args, **kwargs):
        if Path(path) == root / "proc/1/ns/mnt":
            raise PermissionError("PID1 namespace dereference requires ptrace authority")
        return readlink(path, *args, **kwargs)
    def observed_table(path, relative):
        value = table(path, relative)
        if relative == "proc/1/mountinfo":
            reads.append(relative)
            if fault == "race" and len(reads) == 2:
                value["/"][0]["mount_id"] = 3
        return value
    monkeypatch.setattr(os, "readlink", limited_readlink)
    monkeypatch.setattr(module, "_mount_table", observed_table)
    return module


def test_private_root_mount_not_in_stable_pid1_tree_needs_no_ptrace(tmp_path, monkeypatch):
    _view(tmp_path, monkeypatch)._namespace(tmp_path)


@pytest.mark.parametrize("fault", ["same", "bound_root", "device", "missing_host", "missing_local", "race"])
def test_missing_or_shared_or_racing_mount_tree_is_not_private(tmp_path, monkeypatch, fault):
    module = _view(tmp_path, monkeypatch, fault)
    with pytest.raises((ValueError, PermissionError)):
        module._namespace(tmp_path)
