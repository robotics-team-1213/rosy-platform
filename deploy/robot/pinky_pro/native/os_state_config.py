"""Serialized canonical configuration updates shared by both OS roots."""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import uuid

from first_boot_runtime import _json_atomic
from os_state_firstboot import FirstBootState
from os_state_files import (CONFIG_FILES, INITIAL, POINTER_FIELDS, PUBLICATION, initial_changes,
                            load_record, project_files, validate_projection)
from os_state_layout import COMMON, StateError, _layout, _path, _read


@contextlib.contextmanager
def common_lock(root: Path):
    root = Path(root).absolute()
    try:
        found = _layout(root)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise StateError(f"OS_STATE_HOLD: {exc}") from exc
    if found is None:
        yield None
        return
    with contextlib.ExitStack() as cleanup:
        try:
            shared = FirstBootState(root, found[0])
            path = _path(root, COMMON + "/state/config.lock")
            descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
            cleanup.callback(os.close, descriptor)
            info = os.fstat(descriptor)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != root.stat().st_uid
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
                raise ValueError("canonical configuration lock is unsafe")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            shared.validate_storage_state()
        except StateError:
            raise
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise StateError(f"OS_STATE_HOLD: {exc}") from exc
        yield shared


class ConfigurationUpdate:
    def __init__(self, root: Path, shared: FirstBootState | None, expected_generation: str | None):
        self.root, self.shared = root, shared
        self.changes = {}
        self.committed = False
        self.pointer = None
        self.values = {}
        if shared is None:
            if expected_generation is not None:
                raise ValueError("legacy configuration has no canonical generation")
            return
        if shared.current.exists():
            self.pointer, manifest, self.values = shared._generation()
            if expected_generation is not None and self.pointer["generation"] != expected_generation:
                raise ValueError("canonical configuration revision changed")
            shared.prepare_existing()
            self.completion = manifest["completion"]
        else:
            if expected_generation is not None:
                raise ValueError("canonical configuration has not been committed")
            initial = shared._pending() if shared.pending.exists() else load_record(
                root, COMMON + "/state/factory.json", {"schema_version", "state_schema", "factory_id"})
            self.factory_id = initial["factory_id"]
            self.values = initial_changes(root, self.factory_id)
            project_files(root, self.values)

    @property
    def card(self) -> Path:
        relative = "run/rosy-provision-boot/rosy-config.yaml" if self.shared is not None else "boot/firmware/rosy-config.yaml"
        return self.root / relative

    def handles(self, path: Path) -> bool:
        if self.shared is None:
            return False
        try:
            return Path(path).absolute().relative_to(self.root).as_posix() in CONFIG_FILES
        except ValueError:
            return False

    def stage(self, relative: str, data: bytes | None, mode: int) -> None:
        if self.shared is None or self.committed:
            raise ValueError("configuration update is not open")
        supported = {**CONFIG_FILES, "etc/rosy/runtime.env": 0o640}
        if relative == "etc/rosy/runtime.env" and (self.pointer is None or data is None):
            raise ValueError("runtime changes require a committed device identity")
        if relative not in supported or type(mode) is not int or mode != supported[relative]:
            raise ValueError("configuration file or mode is unsupported")
        validate_projection(self.root, {relative: data})
        self.changes[relative] = data

    def commit(self) -> None:
        if self.committed:
            raise ValueError("configuration update already committed")
        if self.shared is None or not self.changes:
            self.committed = True
            return
        values = {**self.values, **self.changes}
        validate_projection(self.root, values)
        if self.pointer is None:
            record = dict(schema_version=1, state_schema=1,
                factory_id=self.factory_id,
                changes={key: value.decode("utf-8") if value is not None else None for key, value in values.items()})
            encoded = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            if len(encoded) > 64 * 1024:
                raise ValueError("initial configuration record exceeds reader limit")
            _json_atomic(_path(self.root, INITIAL), record, 0o600)
            project_files(self.root, values)
        else:
            current = load_record(self.root, COMMON + "/state/current.json", POINTER_FIELDS)
            if current != self.pointer:
                raise ValueError("canonical configuration revision changed")
            pointer = self.shared.stage_generation(str(uuid.uuid4()), self.completion, values)
            prior = _read(self.shared.complete, 64 * 1024, self.root.stat().st_uid)
            _json_atomic(_path(self.root, PUBLICATION), dict(schema_version=1, state_schema=1,
                previous=self.pointer, current=pointer, previous_completion_sha256=hashlib.sha256(prior).hexdigest()), 0o600)
            _json_atomic(self.shared.current, pointer, 0o600)
            self.shared.prepare_existing()
            self.pointer = pointer
        self.committed = True


@contextlib.contextmanager
def configuration_update(root: Path, *, expected_generation: str | None = None):
    root = Path(root).absolute()
    with common_lock(root) as shared:
        update = ConfigurationUpdate(root, shared, expected_generation)
        yield update
        if update.changes and not update.committed:
            raise ValueError("canonical configuration changes were not committed")


def commit_runtime(root: Path, data: bytes, *, expected: bytes) -> None:
    """Publish a privileged runtime edit without losing a concurrent settings change."""
    with configuration_update(root) as update:
        if update.shared is None or update.pointer is None:
            raise ValueError("runtime publication requires a provisioned A/B device")
        if update.values["etc/rosy/runtime.env"] != expected:
            raise ValueError("canonical runtime changed before publication")
        update.stage("etc/rosy/runtime.env", data, 0o640)
        update.commit()
