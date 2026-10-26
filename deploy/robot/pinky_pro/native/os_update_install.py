"""Current-code RAUC finalizer: inactive readback, four-file rebase, fsck and private receipt."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

from os_bootloader import _binding, _claim, _private, boot_facts, RAUC_STATE, BINDING
from os_installed_factory import verify as verify_factory
from os_media import capture
from os_motion_guard import require_inhibited
from os_slot_metadata import FILES, rebase_files
from os_state_io import _json_atomic, _write_atomic
from os_state_layout import _mount_table, _pairs, _path, _read
from os_update_manifest import _digest
from os_update_state import layout_digest, read_state

WORK = "run/rosy-os-update/rauc/mount/os-finalize"
REPORT_FIELDS = BINDING | {"native_factory", "metadata_sha256"}


def _run(argv, timeout=300):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                          env=dict(os.environ, LC_ALL="C"))


def _call(run, argv, timeout=300):
    result = run(argv, timeout=timeout)
    if result.returncode or len(result.stdout) > 65536 or len(result.stderr) > 16384:
        raise ValueError("inactive filesystem command failed")


def _pending(root):
    facts, pending = boot_facts(root), read_state(root)["pending"]
    if (pending is None or pending["phase"] not in {"INSTALLING", "INSTALLED", "VERIFIED"}
            or facts["tryboot"] or facts["slot"] != pending["source_slot"]
            or facts["boot_id"] != pending["source_boot_id"]):
        raise ValueError("finalization requires the bound installing source boot")
    _claim(root, pending)
    require_inhibited(root)
    return pending


def report_path(root: Path, pending=None) -> Path:
    pending = pending if pending is not None else read_state(root)["pending"]
    if pending is None:
        raise ValueError("no pending OS report owner")
    return _path(root, RAUC_STATE + "/installed-" + pending["transaction_id"] + ".json")


def read_report(root: Path) -> dict:
    pending = _pending(root)
    relative = report_path(root, pending).relative_to(root).as_posix()
    value = _private(root, relative, REPORT_FIELDS)
    if value is None or any(value[k] != v for k, v in _binding(pending).items()):
        raise ValueError("installed receipt binding differs or is missing")
    expected = dict(schema_version=1, **pending["verified"]["metadata"]["native_factory"])
    if value["native_factory"] != expected:
        raise ValueError("installed receipt factory differs")
    _digest(value["metadata_sha256"])
    return value


def _namespace(root):
    identities = [os.readlink(root / f"proc/{process}/ns/mnt") for process in ("self", "1")]
    if identities[0] == identities[1] or any(not re.fullmatch(r"mnt:\[[0-9]+\]", item) for item in identities):
        raise ValueError("finalization requires a private mount namespace")


def _fresh(root, pending):
    if _pending(root) != pending:
        raise ValueError("OS transaction changed during finalization")
    media = capture(root)
    if media["slot"] != pending["source_slot"] or layout_digest(media["layout"]) != pending["layout_sha256"]:
        raise ValueError("installed transaction media differs")
    return media


def _device_hash(root, part, image, capacity):
    size = image["size"]
    if not 0 < size <= capacity:
        raise ValueError("installed image exceeds inactive partition")
    node = root / part["path"].lstrip("/")
    digest = hashlib.sha256()
    with os.fdopen(os.open(node, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC), "rb", buffering=0) as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISBLK(info.st_mode) or f"{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}" != part["device"]:
            raise ValueError("inactive readback handle differs")
        remaining = size
        while remaining:
            raw = handle.read(min(remaining, 2 * 1024 * 1024))
            if not raw:
                raise ValueError("short inactive image readback")
            digest.update(raw)
            remaining -= len(raw)
    if digest.hexdigest() != image["sha256"]:
        raise ValueError("inactive image readback hash differs")


def _mounted(root, targets, rw):
    local, host = _mount_table(root, "proc/self/mountinfo"), _mount_table(root, "proc/1/mountinfo")
    devices = {row["part"]["device"] for row in targets}
    if any(row["device"] in devices for rows in host.values() for row in rows):
        raise ValueError("inactive filesystem escaped to PID1 namespace")
    for item in targets:
        point = "/" + item["path"].relative_to(root).as_posix()
        rows = local.get(point, [])
        if len(rows) != 1 or any(p.startswith(point + "/") for p in local):
            raise ValueError("inactive mount is missing, ambiguous or nested")
        row = rows[0]
        options, super_options = set(row["options"]), set(row["super_options"])
        mode, opposite = ("rw", "ro") if rw else ("ro", "rw")
        info = item["path"].stat()
        if (row["root"] != "/" or row["device"] != item["part"]["device"] or row["filesystem"] != item["fs"]
                or mode not in options or opposite in options or mode not in super_options or opposite in super_options
                or not {"nodev", "nosuid", "noexec"} <= options
                or f"{os.major(info.st_dev)}:{os.minor(info.st_dev)}" != item["part"]["device"]):
            raise ValueError("inactive mount identity or options differ")


def _mount(root, targets, active, rw, run):
    for item in targets:
        active.append(item)
        options = "rw,nodev,nosuid,noexec" if rw else "ro,nodev,nosuid,noexec" + (",noload" if item["fs"] == "ext4" else "")
        _call(run, ["/usr/bin/mount", "-t", item["fs"], "-o", options, "--",
                    str(root / item["part"]["path"].lstrip("/")), str(item["path"])])
    _mounted(root, targets, rw)


def _unmount(root, active, run):
    while active:
        item = active[-1]
        point = "/" + item["path"].relative_to(root).as_posix()
        rows = _mount_table(root, "proc/self/mountinfo").get(point, [])
        if rows:
            if len(rows) != 1 or rows[0]["device"] != item["part"]["device"]:
                raise ValueError("refusing to unmount an unknown filesystem")
            _call(run, ["/usr/bin/umount", "--", str(item["path"])])
            if _mount_table(root, "proc/self/mountinfo").get(point):
                raise ValueError("inactive unmount was not observed")
        active.pop()


def _files(targets):
    roots = {item["name"]: item["path"] for item in targets}
    values = {}
    for name in FILES:
        base = roots["boot" if name == "cmdline.txt" else "root"]
        path = _path(base, name)
        if path.stat().st_nlink != 1:
            raise ValueError("installed metadata is hard-linked")
        values[name] = _read(path, 32768, base.stat().st_uid).decode("utf-8")
    return values


def _fsck(root, targets, run):
    for item in targets:
        device = str(root / item["part"]["path"].lstrip("/"))
        argv = ["/usr/sbin/e2fsck", "-f", "-n", device] if item["fs"] == "ext4" else ["/usr/sbin/fsck.vfat", "-n", device]
        _call(run, argv)


def finalize(root: Path = Path("/"), *, run=_run) -> dict:
    if root != Path("/") and run is _run:
        raise ValueError("finalization requires the real root or an explicit test runner")
    _namespace(root)
    pending = _pending(root)
    if pending["phase"] != "INSTALLING" or report_path(root, pending).exists():
        raise ValueError("finalization is not a new installing transaction")
    media = _fresh(root, pending)
    parent = _path(root, str(Path(WORK).parent).replace("\\", "/"))
    if not parent.is_dir() or stat.S_IMODE(parent.stat().st_mode) != 0o700:
        raise ValueError("private RAUC mount prefix is missing")
    work = _path(root, WORK)
    work.mkdir(mode=0o700)
    identity = work.stat().st_dev, work.stat().st_ino
    targets, active = [], []
    complete = False
    try:
        for name, role, filesystem in (("root", "root_", "ext4"), ("boot", "boot_", "vfat")):
            path = work / name
            path.mkdir(mode=0o700)
            targets.append(dict(name=name, path=path, part=media["partitions"][role + pending["target_slot"]], fs=filesystem))
        _call(run, ["/usr/bin/mount", "--make-rprivate", "/"])
        geometry = {part["role"]: part for part in media["layout"]["partitions"]}
        for item, image in zip(targets, ("rootfs", "boot")):
            role = ("root_" if image == "rootfs" else "boot_") + pending["target_slot"]
            _device_hash(root, item["part"], pending["verified"]["images"][image], geometry[role]["size_lba"] * 512)
        _fsck(root, targets, run)
        _mount(root, targets, active, False, run)
        candidate = targets[0]["path"]
        factory = verify_factory(root, candidate, pending["verified"]["metadata"])
        signature_path = "opt/rosy/releases/" + factory["release_id"] + "/SHA256SUMS.sig"
        signature = _read(_path(candidate, signature_path), 512, candidate.stat().st_uid)
        source = _files(targets)
        source_layout = json.loads(source["etc/rosy/os-media.json"], object_pairs_hook=_pairs)
        rendered = rebase_files(source, source_layout, media["layout"], media["slot"])
        _unmount(root, active, run)
        if _fresh(root, pending) != media:
            raise ValueError("media changed before metadata writes")
        _mount(root, targets, active, True, run)
        if _files(targets) != source:
            raise ValueError("installed metadata changed before writes")
        for name, content in rendered.items():
            base = targets[1 if name == "cmdline.txt" else 0]["path"]
            _write_atomic(_path(base, name), content, 0o644)
        for item in targets:
            _call(run, ["/usr/bin/sync", "-f", str(item["path"])])
        _unmount(root, active, run)
        for item in targets:
            _call(run, ["/usr/sbin/blockdev", "--flushbufs", str(root / item["part"]["path"].lstrip("/"))])
        _fsck(root, targets, run)
        _mount(root, targets, active, False, run)
        if (_files(targets) != rendered or verify_factory(root, candidate, pending["verified"]["metadata"]) != factory
                or _read(_path(candidate, signature_path), 512, candidate.stat().st_uid) != signature):
            raise ValueError("installed metadata or signed factory readback differs")
        _unmount(root, active, run)
        _fresh(root, pending)
        complete = True
    finally:
        _unmount(root, active, run)
        if work.is_symlink() or (work.stat().st_dev, work.stat().st_ino) != identity or set(p.name for p in work.iterdir()) != {"root", "boot"}:
            raise ValueError("finalizer workspace changed; preserving it")
        for item in targets:
            _path(root, item["path"].relative_to(root).as_posix()).rmdir()
        work.rmdir()
    if not complete:
        raise ValueError("incomplete finalization")
    report = dict(_binding(pending), native_factory=factory,
                  metadata_sha256=hashlib.sha256(json.dumps(rendered, sort_keys=True).encode("utf-8")).hexdigest())
    _json_atomic(report_path(root, pending), report, 0o600)
    return read_report(root)


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        finalize()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"OS_INSTALL_HOLD: {exc}", file=sys.stderr)
        return 1
    return 0
