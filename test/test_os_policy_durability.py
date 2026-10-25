"""Verify persistence barriers of actual policy writers; not physical powercut proof."""
import datetime as dt
import os
from pathlib import Path
import stat

import pytest

from auto_update_fakes import device, host, hub, keys, updater
from os_state_fakes import projected_device


def _trace(monkeypatch):
    events = []
    fsync, replace, chmod, unlink = os.fsync, os.replace, os.chmod, Path.unlink

    def traced_fsync(fd):
        info = os.fstat(fd)
        events.append(("dir" if stat.S_ISDIR(info.st_mode) else "file", info.st_ino))
        return fsync(fd)

    def traced_replace(source, target):
        events.append(("replace", str(target)))
        return replace(source, target)

    def traced_chmod(path, mode, *args, **kwargs):
        events.append(("mode", str(path)))
        return chmod(path, mode, *args, **kwargs)

    def traced_unlink(path, *args, **kwargs):
        events.append(("unlink", str(path)))
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "fsync", traced_fsync)
    monkeypatch.setattr(os, "replace", traced_replace)
    monkeypatch.setattr(os, "chmod", traced_chmod)
    monkeypatch.setattr(Path, "unlink", traced_unlink)
    return events


def test_hold_mode_and_contents_are_synced_before_publish_then_parent(device, host, hub, monkeypatch):
    common, _, _ = projected_device(device, monkeypatch)
    worker = updater(host, hub)
    events = _trace(monkeypatch)
    worker.hold("fixture", "fixture maintenance", 1)
    path = device / "var/lib/rosy-device/policy/updates/hold.json"
    mode = events.index(("mode", str(path.with_name(".hold.json.tmp"))))
    content = events.index(("file", path.stat().st_ino))
    publish = events.index(("replace", str(path)))
    parent = events.index(("dir", path.parent.stat().st_ino))
    assert mode < content < publish < parent


@pytest.mark.parametrize("expired", [False, True])
def test_hold_deletion_is_durable_for_release_and_expiry(device, host, hub, monkeypatch, expired):
    common, _, _ = projected_device(device, monkeypatch)
    worker = updater(host, hub)
    worker.hold("fixture", "fixture maintenance", 1)
    if expired:
        host.t += dt.timedelta(hours=2)
    events = _trace(monkeypatch)
    worker._expire_hold() if expired else worker.release_hold()
    path = device / "var/lib/rosy-device/policy/updates/hold.json"
    assert not path.exists()
    deleted = events.index(("unlink", str(path)))
    synced = events.index(("dir", path.parent.stat().st_ino))
    assert deleted < synced
