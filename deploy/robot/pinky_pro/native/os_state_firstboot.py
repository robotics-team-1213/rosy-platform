"""Durable firstboot generations; mutable service data stays in its shared mounts."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import uuid

from os_state_io import _json_atomic, _write_atomic
from os_state_layout import (
    COMMON, StateError, _digest, _guid, _layout, _object, _pairs, _path, _read, shared_mount_facts,
)
from os_state_accounts import validate_local_accounts, validate_shared_owners
from os_state_files import (BASE_FILES, ROOT_FILES, clear_transition, initial_changes,
                            project_files, transition, validate_projection)

# Live CORE tokens, NetworkManager profiles and consumable join secrets are never projected.
PENDING_FIELDS = {"schema_version", "state_schema", "generation", "device_uid",
                  "hardware_serial", "bundle_checksum", "factory_id"}
MANIFEST_FIELDS = {"schema_version", "state_schema", "generation", "device_uid",
                   "hardware_serial", "files", "completion"}


def _sync(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _mkdir(path: Path) -> None:
    if not path.exists():
        path.mkdir(mode=0o700)
        _sync(path.parent)
    if path.is_symlink() or not path.is_dir():
        raise ValueError("state directory is not a directory")


def _load(path: Path, owner: int, fields: set[str] | None = None) -> dict:
    raw = _read(path, 64 * 1024, owner)
    value = _object(raw, fields) if fields else json.loads(raw, object_pairs_hook=_pairs)
    if not isinstance(value, dict):
        raise ValueError("state object is not a mapping")
    return value


def _hold(operation):
    def guarded(*args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except StateError:
            raise
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise StateError(f"OS_STATE_HOLD: {exc}") from exc
    return guarded


class FirstBootState:
    """Called under the existing firstboot network lock, before any root mutation."""

    def __init__(self, root: Path, layout: dict):
        self.root, self.layout = root, layout
        self.owner = root.stat().st_uid
        shared_mount_facts(root, layout)
        validate_local_accounts(root)
        validate_shared_owners(root)
        schema = _load(_path(root, COMMON + "/state/schema.json"), self.owner,
                       {"schema_version", "state_schema"})
        if schema != {"schema_version": 1, "state_schema": 1}:
            raise ValueError("unsupported common schema")
        self.directory = _path(root, COMMON + "/state")
        if not self.directory.is_dir():
            raise ValueError("state directory missing")
        self.current = self.directory / "current.json"
        self.pending = self.directory / "initializing.json"
        self.factory = self.directory / "factory.json"
        self.complete = _path(root, "var/lib/rosy/provisioning/complete.json")
        self.record = None

    @classmethod
    @_hold
    def admit(cls, root: Path):
        found = _layout(root)
        if found is None:
            return None
        shared = cls(root, found[0])
        shared.validate_storage_state()
        return shared

    def validate_storage_state(self) -> str:
        if self.current.exists():
            if self.factory.exists():
                raise ValueError("committed device still has a factory marker")
            self._committed()
            return "COMMITTED"
        if self.complete.exists():
            raise ValueError("completion has no committed generation")
        identity = _path(self.root, "etc/rosy/device-identity.json")
        binding = _path(self.root, "var/lib/rosy/provisioning/hardware-binding.json")
        if self.pending.exists():
            pending = self._pending()
            if self.factory.exists():
                factory = _load(self.factory, self.owner, {"schema_version", "state_schema", "factory_id"})
                if factory["factory_id"] != pending["factory_id"]:
                    raise ValueError("factory marker differs from initialization")
            if identity.exists() and _load(identity, self.owner).get("device_uid") != pending["device_uid"]:
                raise ValueError("cached identity differs from initialization")
            if binding.exists() and _load(binding, self.owner) != {
                    "device_uid": pending["device_uid"], "hardware_serial": pending["hardware_serial"]}:
                raise ValueError("hardware binding differs from initialization")
            initial_changes(self.root, pending["factory_id"])
            return "INITIALIZING"
        factory = _load(self.factory, self.owner, {"schema_version", "state_schema", "factory_id"})
        _guid(factory["factory_id"])
        if identity.exists() or binding.exists():
            raise ValueError("factory device contains a cached device binding")
        initial_changes(self.root, factory["factory_id"])
        return "FACTORY_EMPTY"

    def _pending(self) -> dict:
        record = _load(self.pending, self.owner, PENDING_FIELDS)
        for name in ("generation", "device_uid", "factory_id"):
            _guid(record[name])
        _digest(record["bundle_checksum"])
        if not isinstance(record["hardware_serial"], str):
            raise ValueError("invalid initialization hardware binding")
        return record

    def _generation(self) -> tuple[dict, dict, dict[str, bytes | None]]:
        pointer = _load(self.current, self.owner,
                        {"schema_version", "state_schema", "generation", "manifest_sha256"})
        generation = _guid(pointer["generation"])
        _digest(pointer["manifest_sha256"])
        location = _path(self.root, COMMON + "/state/generations/" + generation)
        raw = _read(location / "manifest.json", 64 * 1024, self.owner)
        if hashlib.sha256(raw).hexdigest() != pointer["manifest_sha256"]:
            raise ValueError("committed generation manifest checksum differs")
        manifest = _object(raw, MANIFEST_FIELDS)
        if manifest["generation"] != generation:
            raise ValueError("generation identity differs")
        _guid(manifest["device_uid"])
        if not isinstance(manifest["files"], dict) or set(manifest["files"]) != set(ROOT_FILES):
            raise ValueError("generation file allowlist differs")
        content = {}
        for relative, mode in ROOT_FILES.items():
            entry = manifest["files"][relative]
            if entry is None and relative not in BASE_FILES:
                content[relative] = None
                continue
            if not isinstance(entry, dict) or set(entry) != {"sha256", "mode"}:
                raise ValueError("invalid generation file entry")
            if type(entry["mode"]) is not int or entry["mode"] != mode:
                raise ValueError("generation file mode differs")
            _digest(entry["sha256"])
            data = _read(location / relative.replace("/", "__"), 64 * 1024, self.owner)
            if hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise ValueError("generation file checksum differs")
            data.decode("utf-8")
            content[relative] = data
        identity = json.loads(content["etc/rosy/device-identity.json"], object_pairs_hook=_pairs)
        complete = manifest["completion"]
        if (not isinstance(complete, dict) or identity.get("device_uid") != manifest["device_uid"]
                or complete.get("device_uid") != manifest["device_uid"]
                or complete.get("hardware_serial") != manifest["hardware_serial"]
                or complete.get("device_name") != identity.get("device_name")):
            raise ValueError("canonical identity/completion binding differs")
        return pointer, manifest, content

    def _committed(self):
        pointer, manifest, content = self._generation()
        expected = dict(manifest["completion"], os_state={
            "generation": pointer["generation"], "manifest_sha256": pointer["manifest_sha256"]})
        binding = _load(_path(self.root, "var/lib/rosy/provisioning/hardware-binding.json"), self.owner)
        if binding != {"device_uid": manifest["device_uid"], "hardware_serial": manifest["hardware_serial"]}:
            raise ValueError("hardware binding differs from generation")
        if self.complete.exists():
            raw = _read(self.complete, 64 * 1024, self.owner)
            transition(self.root, pointer, _load(self.complete, self.owner), raw, expected)
        else:
            pending = self._pending()
            if (pending["generation"] != pointer["generation"]
                    or pending["device_uid"] != manifest["device_uid"]
                    or pending["hardware_serial"] != manifest["hardware_serial"]
                    or pending["bundle_checksum"] != manifest["completion"].get("payload_checksum")):
                raise ValueError("interrupted completion has no matching initialization")
        identity_path = _path(self.root, "etc/rosy/device-identity.json")
        if identity_path.exists() and _load(identity_path, self.owner) != json.loads(
                content["etc/rosy/device-identity.json"]):
            raise ValueError("root identity differs from committed generation")
        return content, expected

    @_hold
    def prepare_existing(self) -> None:
        if not self.current.exists():
            if self.complete.exists():
                raise ValueError("completion has no committed generation")
            return
        content, expected = self._committed()
        project_files(self.root, content)
        if not self.complete.exists() or _load(self.complete, self.owner) != expected:
            _json_atomic(self.complete, expected, 0o640)
        clear_transition(self.root)

    @_hold
    def begin(self, payload: dict, hardware_serial: str, bundle: Path) -> None:
        self.validate_bundle_path(bundle)
        identity = payload["device_identity"]
        if self.current.exists() or self.complete.exists():
            raise ValueError("initialization cannot replace a committed device")
        if self.pending.exists():
            record = self._pending()
            if (record["device_uid"] != identity["device_uid"]
                    or record["hardware_serial"] != hardware_serial
                    or record["bundle_checksum"] != payload["payload_checksum"]):
                raise ValueError("initialization belongs to another bundle/device")
            # Nothing published: a retry uses a new generation, leaving interrupted files inert.
            record["generation"] = str(uuid.uuid4())
            _json_atomic(self.pending, record, 0o600)
        else:
            factory = _load(self.factory, self.owner, {"schema_version", "state_schema", "factory_id"})
            _guid(factory["factory_id"])
            record = dict(schema_version=1, state_schema=1, generation=str(uuid.uuid4()),
                          device_uid=identity["device_uid"], hardware_serial=hardware_serial,
                          bundle_checksum=payload["payload_checksum"], factory_id=factory["factory_id"])
            _json_atomic(self.pending, record, 0o600)
        if self.factory.exists():
            factory = _load(self.factory, self.owner, {"schema_version", "state_schema", "factory_id"})
            if factory["factory_id"] != record["factory_id"]:
                raise ValueError("factory initialization marker differs")
            self.factory.unlink()
            _sync(self.directory)
        self.record = record

    @_hold
    def commit(self, complete: dict) -> dict:
        if self.record is None or self._pending() != self.record:
            raise ValueError("initialization changed before commit")
        project_files(self.root, initial_changes(self.root, self.record["factory_id"]))
        values = {}
        for relative in ROOT_FILES:
            path = _path(self.root, relative)
            values[relative] = (_read(path, 64 * 1024, self.owner)
                                if path.exists() or relative in BASE_FILES else None)
        project_files(self.root, values)
        pointer = self.stage_generation(self.record["generation"], complete, values)
        _json_atomic(self.current, pointer, 0o600)
        return dict(complete, os_state={"generation": pointer["generation"],
                                       "manifest_sha256": pointer["manifest_sha256"]})

    def stage_generation(self, generation: str, complete: dict, values: dict) -> dict:
        _guid(generation)
        if set(values) != set(ROOT_FILES):
            raise ValueError("generation publication file set differs")
        validate_projection(self.root, values)
        generations = _path(self.root, COMMON + "/state/generations")
        _mkdir(generations)
        # An abandoned partial directory never becomes the committed generation.
        location = generations / generation
        if location.exists():
            raise ValueError("generation publication needs recovery of its previous attempt")
        _mkdir(location)
        files = {}
        for relative, mode in ROOT_FILES.items():
            data = values[relative]
            if data is None:
                files[relative] = None
                continue
            data.decode("utf-8")
            target = location / relative.replace("/", "__")
            _write_atomic(target, data.decode("utf-8"), 0o600)
            files[relative] = dict(sha256=hashlib.sha256(data).hexdigest(), mode=mode)
        manifest = dict(schema_version=1, state_schema=1, generation=generation,
                        device_uid=complete["device_uid"], hardware_serial=complete["hardware_serial"],
                        files=files, completion=complete)
        _json_atomic(location / "manifest.json", manifest, 0o600)
        _sync(location)
        _sync(generations)
        digest = hashlib.sha256(_read(location / "manifest.json", 64 * 1024, self.owner)).hexdigest()
        return dict(schema_version=1, state_schema=1, generation=generation, manifest_sha256=digest)

    @_hold
    def consume_bundle(self, bundle: Path) -> None:
        self.validate_bundle_path(bundle)
        bundle.unlink()
        _sync(bundle.parent)

    @_hold
    def validate_bundle_path(self, bundle: Path) -> None:
        # The supplied bundle must be on the admitted persistent provision mount.
        expected = self.root / "run/rosy-provision-boot/rosy-provision/provision.json"
        if bundle.absolute() != expected.absolute():
            raise ValueError("bundle is outside the provision mount")
        _path(self.root, "run/rosy-provision-boot/rosy-provision/provision.json")

    @_hold
    def finish_existing(self, bundle: Path) -> None:
        if not bundle.exists():
            return
        self.validate_bundle_path(bundle)
        payload = _load(bundle, self.owner)
        from first_boot_runtime import validate_provision_bundle
        validate_provision_bundle(payload)
        _, manifest, _ = self._generation()
        if payload["payload_checksum"] != manifest["completion"].get("payload_checksum"):
            raise ValueError("remaining bundle differs from committed device")
        self.consume_bundle(bundle)
