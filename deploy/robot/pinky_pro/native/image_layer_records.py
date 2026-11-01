"""Image-layer sync: backup-record history, cleanup planning and post-install steps (D-388, D-766 split)."""

from __future__ import annotations

from pathlib import Path
import json
import re

from image_layer_files import _mode, _sha256
import image_layer_boot as boot
from image_layer_plan import (
    BACKUP_MANIFEST, BACKUP_ROOT, ENABLED_UNITS, MODPROBE_DIR, Runner, STATE_DIRECTORIES, SyncError, UDEV_DIR,
    UNIT_DIR, _compare_modes, allowlist, check_destination,
)


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
        if unit.endswith((".path", ".timer")) or unit in boot.FEATURE_UNITS:
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
