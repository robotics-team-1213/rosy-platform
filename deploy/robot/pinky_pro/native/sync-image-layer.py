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
import json
import os
from pathlib import Path
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

from image_layer_files import _install, _mode, _sha256, _write_json
import image_layer_boot as boot
from image_layer_plan import (  # noqa: F401  (names stay reachable on this entry module)
    ALLOWED_PREFIXES, BACKUP_MANIFEST, BACKUP_ROOT, DEFAULT_PUBLIC_KEY, ENABLED_UNITS, FORBIDDEN_PREFIXES,
    IMAGE_LAYER, LOCK_FILE, MAX_PENDING_ATTEMPTS, MODPROBE_DIR, NATIVE_RUNTIME, NEXT_BOOT_ONLY, PENDING_FILE,
    RELEASE_ID, RELEASE_NATIVE, RETIRED_UNITS, Runner, STATE_CONFIG, STATE_DIRECTORIES, SyncError, UDEV_DIR,
    UNITS, UNIT_DIR, _compare_modes, _entry, _restartable, _run, active_units, affected_units, allowlist,
    check_destination, plan, resolve_current,
)
from image_layer_records import (  # noqa: F401
    SERIAL, _kind, _landed, _next_serial, _origin, _post_commands, _records, _run_folders, _steps, _unit_name,
    _unit_state, plan_cleanup, state_directory_rules,
)


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


def apply(root: Path, release_id: str, work: list[dict], runner: Runner,
          *, cleanup: list[dict] | None = None, units: list[str] | None = None,
          pending: dict | None = None,
          state_rules: list[str] | None = None,
          now: Callable[[], _dt.datetime] | None = None) -> dict:
    """Back up, clean up, install, reload; the boot coordinator owns its inverse.

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
            if item["kind"] == "boot":
                continue  # The boot inverse owns these; legacy sync cannot parse their paths.
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
                if item["kind"] == "boot":
                    continue  # The durable boot coordinator settles these before downgrade.
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
        boot.verify_maintenance(root, release_id, verify)
        native = release / RELEASE_NATIVE
        if not native.is_dir():
            raise SyncError(f"IMAGE_LAYER_SOURCE: release {release_id} has no {RELEASE_NATIVE}")
        try:
            if not dry_run:
                boot.inverse(root, release_id, verify, runner, install=_install)
            boot.prepare(root, native, release_id, verify, dry_run=dry_run)
        except ValueError as exc:
            raise SyncError(str(exc)) from exc
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


def inverse_boot_layer(root: Path, target: str, *, verify, runner: Runner = _run, dry_run: bool = False) -> dict:
    with _release_lock(root):
        return boot.inverse_maintenance(root, target, verify, runner, install=_install, dry_run=dry_run)


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
    parser.add_argument("--inverse-before-legacy-sync", action="store_true")
    parser.add_argument("--rollback-target-previous", action="store_true")
    args = parser.parse_args(argv)
    if args.rollback_target_previous and not args.inverse_before_legacy_sync:
        parser.error("--rollback-target-previous requires --inverse-before-legacy-sync")
    public_key = args.public_key or args.root / DEFAULT_PUBLIC_KEY
    try:
        verify = _verifier(args.root, public_key)
        if args.inverse_before_legacy_sync:
            target, _ = resolve_current(args.root, is_link=is_link, readlink=readlink)
            if args.rollback_target_previous:
                target = boot._previous(args.root)
                if target is None:
                    raise SyncError("BOOT_INVERSE: previous release is not a validated release link")
                verify(target)
            result = inverse_boot_layer(args.root, target, verify=verify, runner=runner, dry_run=args.dry_run)
        else:
            result = sync(args.root, dry_run=args.dry_run, verify=verify, runner=runner,
                          is_link=is_link, readlink=readlink)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        result = {"ok": False, "error": str(exc)}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1
