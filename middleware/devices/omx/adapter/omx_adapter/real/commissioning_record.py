"""D-858 S3 commissioning record per OMX arm instance, and the only source of ``MotionEvidence``.

One JSON file per ``workcell_id/instance_id`` holds the bench measurements: joint limits,
gripper open/close, FK workspace box, stop test. Each item keeps who measured it (a name) and
when. Saves are atomic (temp file, fsync, rename); every save appends the whole new record to a
JSON Lines history, so each earlier revision stays readable. The revision is the SHA-256 of the
canonical record, never a stored field, so it cannot disagree with the content.

Absorbed from rosy-vault 9a744a3 ``device_core/calibration.py`` (V-011). Value checks reuse the
D-496 validators of ``hardware_profile.py``; that module still only validates documents and
never configures hardware. Commissioning owns this store; the port only reads its revision.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from .dynamixel_gates import MotionEvidence
from ..hardware_profile import _fields, _number, _range

SCHEMA = "rosy.omx-commissioning-record.v1"
ITEMS = ("joint_limits", "gripper", "workspace", "stop_test")
_STOP_FIELDS = ("joint measured_stop_ms joint1_deviation_rad joint1_velocity_rad_s "
                "pre_stop_velocity_rad_s passed driver config_revision")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


def revision_of(record: Mapping[str, object] | None) -> str | None:
    if record is None:
        return None
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 128:
        raise ValueError(f"{label}: expected a non-empty trimmed string")
    return value


def _check_value(name: str, value: object, joint_names: list[str]) -> None:
    if name == "joint_limits":
        _fields(value, " ".join(joint_names), name)
        for joint in joint_names:
            _range(value[joint], f"joint_limits.{joint}")
    elif name == "gripper":
        _fields(value, "open_rad close_rad", name)
        if _number(value["open_rad"], "gripper.open_rad") == _number(value["close_rad"], "gripper.close_rad"):
            raise ValueError("gripper: open and close must differ")
    elif name == "workspace":
        if not isinstance(value, list) or len(value) != 3:
            raise ValueError("workspace: expected [[x_min, x_max], [y_min, y_max], [z_min, z_max]] m")
        for axis, pair in zip("xyz", value):
            _range(pair, f"workspace.{axis}")
    elif name == "stop_test":
        _fields(value, _STOP_FIELDS, name)
        for key in ("measured_stop_ms", "joint1_deviation_rad", "joint1_velocity_rad_s",
                    "pre_stop_velocity_rad_s"):
            _number(value[key], f"stop_test.{key}")
        if type(value["passed"]) is not bool or value["joint"] != "joint1":
            raise ValueError("stop_test: expected boolean passed on joint1")
        _text(value["driver"], "stop_test.driver")
        _text(value["config_revision"], "stop_test.config_revision")
    else:
        raise ValueError(f"unknown commissioning item {name!r}; expected one of {ITEMS}")


def check_record(record: object) -> dict:
    _fields(record, "schema workcell_id instance_id joint_names items", "record")
    if record["schema"] != SCHEMA:
        raise ValueError(f"record: expected schema {SCHEMA}")
    for key in ("workcell_id", "instance_id"):
        _text(record[key], f"record.{key}")
    names = record["joint_names"]
    if (not isinstance(names, list) or not names or len(set(names)) != len(names)
            or not all(isinstance(n, str) and n.strip() for n in names)):
        raise ValueError("record.joint_names: expected unique joint names")
    if not isinstance(record["items"], dict):
        raise ValueError("record.items: expected a mapping")
    for name, item in record["items"].items():
        _fields(item, "value measured_at measured_by config_revision", f"items.{name}")
        _text(item["config_revision"], f"items.{name}.config_revision")
        _check_value(name, item["value"], names)
        datetime.fromisoformat(_text(item["measured_at"], f"items.{name}.measured_at"))
        _text(item["measured_by"], f"items.{name}.measured_by")
    return record


class CommissioningStore:
    """One arm instance's record file under ``root/<workcell_id>/<instance_id>.json``."""

    def __init__(self, root: Path | str, *, workcell_id: str, instance_id: str) -> None:
        for value in (workcell_id, instance_id):
            if not isinstance(value, str) or not _ID.fullmatch(value):
                raise ValueError("workcell_id/instance_id must be plain names (no path parts)")
        self.workcell_id, self.instance_id = workcell_id, instance_id
        self.path = Path(root) / workcell_id / f"{instance_id}.json"
        self.history_path = self.path.with_name(f"{instance_id}.history.jsonl")

    def read(self) -> dict | None:
        """The record, or None before the first save. A damaged file raises (fail closed)."""
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        record = check_record(json.loads(text))
        if (record["workcell_id"], record["instance_id"]) != (self.workcell_id, self.instance_id):
            raise ValueError("record belongs to another arm instance")
        return record

    def revision(self) -> str | None:
        return revision_of(self.read())

    def history(self) -> list[dict]:
        try:
            lines = self.history_path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        return [json.loads(line) for line in lines if line.strip()]

    def save(self, changes: Mapping[str, object], *, by: str, config_revision: str,
             joint_names: list[str] | tuple[str, ...], expected_revision: str | None,
             now: datetime | None = None) -> str:
        """Merge measured items, check the whole record, write it atomically. Returns the new
        revision. ``expected_revision`` is the revision the caller read (None before the first
        save); a record saved in between is refused rather than overwritten."""
        by = _text(by, "measured_by (who measured)")
        if not changes or not set(changes) <= set(ITEMS):
            raise ValueError(f"changes: expected some of {ITEMS}")
        # shortcut: read-compare-write without a cross-process lock; one commissioning
        # operator per arm at a time. Add a lock file if two consoles ever save the same arm.
        old = self.read()
        old_revision = revision_of(old)
        if old_revision != expected_revision:
            raise ValueError("record changed since it was read; reload and measure again")
        record = old or {"schema": SCHEMA, "workcell_id": self.workcell_id,
                         "instance_id": self.instance_id, "joint_names": list(joint_names),
                         "items": {}}
        if record["joint_names"] != list(joint_names):
            raise ValueError("joint names differ from the arm's record")
        stamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
        record = json.loads(json.dumps(record))  # private copy; tuples become lists
        for name, value in changes.items():
            # Each item keeps the config revision it was measured under (S3 review M1): a later
            # save under another revision never relabels earlier measurements.
            record["items"][name] = {"value": json.loads(json.dumps(value, allow_nan=False)),
                                     "measured_at": stamp, "measured_by": by,
                                     "config_revision": _text(config_revision, "config_revision")}
        check_record(record)
        revision = revision_of(record)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(self.path, json.dumps(record, indent=2, sort_keys=True) + "\n")
        entry = {"revision": revision, "previous_revision": old_revision, "at": stamp, "by": by,
                 "changed": sorted(changes), "record": record}
        with self.history_path.open("a", encoding="utf-8") as history:
            history.write(json.dumps(entry, sort_keys=True) + "\n")
            history.flush()
            os.fsync(history.fileno())
        return revision


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    if hasattr(os, "O_DIRECTORY"):  # POSIX: make the rename itself durable
        dir_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)


def _evidence(record: dict | None, refusals: list[str]) -> MotionEvidence:
    if record is None:
        return MotionEvidence(refusals=tuple(refusals) or ("no commissioning record for this arm",))
    items = record["items"]
    # A missing stop test is the gate's own "no stop test record"; measurement mode runs without it.
    missing = [name for name in ITEMS if name not in items and name != "stop_test"]
    if missing:
        refusals.append("commissioning record missing: " + ", ".join(missing))
    revisions = {item["config_revision"] for item in items.values()}
    if len(revisions) > 1:
        refusals.append("items measured under different config revisions: " + ", ".join(
            f"{name}={item['config_revision']}" for name, item in sorted(items.items())))
    grip = items.get("gripper", {}).get("value", {})
    workspace = items.get("workspace", {}).get("value")
    return MotionEvidence(
        limits_measured="joint_limits" in items, gripper_open_rad=grip.get("open_rad"),
        gripper_close_rad=grip.get("close_rad"), stop_test=items.get("stop_test", {}).get("value"),
        workspace_m=tuple(tuple(pair) for pair in workspace) if workspace else None,
        config_revision=revisions.pop() if len(revisions) == 1 else None, revision=revision_of(record),
        refusals=tuple(refusals))


def load_motion_evidence(store: CommissioningStore, config) -> MotionEvidence:
    """Gate evidence for the port that runs ``config`` (an ``ArmCommandConfig``). Every gap is an
    explicit refusal: no record, missing items, a record of another config revision or joint
    set, owner limits wider than the measured ones. Stop-test V-016 bounds are in the gate."""
    try:
        record = store.read()
    except (OSError, ValueError, TypeError) as exc:
        return MotionEvidence(refusals=(f"commissioning record unreadable: {type(exc).__name__}: {exc}"[:300],))
    refusals: list[str] = []
    if record is not None:
        stale = sorted(name for name, item in record["items"].items()
                       if item["config_revision"] != config.calibration_revision)
        if stale:
            refusals.append(f"items not measured under port config revision "
                            f"{config.calibration_revision!r}: {', '.join(stale)}")
        if not config.enabled:
            refusals.append("owner config is not enabled")
        elif tuple(record["joint_names"]) != tuple(config.joint_names):
            refusals.append("record joint names differ from the owner config")
        elif "joint_limits" in record["items"]:
            measured = record["items"]["joint_limits"]["value"]
            for name in config.joint_names:
                lower, upper = config.position_limits[name]
                low, high = measured[name]
                if lower < low or upper > high:
                    refusals.append(f"owner limit {name} [{lower}, {upper}] exceeds measured [{low}, {high}]")
    return _evidence(record, refusals)


def gate_status(store: CommissioningStore) -> dict:
    """Read-only per-arm gate view for the commissioning screen: which items are present, who
    measured them when, what still blocks. The owner-config binding is checked by the port."""
    try:
        record = store.read()
    except (OSError, ValueError, TypeError) as exc:
        return {"revision": None, "items": {}, "blockers": [f"commissioning record unreadable: {type(exc).__name__}"]}
    items = (record or {}).get("items", {})
    return {"revision": revision_of(record),
            "items": {name: ({key: items[name][key] for key in
                              ("measured_at", "measured_by", "config_revision")} if name in items else None)
                      for name in ITEMS},
            "stop_test": items.get("stop_test", {}).get("value"),
            "blockers": _evidence(record, []).blockers()}
