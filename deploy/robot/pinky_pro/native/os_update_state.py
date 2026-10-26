"""Durable boot-bound OS transaction journal; firmware/health authority stays with its owners."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat

from media_layout import validate_layout
from os_state_io import _json_atomic
from os_state_layout import COMMON, _guid, _layout, _object, _path, _read, mount_facts
from os_update_manifest import _digest, _fields, release_id, validate_metadata

DIRECTORY = COMMON + "/os-update"
STATE = DIRECTORY + "/state.json"
PHASES = ("PREPARED", "INSTALLING", "INSTALLED", "VERIFIED", "ARMED", "TRIAL", "HEALTHY", "COMMIT_INTENT")
PENDING_FIELDS = {"transaction_id", "source_boot_id", "trial_boot_id", "source_slot", "target_slot",
                  "phase", "verified", "layout_sha256", "health_sha256"}


def _slot(value):
    if value not in ("a", "b"):
        raise ValueError("invalid OS slot")


def _verification(value):
    _fields(value, {"metadata", "manifest_sha256", "images"})
    metadata = validate_metadata(value["metadata"])
    _digest(value["manifest_sha256"])
    _fields(value["images"], {"rootfs", "boot"})
    for role, filename, field in (("rootfs", "rootfs.ext4", "rootfs_bytes"), ("boot", "boot.vfat", "boot_bytes")):
        image = value["images"][role]
        _fields(image, {"filename", "sha256", "size"})
        if image["filename"] != filename or type(image["size"]) is not int or image["size"] != metadata[field]:
            raise ValueError("OS image verification differs from metadata")
        _digest(image["sha256"])


def _validate(value):
    _fields(value, {"schema_version", "committed", "pending", "failed_versions"})
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("unsupported OS update state schema")
    committed = value["committed"]
    _fields(committed, {"slot", "release_id"})
    _slot(committed["slot"])
    release_id(committed["release_id"])
    failed = value["failed_versions"]
    if not isinstance(failed, list) or len(failed) > 128:
        raise ValueError("invalid failed OS version history")
    for version in failed:
        release_id(version)
    if len(set(failed)) != len(failed):
        raise ValueError("duplicate failed OS version")
    pending = value["pending"]
    if pending is None:
        return value
    _fields(pending, PENDING_FIELDS)
    for key in ("transaction_id", "source_boot_id"):
        _guid(pending[key])
    _slot(pending["source_slot"])
    _slot(pending["target_slot"])
    _digest(pending["layout_sha256"])
    _verification(pending["verified"])
    version = pending["verified"]["metadata"]["release_id"]
    if (pending["phase"] not in PHASES or pending["source_slot"] != committed["slot"]
            or pending["target_slot"] == pending["source_slot"] or version <= committed["release_id"] or version in failed):
        raise ValueError("OS transaction conflicts with committed state")
    trial = pending["phase"] in ("TRIAL", "HEALTHY", "COMMIT_INTENT")
    if trial:
        _guid(pending["trial_boot_id"])
        if pending["trial_boot_id"] == pending["source_boot_id"]:
            raise ValueError("trial requires a new boot")
    elif pending["trial_boot_id"] is not None:
        raise ValueError("trial evidence before trial")
    if pending["phase"] in ("HEALTHY", "COMMIT_INTENT"):
        _digest(pending["health_sha256"])
    elif pending["health_sha256"] is not None:
        raise ValueError("health evidence before health")
    return value


def _directory(root):
    admitted = _layout(root)
    if admitted is None or admitted[0]["schema_version"] != 2:
        raise ValueError("automatic OS transactions require boot protocol 2")
    mount_facts(root, admitted[0])
    directory = _path(root, DIRECTORY)
    info = directory.stat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError("OS update store must already be private")
    return directory


def _load(root):
    _directory(root)
    path = _path(root, STATE)
    info = path.stat()
    if info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600:
        raise ValueError("OS state must be a private single-link file")
    value = _object(_read(path, 65536, root.stat().st_uid), {"schema_version", "committed", "pending", "failed_versions"})
    return _validate(value)


def read_state(root: Path = Path("/")) -> dict:
    """Missing or damaged state holds; only the factory initializer creates an idle store."""
    try:
        return _load(Path(root).absolute())
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
        raise ValueError(f"OS_UPDATE_STATE_HOLD: {exc}") from exc


class _Store:
    def __init__(self, root, state):
        self.root, self._state = root, state
        self._active = True

    @property
    def state(self):
        return deepcopy(self._state)

    def _save(self, value):
        if not self._active:
            raise ValueError("OS_UPDATE_STATE_HOLD: state lock is no longer held by a usable writer")
        _validate(value)
        try:
            _json_atomic(_path(self.root, STATE), value, 0o600)
        except BaseException:
            # A failed parent fsync may follow a successful rename; reopen rather than reuse stale state.
            self._active = False
            raise
        self._state = deepcopy(value)

    def begin(self, verified, media, boot_id, transaction_id):
        value = self.state
        _verification(verified)
        _guid(boot_id)
        _guid(transaction_id)
        current = _layout(self.root)[0]["slot"]
        layout = validate_layout(media["layout"])
        version = verified["metadata"]["release_id"]
        if (value["pending"] is not None or media["slot"] != current or current != value["committed"]["slot"]
                or layout["provision_role"] != "bootstrap" or version <= value["committed"]["release_id"]
                or version in value["failed_versions"]):
            raise ValueError("OS transaction is not a new committed-slot update")
        digest = hashlib.sha256(json.dumps(layout, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        value["pending"] = dict(transaction_id=transaction_id, source_boot_id=boot_id, trial_boot_id=None,
            source_slot=current, target_slot="b" if current == "a" else "a", phase="PREPARED",
            verified=deepcopy(verified), layout_sha256=digest, health_sha256=None)
        self._save(value)

    def _pending(self, transaction_id):
        pending = self._state["pending"]
        if pending is None or transaction_id != pending["transaction_id"]:
            raise ValueError("stale OS transaction owner")
        return deepcopy(pending)

    def transition(self, transaction_id, phase, boot_id, *, health_sha256=None):
        pending = self._pending(transaction_id)
        _guid(boot_id)
        if phase not in PHASES or PHASES.index(phase) not in (PHASES.index(pending["phase"]), PHASES.index(pending["phase"]) + 1):
            raise ValueError("OS transaction phase skip or reversal")
        if phase in ("TRIAL", "HEALTHY", "COMMIT_INTENT"):
            if boot_id == pending["source_boot_id"] or (pending["trial_boot_id"] is not None and boot_id != pending["trial_boot_id"]):
                raise ValueError("OS trial boot differs")
            pending["trial_boot_id"] = boot_id
        elif boot_id != pending["source_boot_id"]:
            raise ValueError("OS install source boot differs")
        if phase == "HEALTHY":
            _digest(health_sha256)
            if pending["health_sha256"] not in (None, health_sha256):
                raise ValueError("OS health evidence changed")
            pending["health_sha256"] = health_sha256
        elif health_sha256 is not None:
            raise ValueError("health evidence supplied for the wrong phase")
        pending["phase"] = phase
        self._save(dict(self.state, pending=pending))

    def commit(self, transaction_id, boot_id):
        """Commit owner calls only after durable intent, firmware write/readback and matching GOOD_ACK."""
        pending = self._pending(transaction_id)
        if pending["phase"] != "COMMIT_INTENT" or boot_id != pending["trial_boot_id"]:
            raise ValueError("OS commit lacks same-trial intent")
        self._save(dict(self.state, committed=dict(slot=pending["target_slot"],
            release_id=pending["verified"]["metadata"]["release_id"]), pending=None))

    def record_failure(self, transaction_id, boot_id, current_slot):
        """Fallback owner calls after observing normal firmware boot on the preserved source."""
        pending = self._pending(transaction_id)
        _guid(boot_id)
        if (current_slot != pending["source_slot"] or _layout(self.root)[0]["slot"] != current_slot
                or boot_id == pending["trial_boot_id"] or pending["phase"] == "COMMIT_INTENT"):
            raise ValueError("OS failure requires source boot or commit-owner reconciliation")
        failed = [*self._state["failed_versions"], pending["verified"]["metadata"]["release_id"]]
        self._save(dict(self.state, pending=None, failed_versions=failed))


@contextmanager
def locked(root: Path = Path("/")):
    """Short state lock only: release before daemon calls or CORE restarts."""
    root = Path(root).absolute()
    try:
        _directory(root)
        path = _path(root, DIRECTORY + "/state.lock")
        with os.fdopen(os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600), "rb") as handle:
            info = os.fstat(handle.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != root.stat().st_uid
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
                raise ValueError("unsafe OS state lock")
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError("OS state lock is busy") from exc
            store = _Store(root, _load(root))
            try:
                yield store
            finally:
                store._active = False
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
        raise ValueError(f"OS_UPDATE_STATE_HOLD: {exc}") from exc
