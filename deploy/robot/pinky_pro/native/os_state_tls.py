"""Recover the bounded TLS maintenance write set before admitting another writer."""
from __future__ import annotations

import base64
import contextlib
import hashlib
import json
from pathlib import Path
import stat
import uuid

from first_boot_runtime import _json_atomic
from os_state_config import ConfigurationUpdate, common_lock
from os_state_files import POINTER_FIELDS, load_record, sync_directory
from os_state_layout import COMMON, TLS_PENDING, _digest, _guid, _object, _path, _read

CONFIG = "var/lib/rosy/core/.rosy/rosy.yaml"
ENV = "etc/rosy/runtime.env"
MODES = {"etc/rosy/tls/" + name: mode for name, mode in (
    ("ca.pem", 0o644), ("ca.key", 0o600), ("leaf.pem", 0o644), ("leaf.key", 0o640),
    ("fullchain.pem", 0o644), ("managed.json", 0o644))}
FIELDS = {"schema_version", "state_schema", "previous", "generation", "device_uid",
          "hardware_serial", "hostname", "targets"}
LIMIT = 2 * 1024 * 1024


def _hash(data):
    return hashlib.sha256(data).hexdigest()


@contextlib.contextmanager
def publication(store):
    with common_lock(store.root) as shared:
        if shared is None or not shared.current.exists():
            raise ValueError("TLS publication requires a committed A/B device")
        yield TLSPublication(store, shared)


class TLSPublication:
    def __init__(self, store, shared):
        self.store, self.shared = store, shared
        self.root = Path(store.root)
        self.path = _path(self.root, TLS_PENDING)
        self.record = None
        self.update = None

    def _read_record(self):
        raw = _read(self.path, LIMIT, self.root.stat().st_uid)
        info = self.path.stat()
        if stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1:
            raise ValueError("TLS recovery record permissions differ")
        record = _object(raw, FIELDS)
        previous = _object(json.dumps(record["previous"]).encode(), POINTER_FIELDS)
        _guid(previous["generation"])
        _digest(previous["manifest_sha256"])
        _guid(record["generation"])
        _, manifest, _ = self.shared._generation()
        if (record["device_uid"] != manifest["device_uid"]
                or record["hardware_serial"] != manifest["hardware_serial"]
                or not isinstance(record["hostname"], str) or len(record["hostname"]) > 253):
            raise ValueError("TLS recovery record belongs to another device")
        self._targets(record)
        return record

    def _targets(self, record):
        entries = record["targets"]
        if not isinstance(entries, dict) or set(entries) != {*MODES, CONFIG, ENV}:
            raise ValueError("TLS recovery write set differs")
        targets = {}
        for path, entry in entries.items():
            if not isinstance(entry, dict) or set(entry) != {"before", "data", "uid", "gid", "mode"}:
                raise ValueError("TLS recovery entry differs")
            if any(type(entry[key]) is not int for key in ("uid", "gid", "mode")):
                raise ValueError("TLS recovery owner/mode type differs")
            roles = ({(0, 0, 0o640)} if path == ENV else
                     {(uid, gid, mode) for uid in (0, self.store.uid) for gid in (0, self.store.gid)
                      for mode in (0o600, 0o640, 0o644)} if path == CONFIG else
                     {(0, self.store.gid if path.endswith("/leaf.key") else 0, MODES[path])})
            if (entry["uid"], entry["gid"], entry["mode"]) not in roles:
                raise ValueError("TLS recovery file authority differs")
            if not isinstance(entry["data"], str) or len(entry["data"]) > 180000:
                raise ValueError("TLS recovery content exceeds limit")
            data = base64.b64decode(entry["data"], validate=True)
            if len(data) > (64 * 1024 if path == ENV else 128 * 1024):
                raise ValueError("TLS recovery content exceeds limit")
            before = entry["before"]
            if before is not None:
                if not isinstance(before, dict) or set(before) != {"sha256", "uid", "gid", "mode"}:
                    raise ValueError("TLS recovery prior file differs")
                _digest(before["sha256"])
                if (any(type(before[key]) is not int for key in ("uid", "gid", "mode"))
                        or (before["uid"], before["gid"], before["mode"]) not in roles):
                    raise ValueError("TLS recovery prior authority differs")
            targets[path] = (data, entry["uid"], entry["gid"], entry["mode"])
        return targets

    def _save(self):
        encoded = json.dumps(self.record, sort_keys=True, separators=(",", ":")).encode()
        if len(encoded) > LIMIT - 1:
            raise ValueError("TLS recovery record exceeds limit")
        _json_atomic(self.path, self.record, 0o600)

    def _current(self):
        return load_record(self.root, COMMON + "/state/current.json", POINTER_FIELDS)

    def _validate_pointer(self):
        current = self._current()
        if current != self.record["previous"] and current["generation"] != self.record["generation"]:
            raise ValueError("TLS recovery canonical revision changed")
        return current

    def recover(self, hostname, fence):
        self.update = ConfigurationUpdate(self.root, self.shared, None)
        if not self.path.exists():
            return None
        self.record = self._read_record()
        if self.record["hostname"] != hostname:
            raise ValueError("TLS recovery hostname changed")
        self._validate_pointer()
        targets = self._targets(self.record)
        # Validate the entire live write set before replaying any member.
        current_files = {path: self.store.read(path) for path in targets}
        for path, current in current_files.items():
            entry = self.record["targets"][path]
            before = entry["before"]
            allowed = {(_hash(targets[path][0]), *targets[path][1:])}
            if before is not None:
                allowed.add((before["sha256"], before["uid"], before["gid"], before["mode"]))
            if current is None:
                if before is not None:
                    raise ValueError("TLS recovery file unexpectedly removed")
            elif (_hash(current[0]), *current[1][2:5]) not in allowed:
                raise ValueError("TLS recovery refuses a foreign file change")
        for path, target in targets.items():
            fence()
            if self.store.read(path) != current_files[path]:
                raise ValueError("TLS recovery file changed during replay")
            self.store.atomic(path, *target)
        self.commit(fence)
        return {"ok": True, "status": "TLS_STAGED_RUNTIME_STOPPED", "files": len(MODES),
                "existing_ca_retained": True, "recovered": True}

    def begin(self, targets, originals, hostname):
        if self.path.exists():
            raise ValueError("TLS transaction already pending")
        _, manifest, _ = self.shared._generation()
        entries = {}
        for path, (data, uid, gid, mode) in targets.items():
            before = originals[path]
            entries[path] = dict(data=base64.b64encode(data).decode("ascii"), uid=uid, gid=gid, mode=mode,
                before=(dict(sha256=_hash(before[0]), uid=before[1][2], gid=before[1][3], mode=before[1][4])
                        if before is not None else None))
        self.record = dict(schema_version=1, state_schema=1, previous=self.update.pointer,
            generation=str(uuid.uuid4()), device_uid=manifest["device_uid"],
            hardware_serial=manifest["hardware_serial"], hostname=hostname, targets=entries)
        self._targets(self.record)
        self._save()

    def commit(self, fence):
        fence()
        targets = self._targets(self.record)
        for path, target in targets.items():
            current = self.store.read(path)
            if current is None or current[0] != target[0] or current[1][2:5] != target[1:]:
                raise ValueError("TLS recovery readback differs")
        current = self._validate_pointer()
        if current == self.record["previous"]:
            abandoned = _path(self.root, COMMON + "/state/generations/" + self.record["generation"])
            if abandoned.exists():
                self.record["generation"] = str(uuid.uuid4())
                self._save()
            self.update.stage(ENV, targets[ENV][0], 0o640)
            self.update.commit(generation=self.record["generation"])
        elif self.update.values[ENV] != targets[ENV][0]:
            raise ValueError("TLS recovery runtime differs from published generation")
        fence()
        self._clear()

    def published(self):
        if self.record is None:
            return False
        try:
            return self._current() != self.record["previous"]
        except (OSError, ValueError, KeyError, TypeError):
            return True

    def _clear(self):
        if self._read_record() != self.record:
            raise ValueError("TLS recovery record changed before completion")
        self.path.unlink()
        sync_directory(self.path.parent)

    def abort(self):
        if self.record is not None:
            if self.published():
                raise ValueError("published TLS runtime cannot roll back local files alone")
            self._clear()
