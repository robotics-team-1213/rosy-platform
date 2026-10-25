"""Compiled device-setting files, tombstones and per-root derived timezone state."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import uuid

from first_boot_runtime import _write_atomic
from os_state_layout import COMMON, _digest, _guid, _object, _path, _read

BASE_FILES = {"etc/rosy/device-identity.json": 0o644, "etc/rosy/runtime.env": 0o640,
              "etc/hostname": 0o644, "etc/hosts": 0o644}
CONFIG_FILES = {"etc/rosy/network-policy.json": 0o600, "etc/rosy/login-policy.json": 0o600,
                "etc/rosy/ap-credentials.json": 0o600, "etc/rosy/fleet-bootstrap.json": 0o600,
                "etc/rosy/timezone.json": 0o600, "var/lib/rosy/config/applied.json": 0o600}
ROOT_FILES = {**BASE_FILES, **CONFIG_FILES}
INITIAL = COMMON + "/state/config-initializing.json"
PUBLICATION = COMMON + "/state/config-publishing.json"
POINTER_FIELDS = {"schema_version", "state_schema", "generation", "manifest_sha256"}


def sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def load_record(root: Path, relative: str, fields: set[str]) -> dict:
    return _object(_read(_path(root, relative), 64 * 1024, root.stat().st_uid), fields)


def initial_changes(root: Path, factory_id: str) -> dict[str, bytes | None]:
    if not _path(root, INITIAL).exists():
        return {}
    record = load_record(root, INITIAL, {"schema_version", "state_schema", "factory_id", "changes"})
    if record["factory_id"] != factory_id or not isinstance(record["changes"], dict):
        raise ValueError("initial configuration belongs to a different factory state")
    _guid(record["factory_id"])
    result = {}
    for name, value in record["changes"].items():
        if name not in CONFIG_FILES or value is not None and not isinstance(value, str):
            raise ValueError("initial configuration file/value is unsupported")
        data = value.encode("utf-8") if value is not None else None
        if data is not None and len(data) > 64 * 1024:
            raise ValueError("initial configuration file exceeds limit")
        result[name] = data
    return result


def _timezone(root: Path, data: bytes | None) -> str | None:
    if data is None:
        return None
    value = _object(data, {"schema_version", "timezone"})["timezone"]
    if (not isinstance(value, str) or not value or value.startswith("/") or "\\" in value
            or any(part in ("", ".", "..") for part in value.split("/"))):
        raise ValueError("invalid canonical timezone")
    bank = _path(root, "usr/share/zoneinfo").resolve()
    source = (bank / value).resolve()
    if not source.is_relative_to(bank):
        raise ValueError("timezone escapes the OS zoneinfo directory")
    _read(source, 1024 * 1024, root.stat().st_uid)
    return value


def validate_projection(root: Path, values: dict[str, bytes | None]) -> dict[str, Path]:
    targets = {}
    for name, data in values.items():
        if name not in ROOT_FILES or data is None and name in BASE_FILES:
            raise ValueError("unsupported canonical file/deletion")
        if data is not None:
            if not isinstance(data, bytes) or len(data) > 64 * 1024:
                raise ValueError("canonical file is not bounded bytes")
            data.decode("utf-8")
        target = _path(root, name)
        if target.exists():
            _read(target, 64 * 1024, root.stat().st_uid)
        targets[name] = target
    if "etc/rosy/timezone.json" in values:
        _timezone(root, values["etc/rosy/timezone.json"])
    return targets


def project_files(root: Path, values: dict[str, bytes | None]) -> None:
    targets = validate_projection(root, values)
    timezone = _timezone(root, values.get("etc/rosy/timezone.json"))
    localtime = _path(root, "etc") / "localtime"
    if timezone is not None and (localtime.exists() or localtime.is_symlink()):
        info = localtime.lstat()
        if info.st_uid != root.stat().st_uid or not (stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)):
            raise ValueError("timezone projection target is unsafe")
    for name, target in targets.items():
        data = values[name]
        if data is None:
            if target.exists():
                target.unlink()
                sync_directory(target.parent)
        elif (not target.exists() or _read(target, 64 * 1024, root.stat().st_uid) != data
              or stat.S_IMODE(target.stat().st_mode) != ROOT_FILES[name]):
            _write_atomic(target, data.decode("utf-8"), ROOT_FILES[name])
    if timezone is not None:
        temporary = localtime.with_name(".rosy-localtime-" + uuid.uuid4().hex)
        try:
            temporary.symlink_to("/usr/share/zoneinfo/" + timezone)
            os.replace(temporary, localtime)
            sync_directory(localtime.parent)
        finally:
            temporary.unlink(missing_ok=True)
        _write_atomic(root / "etc/timezone", timezone + "\n", 0o644)


def transition(root: Path, pointer: dict, complete: dict, raw: bytes, expected: dict) -> None:
    path = _path(root, PUBLICATION)
    if not path.exists():
        if complete != expected:
            raise ValueError("completion differs from committed generation")
        return
    record = load_record(root, PUBLICATION, {"schema_version", "state_schema", "previous", "current",
                                            "previous_completion_sha256"})
    for key in ("previous", "current"):
        item = _object(json.dumps(record[key]).encode("utf-8"), POINTER_FIELDS)
        _guid(item["generation"])
        _digest(item["manifest_sha256"])
    _digest(record["previous_completion_sha256"])
    if pointer not in (record["previous"], record["current"]):
        raise ValueError("configuration publication belongs to another generation")
    if complete == expected:
        if pointer == record["previous"] and hashlib.sha256(raw).hexdigest() != record["previous_completion_sha256"]:
            raise ValueError("previous publication completion checksum differs")
        return
    prior = record["previous"]
    without_reference = {key: value for key, value in complete.items() if key != "os_state"}
    if (pointer != record["current"] or complete.get("os_state") != {
            "generation": prior["generation"], "manifest_sha256": prior["manifest_sha256"]}
            or without_reference != {key: value for key, value in expected.items() if key != "os_state"}
            or hashlib.sha256(raw).hexdigest() != record["previous_completion_sha256"]):
        raise ValueError("configuration publication has no matching completion proof")


def clear_transition(root: Path) -> None:
    path = _path(root, PUBLICATION)
    if path.exists():
        path.unlink()
        sync_directory(path.parent)
