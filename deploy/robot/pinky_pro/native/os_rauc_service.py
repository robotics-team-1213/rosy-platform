"""Transaction-scoped RAUC manager; caller owns policy, no-motion controls and long OS/native run locks."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import sys
import time

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from os_bootloader import _binding, _claim, boot_facts
from os_media import capture
from os_rauc import RAUC
from os_rauc_runtime import prepare
from os_state_io import _write_atomic
from os_state_layout import COMMON, _object, _path, _read
from os_storage_dispatch import OS_UPDATE_ASSETS
from os_update_state import layout_digest, read_state

SERVICE = "rosy-os-rauc.service"
RUNTIME = "run/rosy-os-update/rauc"
DROPIN = "run/systemd/system/" + SERVICE + ".d/50-rosy-transaction.conf"
ASSETS = OS_UPDATE_ASSETS
REQUEST_FIELDS = {"schema_version", "transaction_id", "source_boot_id", "target_slot", "manifest_sha256",
                  "layout_sha256", "expires_monotonic_ns"}


def _run(argv, timeout=60):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                          env=dict(os.environ, LC_ALL="C"))


def _call(run, argv, timeout=60):
    result = run(argv, timeout=timeout)
    if result.returncode or len(result.stdout) > 65536 or len(result.stderr) > 16384:
        raise ValueError("RAUC manager command failed")
    return result.stdout


def _value(run, name):
    return _call(run, ["systemctl", "show", "--value", "-p", name, SERVICE]).strip()


def _file(root, relative, mode, limit=32768):
    path = _path(root, relative)
    info = path.stat()
    if info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != mode:
        raise ValueError("RAUC manager input mode or link count differs")
    return _read(path, limit, root.stat().st_uid)


def _assets(root):
    for source, target in ASSETS:
        expected = _file(root, "opt/rosy/os-bootstrap/native-runtime/" + source, 0o644)
        if _file(root, target, 0o644) != expected:
            raise ValueError("live RAUC asset differs from its frozen owner")


def _admit(root, bundle, raw, signature):
    state, facts = read_state(root), boot_facts(root)
    pending = state["pending"]
    if (pending is None or pending["phase"] != "INSTALLING" or facts["tryboot"]
            or facts["slot"] != pending["source_slot"] or facts["boot_id"] != pending["source_boot_id"]):
        raise ValueError("RAUC install requires the same INSTALLING source boot")
    prepared = prepare(root, bundle, raw, signature)
    if (prepared["verified"] != pending["verified"] or prepared["target_slot"] != pending["target_slot"]
            or layout_digest(prepared["media"]["layout"]) != pending["layout_sha256"]):
        raise ValueError("RAUC inputs differ from the pending transaction")
    _assets(root)
    return pending, prepared


def _effective(run, prepared):
    if (_value(run, "FragmentPath") != "/etc/systemd/system/" + SERVICE
            or shlex.split(_value(run, "DropInPaths")) != ["/" + DROPIN]
            or _value(run, "ProtectSystem") != "strict" or _value(run, "DevicePolicy") != "closed"):
        raise ValueError("effective RAUC unit or isolation differs")
    words = shlex.split(_value(run, "DeviceAllow"))
    actual = list(zip(words[::2], words[1::2]))
    expected = [tuple(line.removeprefix("DeviceAllow=").split()) for line in prepared["device_dropin"].splitlines()
                if line.startswith("DeviceAllow=") and line != "DeviceAllow="]
    if len(words) % 2 or len(actual) != len(expected) or set(actual) != set(expected):
        raise ValueError("effective RAUC device grants differ")
    if set(shlex.split(_value(run, "ReadWritePaths"))) != {"/" + RUNTIME, "/" + COMMON + "/os-update/rauc"}:
        raise ValueError("effective RAUC writable paths differ")


def _empty_cgroup(root, group):
    if not group:
        return
    if (not group.startswith("/") or Path(group).name != SERVICE
            or any(part in {"..", "."} for part in group.split("/")) or len(group) > 1024):
        raise ValueError("RAUC cgroup identity differs")
    _read(_path(root, "sys/fs/cgroup/cgroup.controllers"), 4096, root.stat().st_uid)
    path = _path(root, "sys/fs/cgroup" + group + "/cgroup.events")
    try:
        raw = _read(path, 4096, root.stat().st_uid).decode("ascii")
    except FileNotFoundError:
        if not path.parent.exists():
            return
        raise ValueError("RAUC cgroup completion is unknown")
    fields = dict(line.split() for line in raw.splitlines())
    if fields.get("populated") != "0":
        raise ValueError("RAUC cgroup still has live processes")


def _stop(root, run):
    groups = {_value(run, "ControlGroup"), "/system.slice/" + SERVICE}
    _call(run, ["systemctl", "stop", SERVICE])
    if _value(run, "MainPID") != "0" or _value(run, "ActiveState") not in ("inactive", "failed"):
        raise ValueError("RAUC daemon is not confirmed stopped")
    groups.add(_value(run, "ControlGroup"))
    for group in groups:
        _empty_cgroup(root, group)


def _request(root):
    raw = _file(root, RUNTIME + "/request.json", 0o600, 8192)
    return _object(raw, REQUEST_FIELDS)


def _existing(root):
    request = _request(root)
    state = read_state(root)
    if state["pending"] is None:
        raise ValueError("RAUC runtime has no pending owner")
    metadata = state["pending"]["verified"]["metadata"]
    bundle = _path(root, COMMON + "/os-update/staging/" + metadata["release_id"] + "/" + metadata["bundle"]["filename"])
    raw = _file(root, RUNTIME + "/os-update.json", 0o600, 16384)
    signature = _file(root, RUNTIME + "/os-update.json.sig", 0o600, 512).decode("ascii").strip()
    pending, prepared = _admit(root, bundle, raw, signature)
    if any(request[k] != v for k, v in _binding(pending).items()):
        raise ValueError("RAUC runtime request has a different owner")
    expected = _contents(prepared, raw, signature, request)
    for relative, (data, mode) in expected.items():
        if _file(root, relative, mode) != data:
            raise ValueError("RAUC runtime configuration differs")
    return request, pending, prepared, expected


def check(root=Path("/"), *, run=_run):
    """ExecStartPre and controller both reverify actual inputs and manager grants before install."""
    try:
        root = Path(root).absolute()
        request, pending, prepared, _ = _existing(root)
        _claim(root, pending)
        now, expiry = time.monotonic_ns(), request["expires_monotonic_ns"]
        if type(expiry) is not int or not now < expiry <= now + 900_000_000_000:
            raise ValueError("RAUC request expired")
        _effective(run, prepared)
        return prepared
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
        raise ValueError(f"OS_RAUC_SERVICE_HOLD: {exc}") from exc


def _contents(prepared, raw, signature, request):
    return {
        RUNTIME + "/system.conf": (prepared["configuration"].encode(), 0o600),
        RUNTIME + "/os-update.json": (raw, 0o600),
        RUNTIME + "/os-update.json.sig": ((signature + "\n").encode("ascii"), 0o600),
        RUNTIME + "/request.json": ((json.dumps(request, sort_keys=True) + "\n").encode(), 0o600),
        DROPIN: (prepared["device_dropin"].encode(), 0o644),
    }


def _parent(root, relative, mode):
    path = _path(root, relative)
    path.mkdir(parents=True, exist_ok=True, mode=mode)
    _path(root, relative)
    if stat.S_IMODE(path.stat().st_mode) != mode:
        raise ValueError("RAUC runtime parent is not private or has unexpected permissions")


def _cleanup(root, files, directories):
    # Validate everything before removing anything. Unknown files and mounts remain for recovery.
    for path, identity in directories.items():
        info = path.stat()
        if (info.st_dev, info.st_ino) != identity or path.is_symlink() or os.path.ismount(path):
            raise ValueError("RAUC runtime directory changed")
        expected = {root / name for name in files if (root / name).parent == path}
        expected.update(child for child in directories if child.parent == path)
        if set(path.iterdir()) - expected:
            raise ValueError("unknown RAUC runtime files remain")
    for relative, (data, mode) in files.items():
        path = _path(root, relative)
        if path.exists() and _file(root, relative, mode) != data:
            raise ValueError("RAUC runtime file changed before cleanup")
    for relative in files:
        _path(root, relative).unlink(missing_ok=True)
    for path in sorted(directories, key=lambda p: len(p.parts), reverse=True):
        path.rmdir()


def install(root, bundle, raw, signature, *, authorize, run=_run):
    """Controller holds OS transaction/claim/native-run locks and maintenance before calling."""
    root = Path(root).absolute()
    files, directories = {}, {}
    try:
        if run is _run and root != Path("/"):
            raise ValueError("live service management requires the real root")
        pending, prepared = _admit(root, bundle, raw, signature)
        from os_update_install import report_path, read_report
        if report_path(root, pending).exists():
            raise ValueError("an installed receipt already exists; recover instead of replaying install")
        _claim(root, pending)
        _stop(root, run)
        runtime, dropdir = _path(root, RUNTIME), _path(root, DROPIN).parent
        if runtime.exists() or dropdir.exists():
            raise ValueError("recover the existing RAUC runtime before starting a new one")
        try:
            _parent(root, "run/rosy-os-update", 0o700)
            _parent(root, "run/systemd/system", 0o755)
            for path, mode in ((runtime, 0o700), (runtime / "mount", 0o700), (dropdir, 0o755)):
                path.mkdir(mode=mode)
                info = path.stat()
                directories[path] = (info.st_dev, info.st_ino)
            request = dict(_binding(pending), expires_monotonic_ns=time.monotonic_ns() + 900_000_000_000)
            for relative, entry in _contents(prepared, raw, signature, request).items():
                files[relative] = entry  # A failed parent fsync can follow a successful publication.
                data, mode = entry
                _write_atomic(_path(root, relative), data, mode)
            _call(run, ["systemctl", "daemon-reload"])
            _call(run, ["systemctl", "start", SERVICE], timeout=660)
            _effective(run, prepared)
            if _value(run, "ActiveState") != "active" or not _value(run, "MainPID").isdigit() or int(_value(run, "MainPID")) <= 0:
                raise ValueError("RAUC daemon is not active")
            # Full bundle verification may take minutes on SD; policy must be sampled afterward.
            authorize()
            _claim(root, pending)
            if read_state(root)["pending"] != pending or layout_digest(capture(root)["layout"]) != pending["layout_sha256"]:
                raise ValueError("RAUC transaction or media changed before install")
            _call(run, [RAUC, "--conf", str(runtime / "system.conf"), "install", str(bundle)], timeout=2700)
            report = read_report(root)
            return dict(installed=True, manifest_sha256=prepared["verified"]["manifest_sha256"], report=report)
        finally:
            _stop(root, run)
            _cleanup(root, files, directories)
            _call(run, ["systemctl", "daemon-reload"])
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
        raise ValueError(f"OS_RAUC_SERVICE_HOLD: {exc}") from exc


def recover(root=Path("/"), *, run=_run):
    """Revoke a stopped same-boot transaction's verified runtime even after its claim expires."""
    try:
        root = Path(root).absolute()
        if run is _run and root != Path("/"):
            raise ValueError("live service management requires the real root")
        _stop(root, run)
        _, _, _, files = _existing(root)
        paths = [_path(root, RUNTIME), _path(root, RUNTIME + "/mount"), _path(root, DROPIN).parent]
        directories = {p: (p.stat().st_dev, p.stat().st_ino) for p in paths}
        _cleanup(root, files, directories)
        _call(run, ["systemctl", "daemon-reload"])
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
        raise ValueError(f"OS_RAUC_SERVICE_HOLD: {exc}") from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/"))
    parser.add_argument("command", choices=("check",))
    args = parser.parse_args(argv)
    try:
        check(args.root)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
