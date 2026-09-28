"""Compose signed staging, generation preparation, and the existing activation journal."""
from __future__ import annotations

from dataclasses import asdict, replace
import json
from pathlib import Path
import shutil
from typing import Protocol
import uuid

from bundle import BundleError, release_id, stage_archive, verify_tree
from layout import ActivationRecord, Layout, read_activation
from storage import check_update_headroom, directory_size
from updater import Updater


class RuntimePort(Protocol):
    def assert_stopped(self) -> None: ...
    def load_images(self, root: Path, manifest: dict) -> None: ...
    def prepare_data(self, path: Path) -> None: ...
    def stop(self) -> None: ...
    def start(self, mode: str) -> None: ...
    def healthy(self) -> bool: ...


def copy_regular(source: Path, target: Path):
    """Copy local snapshots without following links into unrelated host data."""
    if source.is_symlink() or any(p.is_symlink() for p in source.rglob("*")):
        raise BundleError("DATA_SYMLINK", "snapshot sources must not contain symlinks")
    if source.is_dir():
        shutil.copytree(source, target)
    else:
        shutil.copy2(source, target)


class Delivery:
    def __init__(self, layout: Layout, key: Path, runtime: RuntimePort, *, device_target: dict):
        self.layout, self.key, self.runtime, self.target = layout, key, runtime, device_target
        self.updater = Updater(layout, stop_runtime=runtime.stop, start_runtime=runtime.start,
                               health_check=runtime.healthy)
        # Host-owned: do not put authority for a manual rollback in CORE's writable data mount.
        self.previous = layout.previous_activation

    def current(self):
        return read_activation(self.layout) if self.layout.activation.exists() else None

    def status(self):
        current = self.current()
        return {"activation": asdict(current) if current else None,
                "state": self.updater.read_state(), "recovery_hold": self.updater.read_recovery_hold(),
                "staged": sorted(p.name for p in self.layout.staging.glob("*")
                                 if p.is_dir() and not p.name.startswith("."))}

    def stage(self, path):
        return stage_archive(path, self.layout, self.key, device_target=self.target).name

    def install(self, version, *, health_timeout_s=90.0):
        version = release_id(version)
        if self.updater.read_recovery_hold() is not None or self.layout.journal.exists():
            raise BundleError("RECOVERY_HELD", "finish recovery before installation")
        self.runtime.assert_stopped()
        old = self.current()
        if old is None and not self.updater._never_activated():
            raise BundleError("ACTIVATION_MISSING", "activation history exists; recover it before installing")
        if old and version <= old.release_id:
            raise BundleError("RELEASE_NOT_NEWER", "use explicit rollback for a previous release")
        staged = self.layout.staging / version
        manifest = verify_tree(staged, self.key, device_target=self.target)
        if manifest["release_id"] != version:
            raise BundleError("RELEASE_ID_MISMATCH", "staging name differs from signed manifest")
        source_config = (self.layout.config_generation(old.config_generation) / "rosy.yaml"
                         if old else self.layout.etc / "rosy.yaml")
        source_data = self.layout.var / "data-working" / old.data_generation if old else None
        if not source_config.is_file() or source_config.is_symlink():
            raise BundleError("CONFIG_MISSING", "enroll a regular device-owned rosy.yaml before installation")
        if source_data is not None and not source_data.is_dir():
            raise BundleError("DATA_MISSING", "active working data is unavailable")
        data_names = (".rosy", "maps", "waypoints.json", "docks.json", "events", "audit.jsonl")
        size = directory_size(source_data) if source_data else sum(
            directory_size(self.layout.var / name) if (self.layout.var / name).is_dir()
            else (self.layout.var / name).stat().st_size if (self.layout.var / name).is_file() else 0
            for name in data_names)
        # Staging can be days old. Recheck before copying a release or loading an image.
        for filesystem in (self.layout.opt, self.layout.var):
            rejected = check_update_headroom(max(1, directory_size(staged) + size), staging=filesystem)
            if rejected:
                raise BundleError(rejected[0].code, rejected[0].detail)
        destination = self.layout.release(version)
        if destination.exists():
            verify_tree(destination, self.key, device_target=self.target)
            if (destination / "SHA256SUMS").read_bytes() != (staged / "SHA256SUMS").read_bytes():
                raise BundleError("RELEASE_ID_REUSED", "installed release id has different content")
        else:
            shutil.copytree(staged, destination)
        # Staging is owner-private. Signed nonsecret runtime payload must be
        # readable by the non-root CORE after freeze_tree removes write bits.
        for entry in [destination, *destination.rglob("*")]:
            entry.chmod(0o755 if entry.is_dir() else 0o644)
        self.runtime.load_images(destination, manifest)
        generation = version + "-" + uuid.uuid4().hex[:12]
        config = self.layout.config_generation(generation)
        snapshot = self.layout.data_generation(generation)
        working = self.layout.var / "data-working" / generation
        config.mkdir(parents=True)
        copy_regular(source_config, config / "rosy.yaml")
        if source_data:
            copy_regular(source_data, snapshot)
        else:
            snapshot.mkdir(parents=True)
            for name in data_names:
                source = self.layout.var / name
                if source.exists():
                    copy_regular(source, snapshot / name)
        copy_regular(snapshot, working)
        self.runtime.prepare_data(working)
        candidate = ActivationRecord.create(release_id=version, release_path=destination,
                                            config_generation=generation, data_generation=generation)
        return self.updater.activate(candidate, health_timeout_s=health_timeout_s)

    def rollback(self):
        self.runtime.assert_stopped()
        if self.layout.journal.exists():
            raise BundleError("RECOVERY_REQUIRED", "finish the pending activation recovery first")
        if not self.previous.is_file():
            raise BundleError("PREVIOUS_UNAVAILABLE", "no completed previous activation is recorded")
        previous = ActivationRecord(**json.loads(self.previous.read_text(encoding="utf-8")))
        # Validate record containment using the same boundary as boot, without changing activation.
        from layout import _check_contained
        _check_contained(self.layout, asdict(previous), self.previous)
        manifest = verify_tree(Path(previous.release_path), self.key, device_target=self.target)
        if manifest["release_id"] != previous.release_id:
            raise BundleError("RELEASE_ID_MISMATCH", "previous activation differs from signed release")
        self.runtime.load_images(Path(previous.release_path), manifest)
        return self.updater.activate(replace(previous, runtime_mode="core"))
