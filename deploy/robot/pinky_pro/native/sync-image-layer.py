#!/usr/bin/env python3
"""Bring a flashed robot's image layer up to the active release (D-388).

A payload release (D-225) replaces /opt/rosy/releases/<id> and moves
/opt/rosy/current. It does not touch what the image installed outside the
release: the scripts in /opt/rosy/native-runtime, the rosy units in
/etc/systemd/system, the udev rules and the modprobe options. This tool copies
the allowlisted files from the ACTIVE release's deploy/robot/native (which the
release signature covers) to where a fresh image puts them.

It ships inside the release, so a robot running an old image gets it with the
first payload release that carries it; rosy-release-push.ps1 runs it after
activation. Nothing image-resident needs to change for that.

    sudo -n python3 -B sync-image-layer.py --dry-run   # JSON plan, no writes
    sudo -n python3 -B sync-image-layer.py             # back up, install, reload

It never restarts a unit. ``restart_units`` names the active units whose unit
file or native-runtime script changed; the caller decides. Boot oneshots and
network/config units are reported as ``next_boot_units`` instead.

After a rollback it also undoes, within the allowlist, what an earlier sync
did to paths the current release no longer carries: files it added are
removed and files it replaced are restored, per the backup manifests. Files
no sync recorded (the image's own) are never removed. Reload/enable commands
that failed stay in pending.json and run again on the next call.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Callable

# Importing native_release/signing from inside a signed release must not leave
# bytecode there: it would be an unlisted file and fail the next verify().
sys.dont_write_bytecode = True
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


RELEASE_ID = re.compile(r"^[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]{3}$")
RELEASE_NATIVE = "deploy/robot/native"
IMAGE_LAYER = "image-layer"
NATIVE_RUNTIME = "opt/rosy/native-runtime"
UNIT_DIR = "etc/systemd/system"
UDEV_DIR = "etc/udev/rules.d"
MODPROBE_DIR = "etc/modprobe.d"
ALLOWED_PREFIXES = (NATIVE_RUNTIME + "/", UNIT_DIR + "/", UDEV_DIR + "/", MODPROBE_DIR + "/")
# Never written, whatever the allowlist says (config.txt, kernel and modules,
# the CORE Python runtime, device configuration, accounts and sudo).
FORBIDDEN_PREFIXES = (
    "boot/", "etc/rosy/", "usr/local/", "lib/modules/", "usr/lib/modules/",
    "etc/sudoers", "etc/passwd", "etc/shadow", "etc/group", "etc/gshadow",
)
BACKUP_ROOT = "var/lib/rosy/image-layer-backup"
BACKUP_MANIFEST = "backup-manifest.json"
# Written before the reload/enable commands, removed once they all succeed.
PENDING_FILE = BACKUP_ROOT + "/pending.json"
# After this many runs that could not finish them, pending commands are parked.
MAX_PENDING_ATTEMPTS = 3
LOCK_FILE = "var/lib/rosy/releases/native-release.lock"
DEFAULT_PUBLIC_KEY = "etc/rosy/trusted-release-keys/rosy-release-2026-01.pem"
# Only these nonrecursive directory rules may be applied outside the updater's
# old mount namespace. Never run the config's z/Z ownership migrations here.
STATE_DIRECTORIES = {
    "/var/lib/rosy/maps": ("2750", "rosy-io", "rosy-core"),
    "/var/lib/rosy/models": ("0750", "root", "rosy-camera"),
    "/var/lib/rosy/pilot-recordings": ("2750", "rosy-camera", "rosy-core"),
}
STATE_CONFIG = BACKUP_ROOT + "/state-directories.conf"

# The units build-native-payload.sh copies from deploy/robot/pinky_pro/native
# into the image's /etc/systemd/system. The first-boot units come from
# image/first-boot, which no release carries, so they stay image-only.
UNITS = (
    "rosy-release-recover.service",
    "rosy-sd-provision.service",
    "rosy-core.service",
    "rosy-host-agent.service",
    "rosy-runtime.target",
    "rosy-io.service",
    "rosy-camera.service",
    "rosy-camera-healthy.service", "rosy-camera-healthy.timer",
    "rosy-navigation.service",
    "rosy-boot-status.service", "rosy-boot-status.timer",
    "rosy-boot-status-ready.service",
    # D-433: retired (see RETIRED_UNITS); rosy-face replaces it.
    "rosy-boot-display.service",
    "rosy-face.service",
    "rosy-config.service",
    "rosy-network.service",
    "rosy-login-code.service",
    "rosy-hw-probe.service",
    "rosy-hw-probe.path",
    "rosy-hw-test.service",
    "rosy-hw-test.path",
    # D-412: the idle-time updater; only the timer is enabled.
    "rosy-auto-update.service",
    "rosy-auto-update.timer",
    # D-418: SSH access on CORE's request (expiry timer only while a temp login is on).
    "rosy-ssh-access.service", "rosy-ssh-pairing.service",
    "rosy-ssh-access.path",
    "rosy-ssh-access-boot.service",
    "rosy-ssh-password-expire.service",
    "rosy-ssh-password-expire.timer",
)
# Of those, the ones customize-rootfs.sh enables. A unit the sync adds is
# enabled only if it is here, as a fresh image would have it.
ENABLED_UNITS = frozenset({
    "rosy-host-agent.service",
    "rosy-release-recover.service",
    "rosy-runtime.target",
    "rosy-boot-status.service",
    "rosy-boot-status.timer",
    "rosy-boot-status-ready.service",
    "rosy-config.service",
    "rosy-network.service",
    "rosy-face.service",
    "rosy-login-code.service",
    "rosy-hw-probe.service",
    "rosy-hw-probe.path",
    "rosy-hw-test.path",
    "rosy-auto-update.timer",
    "rosy-ssh-access.path",
    "rosy-ssh-access-boot.service",
})

# D-433: a unit a newer one replaced. Its file is only ever REPLACED where an
# older image installed it (with a condition that keeps it from starting beside
# its successor), never installed new, and never restarted: restarting it would
# start a second owner of the same lines. A rollback's own sync restores the
# backed-up original.
RETIRED_UNITS = frozenset({"rosy-boot-display.service"})
# The sync only installs and enables a successor (rosy-face); it never stops the
# retired unit or starts the successor. On a robot updating from 026 this sync
# runs under 026's updater, whose rollback could not restart the retired unit,
# so the live swap is left to the D-433 updater (rosy_auto_update._face_swap)
# or the next boot.

# Never offered for a live restart, even when active and changed: the boot
# oneshots are Required by rosy-core (restarting them restarts CORE), and
# restarting network/config can drop the SSH session that runs the push.
# Their new definition takes effect at the next boot.
NEXT_BOOT_ONLY = frozenset({
    "rosy-release-recover.service",
    "rosy-sd-provision.service",
    "rosy-network.service",
    "rosy-config.service",
})


def _restartable(unit: str) -> bool:
    return (
        not unit.endswith(".target")
        and unit not in NEXT_BOOT_ONLY
        and unit not in RETIRED_UNITS
        and not unit.startswith("rosy-first-boot")
    )


Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


class SyncError(ValueError):
    pass


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, timeout=120, check=False)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _mode(path: Path) -> int:
    return path.stat().st_mode & 0o7777


def check_destination(relative: str) -> None:
    """Refuse any destination outside the four allowlisted image directories."""
    parts = relative.split("/")
    if (
        relative.startswith("/")
        or ".." in parts
        or "" in parts
        or not relative.startswith(ALLOWED_PREFIXES)
        or relative.startswith(FORBIDDEN_PREFIXES)
    ):
        raise SyncError(f"IMAGE_LAYER_DESTINATION: refusing to write {relative!r}")


def resolve_current(
    root: Path,
    *,
    is_link: Callable[[Path], bool] | None = None,
    readlink: Callable[[Path], str] | None = None,
) -> tuple[str, Path]:
    """The release /opt/rosy/current names, refusing anything outside releases/."""
    link = root / "opt" / "rosy" / "current"
    releases = root / "opt" / "rosy" / "releases"
    if not (is_link or os.path.islink)(link):
        raise SyncError(f"IMAGE_LAYER_CURRENT: {link} is not a symlink")
    target = Path(os.path.normpath(os.path.join(str(link.parent), (readlink or os.readlink)(link))))
    if not RELEASE_ID.fullmatch(target.name) or target.resolve().parent != releases.resolve():
        raise SyncError(f"IMAGE_LAYER_CURRENT: {link} does not point into {releases}")
    if target.is_symlink() or not target.is_dir():
        raise SyncError(f"IMAGE_LAYER_CURRENT: {target} is not a release directory")
    return target.name, target


def _entry(source: Path, destination: str, kind: str, mode: int) -> dict:
    check_destination(destination)
    return {"source": source, "destination": destination, "kind": kind, "mode": mode}


def allowlist(native: Path) -> tuple[list[dict], list[dict]]:
    """(entries, skipped) for a release's deploy/robot/native directory."""
    entries: list[dict] = []
    skipped: list[dict] = []
    for path in sorted(native.rglob("*"), key=lambda p: p.relative_to(native).as_posix()):
        relative = path.relative_to(native).as_posix()
        if "__pycache__" in relative.split("/"):
            continue
        if path.is_symlink():
            raise SyncError(f"IMAGE_LAYER_SOURCE: {relative} is a symlink")
        if path.is_dir():
            continue
        # install-native-runtime.sh copies the whole directory, so the
        # native-runtime copy mirrors every file the release carries here.
        mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
        entries.append(_entry(path, f"{NATIVE_RUNTIME}/{relative}", "runtime", mode))
    for unit in UNITS:
        source = native / unit
        if source.is_file() and not source.is_symlink():
            entries.append(_entry(source, f"{UNIT_DIR}/{unit}", "unit", 0o644))
        else:
            skipped.append({"path": f"/{UNIT_DIR}/{unit}", "reason": "not in this release"})
    for kind, folder, pattern, destination in (
        ("udev", "udev", "*.rules", UDEV_DIR),
        ("modprobe", "modprobe", "*.conf", MODPROBE_DIR),
    ):
        source_dir = native / IMAGE_LAYER / folder
        if not source_dir.is_dir():
            skipped.append({"path": f"/{destination}", "reason": f"release has no {IMAGE_LAYER}/{folder}"})
            continue
        for source in sorted(source_dir.glob(pattern)):
            if source.is_symlink() or not source.is_file():
                raise SyncError(f"IMAGE_LAYER_SOURCE: {source} is not a regular file")
            entries.append(_entry(source, f"{destination}/{source.name}", kind, 0o644))
    return entries, skipped


def _compare_modes() -> bool:
    # A Windows test host has no POSIX modes to compare; the robot does.
    return os.name == "posix"


def plan(root: Path, native: Path) -> dict:
    entries, skipped = allowlist(native)
    result = {"changed": [], "new": [], "unchanged": [], "skipped": skipped, "_work": []}
    for entry in entries:
        destination = root / entry["destination"]
        shown = "/" + entry["destination"]
        if destination.is_symlink():
            # A unit linked to /dev/null is masked; replacing it would unmask it.
            skipped.append({"path": shown, "reason": "destination is a symlink (masked?)"})
            continue
        if not destination.exists() and entry["kind"] == "unit" and Path(entry["destination"]).name in RETIRED_UNITS:
            skipped.append({"path": shown, "reason": "retired unit, not installed here (D-433)"})
            continue
        if not destination.exists():
            result["new"].append(shown)
            result["_work"].append({**entry, "state": "new"})
            continue
        if not destination.is_file():
            raise SyncError(f"IMAGE_LAYER_DESTINATION: {shown} is not a regular file")
        same = _sha256(destination) == _sha256(entry["source"])
        if same and (not _compare_modes() or _mode(destination) == entry["mode"]):
            result["unchanged"].append(shown)
            continue
        result["changed"].append(shown)
        result["_work"].append({**entry, "state": "changed"})
    return result


def affected_units(root: Path, work: list[dict]) -> list[str]:
    """Units whose file changed, or whose unit file runs a changed runtime script."""
    touched_units = {Path(item["destination"]).name for item in work if item["kind"] == "unit"}
    touched_scripts = {
        "/" + item["destination"] for item in work if item["kind"] == "runtime"
    }
    affected = set(touched_units)
    for unit in UNITS:
        installed = root / UNIT_DIR / unit
        if unit in affected or installed.is_symlink() or not installed.is_file():
            continue
        text = installed.read_text(encoding="utf-8", errors="replace")
        if any(re.search(re.escape(script) + r"(\s|$)", text) for script in touched_scripts):
            affected.add(unit)
    return sorted(affected)


def active_units(units: list[str], runner: Runner) -> list[str]:
    active = []
    for unit in units:
        completed = runner(["systemctl", "is-active", "--quiet", unit])
        if completed.returncode == 0:
            active.append(unit)
    return active


@contextlib.contextmanager
def _release_lock(root: Path):
    """Hold native_release.py's lock so current cannot move under the sync."""
    lock = root / LOCK_FILE
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a+b") as handle:
        if os.name == "posix":
            import fcntl

            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise SyncError("NATIVE_RELEASE_BUSY: another release operation is active") from exc
        try:
            yield
        finally:
            if os.name == "posix":
                fcntl.flock(handle, fcntl.LOCK_UN)


def _install(source: Path, destination: Path, mode: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.rosy-sync.tmp")
    temporary.unlink(missing_ok=True)
    with source.open("rb") as reader, temporary.open("wb") as writer:
        shutil.copyfileobj(reader, writer)
        writer.flush()
        os.fsync(writer.fileno())
    os.chmod(temporary, mode)
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        os.chown(temporary, 0, 0)
    os.replace(temporary, destination)


def _write_json(path: Path, payload: dict) -> None:
    """Write, fsync, rename, and fsync the folder: it survives a power loss."""
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    if os.name == "posix":
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _owe(root: Path, steps: dict) -> None:
    """Merge owed reload/enable/restart work into pending.json, durably.

    Called before a reconciled manifest is flagged, so a failure or a power
    loss after the flag still leaves the work for the next run.
    """
    path = root / PENDING_FILE
    pending: dict = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            pending = loaded if isinstance(loaded, dict) else {}
        except (OSError, ValueError):
            pending = {}
    merged = {
        **pending,
        "daemon_reload": bool(pending.get("daemon_reload")) or bool(steps.get("daemon_reload")),
        "udev_reload": bool(pending.get("udev_reload")) or bool(steps.get("udev_reload")),
        "enable": sorted(set(pending.get("enable", [])) | set(steps.get("enable", []))),
        "units": sorted(set(pending.get("units", [])) | set(steps.get("units", []))),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, merged)


def _check(runner: Runner, argv: list[str]) -> None:
    completed = runner(argv)
    if completed.returncode != 0:
        raise SyncError(f"IMAGE_LAYER_COMMAND: {' '.join(argv)} failed: {completed.stderr.strip()}")


def _unit_name(item: dict) -> str:
    return Path(item["destination"]).name


SERIAL = re.compile(r"^([0-9]{6})-")


def _run_folders(root: Path) -> list[Path]:
    """Backup folders in run order: by serial, never by the clock.

    The Pinky has no RTC, so a timestamp can go backwards between runs.
    Folders without a serial sort first.
    """
    backups = root / BACKUP_ROOT
    if not backups.is_dir():
        return []

    def key(path: Path) -> tuple[int, str]:
        match = SERIAL.match(path.name)
        return (int(match.group(1)) if match else -1, path.name)

    return sorted((path for path in backups.iterdir() if path.is_dir()), key=key)


def _next_serial(root: Path) -> int:
    """One more than the highest serial so far; the caller holds the lock."""
    serials = [int(match.group(1)) for match in
               (SERIAL.match(path.name) for path in _run_folders(root)) if match]
    serial = max(serials, default=-1) + 1
    if serial > 999999:
        raise SyncError("IMAGE_LAYER_BACKUP: backup serials are exhausted")
    return serial


def _records(root: Path) -> tuple[dict[str, list[tuple[dict, Path]]], list[str]]:
    """Every path's records, oldest first, from manifests whose files landed.

    A manifest is written with files_applied false before any file changes and
    set true once they all have. One that never got there (a disable that
    failed first, an install that failed and was undone) changed nothing, so
    its records must not shadow the real history. The second value lists the
    manifests that could not be read.
    """
    chains: dict[str, list[tuple[dict, Path]]] = {}
    corrupt: list[str] = []
    for folder in _run_folders(root):
        manifest = folder / BACKUP_MANIFEST
        if not manifest.is_file():
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            files = data["files"] if isinstance(data, dict) else None
            if not isinstance(files, list):
                raise ValueError("no file list")
        except (OSError, ValueError, KeyError):
            corrupt.append("/" + manifest.relative_to(root).as_posix())
            continue
        if data.get("files_applied") is not True:
            continue
        for record in files:
            if isinstance(record, dict) and isinstance(record.get("path"), str):
                chains.setdefault(record["path"], []).append((record, folder))
    return chains, corrupt


def _origin(chain: list[tuple[dict, Path]]) -> tuple[str, tuple[dict, Path] | None] | None:
    """What a path was before the syncs that still own it.

    Walk back from the newest record through consecutive "changed" records.
    Reaching "new" means a sync created the path: remove it. Reaching an
    earlier "restored"/"removed" or the start means the oldest "changed"
    backup holds the pre-sync file: restore it. A newest "restored"/"removed"
    means it was already undone.
    """
    if not chain or chain[-1][0].get("state") not in {"new", "changed"}:
        return None
    oldest_changed: tuple[dict, Path] | None = None
    for record, folder in reversed(chain):
        state = record.get("state")
        if state == "changed":
            oldest_changed = (record, folder)
            continue
        if state == "new":
            return ("remove", None)
        break
    return ("restore", oldest_changed)


def _landed(root: Path, record: dict) -> bool:
    """Whether the destination holds what this record's run meant to leave."""
    relative = str(record.get("path", "")).lstrip("/")
    check_destination(relative)
    destination = root / relative
    if record.get("state") == "removed":
        return not destination.exists() and not destination.is_symlink()
    return (destination.is_file() and not destination.is_symlink()
            and _sha256(destination) == record.get("sha256"))


def reconcile(root: Path, *, dry_run: bool) -> tuple[list[dict], dict, list[str]]:
    """Settle manifests that are neither files_applied nor abandoned.

    Such a manifest means a run stopped between its first file change and
    its files_applied flag: a power loss. If every destination holds what the
    run recorded, the run did land: flag it, and hand back the reloads and
    enables it never ran. Otherwise undo exactly what it installed from its
    backups and mark it abandoned. Nothing else is touched.

    The owed work goes to pending.json before the manifest is flagged. Folders
    without a serial predate this rule (their undone runs were never marked
    abandoned), so they are only reported, as legacy_ignored.
    """
    report: list[dict] = []
    legacy: list[str] = []
    steps = {"daemon_reload": False, "enable": [], "udev_reload": False, "units": []}
    for folder in _run_folders(root):
        path = folder / BACKUP_MANIFEST
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            files = data["files"]
            if not isinstance(files, list):
                raise ValueError("no file list")
        except (OSError, ValueError, KeyError, TypeError):
            continue  # _records reports it as corrupt
        if data.get("files_applied") is True or data.get("abandoned") is True:
            continue
        shown = "/" + path.relative_to(root).as_posix()
        if not SERIAL.match(folder.name):
            legacy.append(shown)
            continue
        records = [record for record in files if isinstance(record, dict)]
        if dry_run:
            report.append({"manifest": shown, "outcome": "unreconciled"})
            continue
        kinds = {_kind(str(record.get("path", "")).lstrip("/")) for record in records}
        if all(_landed(root, record) for record in records):
            owed = {"daemon_reload": "unit" in kinds, "udev_reload": "udev" in kinds,
                    "enable": [], "units": []}
            for record in records:
                name = Path(str(record["path"])).name
                if _kind(str(record["path"]).lstrip("/")) == "unit":
                    owed["units"].append(name)
                    if record.get("state") == "new" and name in ENABLED_UNITS:
                        owed["enable"].append(name)
            _owe(root, owed)
            data["files_applied"] = True
            _write_json(path, data)
            for key in ("daemon_reload", "udev_reload"):
                steps[key] = steps[key] or owed[key]
            steps["enable"] += owed["enable"]
            steps["units"] += owed["units"]
            report.append({"manifest": shown, "outcome": "applied"})
            continue
        undone: list[str] = []
        for record in reversed(records):
            relative = str(record.get("path", "")).lstrip("/")
            destination = root / relative
            saved = folder / str(record.get("backup") or "")
            has_backup = bool(record.get("backup")) and saved.is_file() and not saved.is_symlink()
            state = record.get("state")
            if state == "new" and _landed(root, record):
                destination.unlink()
            elif state in {"changed", "restored"} and _landed(root, record) and has_backup:
                _install(saved, destination, _mode(saved))
            elif state == "removed" and _landed(root, record) and has_backup:
                _install(saved, destination, _mode(saved))
            else:
                continue
            undone.append("/" + relative)
            if _kind(relative) == "unit":
                steps["daemon_reload"] = True
            if _kind(relative) == "udev":
                steps["udev_reload"] = True
        if steps["daemon_reload"] or steps["udev_reload"]:
            _owe(root, {"daemon_reload": steps["daemon_reload"], "udev_reload": steps["udev_reload"]})
        data["abandoned"] = True
        _write_json(path, data)
        report.append({"manifest": shown, "outcome": "undone", "paths": undone})
    return report, steps, legacy


def _kind(relative: str) -> str:
    if relative.startswith(UNIT_DIR + "/"):
        return "unit"
    if relative.startswith(UDEV_DIR + "/"):
        return "udev"
    if relative.startswith(MODPROBE_DIR + "/"):
        return "modprobe"
    return "runtime"


def plan_cleanup(root: Path, native: Path, skipped: list[dict],
                 chains: dict[str, list[tuple[dict, Path]]]) -> list[dict]:
    """Undo what earlier syncs did to paths the current release no longer carries.

    Only paths the applied backup manifests record, only while the file still
    holds what the last sync installed, and only inside the allowlisted
    directories. Anything else stays.
    """
    carried = {"/" + entry["destination"] for entry in allowlist(native)[0]}
    cleanup: list[dict] = []
    for shown, chain in sorted(chains.items()):
        if shown in carried:
            continue
        decision = _origin(chain)
        if decision is None:
            continue
        relative = shown.lstrip("/")
        check_destination(relative)
        destination = root / relative
        if destination.is_symlink() or not destination.is_file():
            continue
        if _sha256(destination) != chain[-1][0].get("sha256"):
            skipped.append({"path": shown, "reason": "changed since the sync that installed it"})
            continue
        item = {"destination": relative, "kind": _kind(relative)}
        action, origin = decision
        if action == "remove":
            cleanup.append({**item, "state": "removed"})
            continue
        record, folder = origin
        saved = folder / str(record.get("backup") or "")
        if not record.get("backup") or saved.is_symlink() or not saved.is_file():
            skipped.append({"path": shown, "reason": "its backup is missing"})
            continue
        cleanup.append({**item, "state": "restored", "source": saved, "mode": _mode(saved)})
    return cleanup


def _stamp(now: Callable[[], _dt.datetime] | None = None) -> str:
    return (now or (lambda: _dt.datetime.now(_dt.timezone.utc)))().strftime("%Y%m%dT%H%M%SZ")


def _set_aside(path: Path, label: str) -> str:
    """Rename pending.json out of the way, keeping it for a person to read."""
    target = path.with_name(f"pending.{label}-{_stamp()}.json")
    os.replace(path, target)
    return str(target)


def _load_pending(root: Path, *, dry_run: bool) -> tuple[dict, dict]:
    """(pending, report). A corrupt or exhausted pending.json is set aside."""
    path = root / PENDING_FILE
    shown = "/" + PENDING_FILE
    if not path.is_file():
        return {}, {}
    try:
        pending = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(pending, dict):
            raise ValueError("not an object")
    except (OSError, ValueError):
        if dry_run:
            return {}, {"pending_quarantined": f"{shown} is corrupt (the apply sets it aside)"}
        return {}, {"pending_quarantined": _set_aside(path, "corrupt")}
    if int(pending.get("attempts", 0) or 0) >= MAX_PENDING_ATTEMPTS:
        if dry_run:
            return {}, {"pending_parked": f"{shown} failed {pending.get('attempts')} times (the apply parks it)"}
        return {}, {"pending_parked": _set_aside(path, "parked")}
    return pending, {}


def _post_commands(steps: dict) -> list[list[str]]:
    """daemon-reload, then enables, then the udev reload; in that order."""
    commands: list[list[str]] = []
    if steps.get("state_config"):
        # PID 1 creates this root oneshot outside the old updater's read-only
        # namespace. The generated config contains only validated d rules.
        commands.append([
            "systemd-run", "--quiet", "--wait", "--pipe", "--collect",
            "--property=Type=exec", "--property=User=root", "--property=Group=root",
            "--property=ProtectSystem=strict", "--property=ProtectHome=true",
            "--property=PrivateTmp=true", "--property=PrivateDevices=true",
            "--property=NoNewPrivileges=true", "--property=RestrictNamespaces=true",
            "--property=RestrictAddressFamilies=AF_UNIX", "--property=RuntimeMaxSec=60",
            "--property=CapabilityBoundingSet=CAP_CHOWN CAP_FOWNER CAP_FSETID CAP_DAC_OVERRIDE",
            "--property=ReadWritePaths=/var/lib/rosy", "--property=TimeoutStartSec=60",
            "/usr/bin/systemd-tmpfiles", "--create", steps["state_config"],
        ])
    if steps.get("daemon_reload"):
        commands.append(["systemctl", "daemon-reload"])
    for unit in sorted(set(steps.get("enable", []))):
        if unit not in ENABLED_UNITS:
            continue
        # A new .path or .timer would otherwise sit idle until the next boot.
        if unit.endswith((".path", ".timer")):
            commands.append(["systemctl", "enable", "--now", unit])
        else:
            commands.append(["systemctl", "enable", unit])
    if steps.get("udev_reload"):
        commands.append(["udevadm", "control", "--reload"])
    return commands


def state_directory_rules(root: Path, native: Path) -> list[str]:
    """Missing/drifted image directories, from a bounded signed tmpfiles subset.

    Preserve existing files and recordings on rollback. These additive state
    directories are deliberately outside file-backup cleanup ownership.
    """
    source = native / "tmpfiles-rosy-state.conf"
    if not source.exists():
        return []  # Older releases carry no such rules.
    if source.is_symlink() or not source.is_file():
        raise SyncError("IMAGE_LAYER_STATE_RULE: tmpfiles config is not a regular file")
    rules = []
    seen = set()
    for line in source.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if not fields or fields[0].startswith("#") or len(fields) < 2:
            continue
        path = fields[1]
        if path not in STATE_DIRECTORIES or fields[0] != "d":
            continue
        expected = ["d", path, *STATE_DIRECTORIES[path], "-"]
        if fields != expected or path in seen:
            raise SyncError(f"IMAGE_LAYER_STATE_RULE: unapproved rule for {path}")
        seen.add(path)
        destination = root / path.lstrip("/")
        current = destination
        while current != root:
            if current.is_symlink():
                raise SyncError(f"IMAGE_LAYER_STATE_RULE: symlink at {current}")
            current = current.parent
        if destination.exists() and not destination.is_dir():
            raise SyncError(f"IMAGE_LAYER_STATE_RULE: {path} is not a directory")
        needs = not destination.exists()
        if destination.exists() and _compare_modes():
            needs = _mode(destination) != int(expected[2], 8)
            if root == Path("/"):
                import grp
                import pwd

                info = destination.stat()
                needs = needs or info.st_uid != pwd.getpwnam(expected[3]).pw_uid
                needs = needs or info.st_gid != grp.getgrnam(expected[4]).gr_gid
        if needs:
            rules.append(" ".join(expected))
    return rules


def _steps(root: Path, work: list[dict], cleanup: list[dict], pending: dict) -> dict:
    kinds = {item["kind"] for item in work + cleanup}
    added = {
        _unit_name(item) for item in work
        if item["kind"] == "unit" and item["state"] == "new" and _unit_name(item) in ENABLED_UNITS
    }
    removing = {_unit_name(item) for item in cleanup if item["kind"] == "unit" and item["state"] == "removed"}
    # A pending enable for a unit that is gone, or that this run removes, can
    # never succeed; retrying it would fail every later push.
    still_there = {
        unit for unit in pending.get("enable", [])
        if unit not in removing
        and (root / UNIT_DIR / unit).is_file() and not (root / UNIT_DIR / unit).is_symlink()
    }
    return {
        "daemon_reload": "unit" in kinds or bool(pending.get("daemon_reload")),
        "enable": sorted(added | still_there),
        "udev_reload": "udev" in kinds or bool(pending.get("udev_reload")),
    }


def _unit_state(runner: Runner, unit: str) -> dict:
    return {
        "enabled": runner(["systemctl", "is-enabled", "--quiet", unit]).returncode == 0,
        "active": runner(["systemctl", "is-active", "--quiet", unit]).returncode == 0,
    }


def apply(root: Path, release_id: str, work: list[dict], runner: Runner,
          *, cleanup: list[dict] | None = None, units: list[str] | None = None,
          pending: dict | None = None,
          state_rules: list[str] | None = None,
          now: Callable[[], _dt.datetime] | None = None) -> dict:
    """Back up, clean up, install, reload. Undo every change if one fails.

    The reload/enable commands run after the files are in place. Until all of
    them succeed, pending.json names them and the units they affect, so the
    next run finishes the job even when every file is already unchanged.
    """
    cleanup = cleanup or []
    pending = pending or {}
    steps = _steps(root, work, cleanup, pending)
    if state_rules:
        config = root / STATE_CONFIG
        current = config
        while current != root:
            if current.is_symlink():
                raise SyncError(f"IMAGE_LAYER_STATE_RULE: symlink at {current}")
            current = current.parent
        config.parent.mkdir(parents=True, exist_ok=True)
        temporary = config.with_name(config.name + ".tmp")
        if temporary.is_symlink():
            raise SyncError(f"IMAGE_LAYER_STATE_RULE: symlink at {temporary}")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(state_rules) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            os.chown(temporary, 0, 0)
        os.replace(temporary, config)
        steps["state_config"] = str(config)
    backup_dir = None
    manifest: dict | None = None
    backup: Path | None = None
    if work or cleanup:
        stamp = _stamp(now)
        # The serial orders runs; the timestamp is only for people (no RTC).
        (root / BACKUP_ROOT).mkdir(parents=True, exist_ok=True)
        backup = root / BACKUP_ROOT / f"{_next_serial(root):06d}-{stamp}-{release_id}"
        backup.mkdir()
        os.chmod(backup, 0o700)
        backup_dir = "/" + backup.relative_to(root).as_posix()
        records = []
        for item in work + cleanup:
            destination = root / item["destination"]
            record = {
                "path": "/" + item["destination"],
                "state": item["state"],
                "mode": oct(item["mode"]) if "mode" in item else None,
                "sha256": _sha256(item["source"]) if "source" in item else None,
                "backup": None,
                "previous_sha256": None,
            }
            if item["state"] != "new":
                saved = backup / item["destination"]
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, saved)
                record["backup"] = item["destination"]
                record["previous_sha256"] = _sha256(saved)
            records.append(record)
        manifest = {"release_id": release_id, "created": stamp, "files_applied": False,
                    "complete": False, "files": records}
        _write_json(backup / BACKUP_MANIFEST, manifest)

        disabled: list[tuple[str, dict]] = []
        done: list[dict] = []
        try:
            # A unit the sync removes is disabled and stopped while its file,
            # with its [Install] section, still exists.
            for item in cleanup:
                if item["kind"] == "unit" and item["state"] == "removed":
                    unit = _unit_name(item)
                    before = _unit_state(runner, unit)
                    _check(runner, ["systemctl", "disable", "--now", unit])
                    disabled.append((unit, before))
            for item in work + cleanup:
                destination = root / item["destination"]
                if item["state"] == "removed":
                    destination.unlink()
                else:
                    _install(item["source"], destination, item["mode"])
                done.append(item)
        except BaseException:
            for item in reversed(done):
                destination = root / item["destination"]
                if item["state"] == "new":
                    destination.unlink(missing_ok=True)
                else:
                    saved = backup / item["destination"]
                    _install(saved, destination, _mode(saved))
            manifest["abandoned"] = True
            _write_json(backup / BACKUP_MANIFEST, manifest)
            # Best effort: the original failure is what the caller must see.
            for unit, before in reversed(disabled):
                if before["enabled"]:
                    runner(["systemctl", "enable", unit])
                if before["active"]:
                    runner(["systemctl", "start", unit])
            raise
        manifest["files_applied"] = True
        _write_json(backup / BACKUP_MANIFEST, manifest)

    commands = _post_commands(steps)
    if not commands and not pending:
        return {"backup_dir": backup_dir, "commands": [], "enabled": []}
    _write_json(root / PENDING_FILE, {
        **steps,
        "units": sorted(set(units or []) | set(pending.get("units", []))),
        "backup_dir": backup_dir,
        "release_id": release_id,
        "attempts": int(pending.get("attempts", 0) or 0) + 1,
    })
    for argv in commands:
        _check(runner, argv)
        if argv[0] == "systemd-run":
            # A successful process must actually have established the service
            # prerequisites before the caller can restart any runtime unit.
            for rule in state_rules or []:
                _, path, mode, user, group, _ = rule.split()
                directory = root / path.lstrip("/")
                if directory.is_symlink() or not directory.is_dir():
                    raise SyncError(f"IMAGE_LAYER_STATE_DIRECTORY: {path} was not created")
                if _compare_modes() and _mode(directory) != int(mode, 8):
                    raise SyncError(f"IMAGE_LAYER_STATE_DIRECTORY: {path} has incorrect mode")
                if root == Path("/"):
                    import grp
                    import pwd

                    info = directory.stat()
                    if info.st_uid != pwd.getpwnam(user).pw_uid or info.st_gid != grp.getgrnam(group).gr_gid:
                        raise SyncError(f"IMAGE_LAYER_STATE_DIRECTORY: {path} has incorrect ownership")
    (root / PENDING_FILE).unlink()
    if manifest is not None and backup is not None:
        manifest.update(complete=True, commands=[" ".join(argv) for argv in commands])
        _write_json(backup / BACKUP_MANIFEST, manifest)
    return {"backup_dir": backup_dir, "commands": [" ".join(argv) for argv in commands],
            "enabled": [argv[-1] for argv in commands if argv[1] == "enable"]}


def sync(
    root: Path,
    *,
    dry_run: bool,
    verify: Callable[[str], object],
    runner: Runner = _run,
    is_link: Callable[[Path], bool] | None = None,
    readlink: Callable[[Path], str] | None = None,
) -> dict:
    root = Path(root)
    with _release_lock(root):
        release_id, release = resolve_current(root, is_link=is_link, readlink=readlink)
        verify(release_id)
        native = release / RELEASE_NATIVE
        if not native.is_dir():
            raise SyncError(f"IMAGE_LAYER_SOURCE: release {release_id} has no {RELEASE_NATIVE}")
        state_rules = state_directory_rules(root, native)
        pending, pending_report = _load_pending(root, dry_run=dry_run)
        reconciled, owed, legacy_ignored = reconcile(root, dry_run=dry_run)
        if owed["daemon_reload"] or owed["udev_reload"] or owed["enable"]:
            pending = {
                **pending,
                "daemon_reload": bool(pending.get("daemon_reload")) or owed["daemon_reload"],
                "udev_reload": bool(pending.get("udev_reload")) or owed["udev_reload"],
                "enable": sorted(set(pending.get("enable", [])) | set(owed["enable"])),
                "units": sorted(set(pending.get("units", [])) | set(owed["units"])),
            }
        result = plan(root, native)
        work = result.pop("_work")
        chains, corrupt = _records(root)
        cleanup = plan_cleanup(root, native, result["skipped"], chains)
        restored_units = {
            _unit_name(item) for item in cleanup if item["kind"] == "unit" and item["state"] == "restored"
        }
        units = sorted(set(affected_units(root, work)) | restored_units | set(pending.get("units", [])))
        active = active_units(units, runner)
        result.update(
            ok=True,
            dry_run=dry_run,
            release_id=release_id,
            state_directories=[rule.split()[1] for rule in state_rules],
            removed=["/" + item["destination"] for item in cleanup if item["state"] == "removed"],
            restored=["/" + item["destination"] for item in cleanup if item["state"] == "restored"],
            pending=pending or None,
            reconciled=reconciled,
            legacy_ignored=legacy_ignored,
            pending_quarantined=pending_report.get("pending_quarantined"),
            pending_parked=pending_report.get("pending_parked"),
            corrupt_manifests=corrupt,
            units_affected=units,
            restart_units=[unit for unit in active if _restartable(unit)],
            active_targets_affected=[unit for unit in active if unit.endswith(".target")],
            next_boot_units=[unit for unit in active
                             if not _restartable(unit) and not unit.endswith(".target")],
            modprobe_changed=[
                "/" + item["destination"] for item in work + cleanup if item["kind"] == "modprobe"
            ],
        )
        if dry_run:
            steps = _steps(root, work, cleanup, pending)
            if state_rules:
                steps["state_config"] = str(root / STATE_CONFIG)
            result.update(backup_dir=None, enabled=[], commands=[
                " ".join(argv) for argv in _post_commands(steps)])
        else:
            result.update(apply(root, release_id, work, runner, cleanup=cleanup,
                                units=units, pending=pending, state_rules=state_rules))
        return result


def _verifier(root: Path, public_key: Path) -> Callable[[str], object]:
    from native_release import NativeReleaseManager

    manager = NativeReleaseManager(root=root, public_key=public_key)
    return manager.verify


def main(
    argv: list[str] | None = None,
    *,
    runner: Runner = _run,
    is_link: Callable[[Path], bool] | None = None,
    readlink: Callable[[Path], str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=Path("/"))
    parser.add_argument("--public-key", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    public_key = args.public_key or args.root / DEFAULT_PUBLIC_KEY
    try:
        result = sync(args.root, dry_run=args.dry_run,
                      verify=_verifier(args.root, public_key), runner=runner,
                      is_link=is_link, readlink=readlink)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        result = {"ok": False, "error": str(exc)}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
