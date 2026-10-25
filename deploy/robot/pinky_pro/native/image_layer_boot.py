"""Signed, explicitly owned boot files and a durable inverse for legacy rollback."""

from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
import re
import stat
import tempfile

from image_layer_files import _install, _mode, _sha256


CAPABILITIES = ("boot_catalog_v1", "inverse_before_legacy_sync_v1")
BOOT_FILES = {"rosy-first-boot.py": 0o644, "rosy-first-boot.sh": 0o755}
BOOT_DIRECTORY = "opt/rosy/first-boot"
CATALOG = "image-layer/boot/catalog.json"
FEATURE_UNITS = ("rosy-network-users.service", "rosy-network-agent.service",
                 "rosy-network-recovery.service", "rosy-network-recovery.timer")
ENGINE_FILES = ("sync-image-layer.py", "image-layer-reconcile.py", "auto_update_apply.py",
                "auto_update_records.py", "auto_update_host.py", "auto_update_stage.py", "os_state_layout.py",
                "first_boot_runtime.py", "os_state_firstboot.py", "os_state_storage.py", "os_storage_dispatch.py", "os_state_accounts.py",
                "os_state_files.py", "os_state_config.py", "operator_keys.py", "os_state_tls.py", "os_state_io.py",
                "rosy_auto_update.py", "rosy_claim.py",
                "image_layer_boot.py", "image_layer_files.py")
# The signed bridge-v1 baseline stays valid when later engines add helpers.
BRIDGE_V1_FILES = ("sync-image-layer.py", "image-layer-reconcile.py", "auto_update_apply.py",
                   "auto_update_records.py", "auto_update_host.py", "auto_update_stage.py",
                   "rosy_auto_update.py", "rosy_claim.py", "image_layer_boot.py", "image_layer_files.py")
BACKUPS = "var/lib/rosy/image-layer-backup"
JOURNAL = BACKUPS + "/boot-transition.json"
RELEASE_ID = re.compile(r"[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]{3}")


def _safe(root: Path, relative: str) -> Path:
    parts = relative.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("BOOT_INVERSE: invalid path")
    path = root
    for part in parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("BOOT_INVERSE: symlink in managed path")
    return path


def _read(path: Path) -> dict:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 1024 * 1024:
            raise ValueError("BOOT_INVERSE: invalid journal or catalog")
        value = json.loads(os.read(descriptor, 1024 * 1024 + 1))
    finally:
        os.close(descriptor)
    if not isinstance(value, dict):
        raise ValueError("BOOT_INVERSE: expected an object")
    return value


def _fsync_directory(path: Path) -> None:
    if os.name == "posix":
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _save(root: Path, data: dict) -> None:
    path = _safe(root, JOURNAL)
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=".boot-transition-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def catalog_entries(native: Path) -> list[dict]:
    path = _safe(native, CATALOG)
    if not path.exists():
        return []
    try:
        data = _read(path)
        files = data.get("files")
        if (set(data) != {"schema", "files"} or type(data["schema"]) is not int or data["schema"] != 1
                or not isinstance(files, dict) or not files):
            raise ValueError("unsupported catalog")
        entries = []
        for name, digest in files.items():
            if name not in BOOT_FILES or not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
                raise ValueError("unapproved file")
            source = _safe(native, "image-layer/boot/" + name)
            if not source.is_file() or _sha256(source) != digest:
                raise ValueError("missing file or hash mismatch")
            entries.append({"source": source, "destination": BOOT_DIRECTORY + "/" + name,
                            "kind": "boot", "mode": BOOT_FILES[name]})
        return entries
    except (OSError, ValueError) as exc:
        raise ValueError("BOOT_CATALOG: invalid signed boot inventory") from exc


def build_catalog(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for name, mode in BOOT_FILES.items():
        original = _safe(source, name)
        if not original.is_file():
            raise ValueError("BOOT_CATALOG: required boot support is missing")
        _install(original, destination / name, mode)
    (destination / "catalog.json").write_text(json.dumps({"schema": 1, "files": {
        name: _sha256(destination / name) for name in BOOT_FILES
    }}, sort_keys=True) + "\n", encoding="utf-8")


def _previous(root: Path) -> str | None:
    link = root / "opt/rosy/previous"
    if not link.is_symlink():
        return None
    target = link.resolve()
    if target.parent != (root / "opt/rosy/releases").resolve() or not RELEASE_ID.fullmatch(target.name):
        raise ValueError("BOOT_BRIDGE_REQUIRED: invalid previous release")
    return target.name


def _engine_contract(native: Path) -> tuple[tuple[str, ...], bytes]:
    path = _safe(native, "image_layer_boot.py")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(descriptor, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError("BOOT_BRIDGE_REQUIRED: engine metadata is not a regular file")
        raw = handle.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError("BOOT_BRIDGE_REQUIRED: engine metadata exceeds size limit")
    tree = ast.parse(raw)
    declared = {target.id: ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                for target in node.targets if isinstance(target, ast.Name)
                and target.id in ("ENGINE_FILES", "CAPABILITIES")}
    files = declared["ENGINE_FILES"]
    if (not isinstance(files, tuple) or not len(BRIDGE_V1_FILES) <= len(files) <= 64
            or any(not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*\.py", name) for name in files)
            or len(set(files)) != len(files) or not set(BRIDGE_V1_FILES) <= set(files)
            or not set(CAPABILITIES) <= set(declared["CAPABILITIES"])):
        raise ValueError("BOOT_BRIDGE_REQUIRED: invalid engine closure or capabilities")
    return files, raw


def _engine_snapshot(native: Path, installed: Path, files: tuple[str, ...]) -> dict[str, str] | None:
    result = {}
    for name in files:
        if not _safe(native, name).is_file() or not _safe(installed, name).is_file():
            return None
        digest = _sha256(native / name)
        if _sha256(installed / name) != digest:
            return None
        result[name] = digest
    return result


def require_bridge(root: Path, release_id: str, verify) -> str:
    """Capabilities come from installed bytes matching a verified signed release."""
    for candidate in dict.fromkeys([release_id, _previous(root)]):
        if candidate is None:
            continue
        native = root / "opt/rosy/releases" / candidate / "deploy/robot/native"
        installed = root / "opt/rosy/native-runtime"
        try:
            files, snapshot = _engine_contract(native)
            before = _engine_snapshot(native, installed, files)
            if before is None:
                continue
            verify(candidate)
            # The closure declaration and installed bytes must still be the
            # same snapshot after the caller verified the signed release.
            if _engine_contract(native)[1] == snapshot and _engine_snapshot(native, installed, files) == before:
                return _previous(root) or candidate
        except (OSError, ValueError, SyntaxError, StopIteration, TypeError, KeyError):
            continue
    raise ValueError("BOOT_BRIDGE_REQUIRED: install the signed continuity bridge first")


def _transitions(root: Path) -> list[dict]:
    path = _safe(root, JOURNAL)
    if not path.exists():
        return []
    try:
        data = _read(path)
        transitions = data["transitions"]
        if not isinstance(transitions, list):
            raise ValueError("invalid transitions")
        for item in transitions:
            if not isinstance(item, dict) or not all(RELEASE_ID.fullmatch(str(item.get(key, "")))
                                                    for key in ("release_id", "previous_release")):
                raise ValueError("invalid release identity")
            if not isinstance(item.get("files"), list):
                raise ValueError("invalid files")
        return transitions
    except (OSError, ValueError, KeyError) as exc:
        raise ValueError("BOOT_INVERSE: unreadable transition journal") from exc


def prepare(root: Path, native: Path, release_id: str, verify, *, dry_run: bool) -> None:
    entries = catalog_entries(native)
    if not entries:
        return
    previous = require_bridge(root, release_id, verify)
    transitions = _transitions(root)
    if transitions and transitions[-1]["release_id"] == release_id:
        return
    for name in FEATURE_UNITS:
        source = native / name
        if source.is_file():
            entries.append({"source": source, "destination": "etc/systemd/system/" + name, "mode": 0o644})
    for entry in entries:
        destination = _safe(root, entry["destination"])
        if destination.exists() and not destination.is_file():
            raise ValueError("BOOT_INVERSE: destination is not a regular file")
    if dry_run:
        return
    folder = _safe(root, BACKUPS)
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    _fsync_directory(folder.parent)
    backup = Path(tempfile.mkdtemp(prefix="boot-" + release_id + "-", dir=folder))
    records = []
    for index, entry in enumerate(entries):
        destination = root / entry["destination"]
        record = {"path": entry["destination"], "sha256": _sha256(entry["source"]),
                  "mode": entry["mode"], "backup": None, "previous_sha256": None, "previous_mode": None}
        if destination.exists():
            saved = backup / str(index)
            _install(destination, saved, _mode(destination))
            record.update(backup=saved.relative_to(root).as_posix(), previous_sha256=_sha256(saved),
                          previous_mode=_mode(saved))
        records.append(record)
    _fsync_directory(backup)
    _fsync_directory(folder)
    transition = {"release_id": release_id, "previous_release": previous, "files": records}
    _save(root, {**transition, "transitions": transitions + [transition]})


def _check(runner, argv) -> None:
    if runner(argv).returncode != 0:
        raise ValueError("BOOT_INVERSE: unit reconciliation failed")


def reconcile_forward(root: Path, target: str, verify, *, install=_install) -> None:
    transitions = _transitions(root)
    if not transitions or transitions[-1]["release_id"] != target:
        return
    verify(target)
    records = {item["path"]: item for item in transitions[-1]["files"]}
    native = root / "opt/rosy/releases" / target / "deploy/robot/native"
    for entry in catalog_entries(native):
        record = records.get(entry["destination"])
        if record is None:
            raise ValueError("BOOT_INVERSE: boot inventory differs from the transition")
        destination = _safe(root, entry["destination"])
        if destination.exists():
            digest = _sha256(destination)
            if digest not in {record["sha256"], record["previous_sha256"]}:
                raise ValueError("BOOT_INVERSE: boot file changed outside the transition")
            if digest == record["sha256"] and _mode(destination) == entry["mode"]:
                continue
        elif record["backup"]:
            raise ValueError("BOOT_INVERSE: prior boot file is missing")
        install(entry["source"], destination, entry["mode"])


def inverse(root: Path, target: str, verify, runner, *, install=_install, dry_run: bool = False) -> dict:
    """Idempotently restore protected files before a legacy sync can downgrade us."""
    transitions = _transitions(root)
    restored = []
    simulated = {}
    allowed = {BOOT_DIRECTORY + "/" + name for name in BOOT_FILES}
    allowed.update("etc/systemd/system/" + name for name in FEATURE_UNITS)
    while transitions and transitions[-1]["release_id"] > target:
        transition = transitions[-1]
        verify(target)
        verify(transition["release_id"])
        verify(transition["previous_release"])
        files = transition["files"]
        # Validate the entire inverse before stopping a service or restoring one file.
        for record in files:
            if not isinstance(record, dict) or record.get("path") not in allowed:
                raise ValueError("BOOT_INVERSE: unexpected managed path")
            destination = _safe(root, record["path"])
            saved = record.get("backup")
            if saved:
                if not isinstance(saved, str) or not saved.startswith(BACKUPS + "/boot-"):
                    raise ValueError("BOOT_INVERSE: unexpected backup path")
                backup = _safe(root, saved)
                if not backup.is_file() or _sha256(backup) != record["previous_sha256"]:
                    raise ValueError("BOOT_INVERSE: missing or corrupt backup")
                if _mode(backup) != record["previous_mode"]:
                    raise ValueError("BOOT_INVERSE: backup mode changed")
            if record["path"] in simulated:
                if simulated[record["path"]] not in {record["sha256"], record["previous_sha256"]}:
                    raise ValueError("BOOT_INVERSE: transition chain does not match")
            elif destination.exists():
                if not destination.is_file() or _sha256(destination) not in {
                    record["sha256"], record["previous_sha256"],
                }:
                    raise ValueError("BOOT_INVERSE: managed file changed unexpectedly")
            elif saved:
                raise ValueError("BOOT_INVERSE: managed file unexpectedly missing")
        if dry_run:
            simulated.update({record["path"]: record["previous_sha256"] for record in files})
            transitions.pop()
            continue
        for record in reversed(files):
            destination = root / record["path"]
            if (record["path"].startswith("etc/systemd/system/") and not record["backup"]
                    and destination.exists()):
                _check(runner, ["systemctl", "disable", "--now", destination.name])
            if record["backup"]:
                install(root / record["backup"], destination, record["previous_mode"])
            else:
                destination.unlink(missing_ok=True)
            _fsync_directory(destination.parent)
            restored.append("/" + record["path"])
        _check(runner, ["systemctl", "daemon-reload"])
        transitions.pop()
        if transitions:
            _save(root, {**transitions[-1], "transitions": transitions})
    if not transitions and not dry_run:
        journal = _safe(root, JOURNAL)
        journal.unlink(missing_ok=True)
        if journal.parent.exists():
            _fsync_directory(journal.parent)
    return {"ok": True, "dry_run": dry_run, "restored": restored}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build-catalog"])
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    build_catalog(args.source, args.destination)


if __name__ == "__main__":
    main()
