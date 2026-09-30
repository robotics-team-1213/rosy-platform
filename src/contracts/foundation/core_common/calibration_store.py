"""Versioned calibration store: immutable records, append-only status, latest accepted wins.

D-47 addendum (2026-10-01). One store per robot, stdlib only, shared by CORE,
the sensing nodes, bringup and the PC tools:

  <root>/<robot>/<kind>/records/<created>_<sha12>.json   one immutable record per run
  <root>/<robot>/<kind>/events.jsonl                     append-only status and pin events

A record holds kind, robot, created_at, source sessions, method version, the
fitted values with their intervals, and the sha256 of that content. Its
status is not stored in it: it is the last status event for it (candidate
until one exists). ``current`` resolves to the pinned record when a pin is
set and that record is still accepted, else to the newest accepted record.
An accepted record that is not current reads as "superseded". Nothing is
ever overwritten or deleted; a rollback is a pin to an earlier accepted
record (or a reject of the newest). Accepting is an operator action: no code
path here accepts on its own.

Runtime consumers call ``resolve``: the current record's values, or the
static fallback (robot.yaml, camera_nominal.yaml, rosy_params.yaml, ...) when
there is none, together with a source line to log.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "rosy.calibration.record/1"
KINDS = ("camera_profile", "wheel_odometry", "lidar_mount")
STATUSES = ("candidate", "accepted", "rejected")
DEFAULT_ROOT = "/var/lib/rosy/calibration"
_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def default_root() -> Path:
    return Path(os.environ.get("ROSY_CALIBRATION_ROOT", DEFAULT_ROOT))


def default_robot() -> str:
    """The device name recordings use (session.json "device"): the hostname."""
    return os.environ.get("ROSY_CALIBRATION_ROBOT") or socket.gethostname()


def _check(name, value):
    if not isinstance(value, str) or not _SAFE.match(value):
        raise ValueError(f"invalid {name}: {value!r}")


def content_sha(body: dict) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class CalibrationStore:
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else default_root()

    def _dir(self, robot, kind):
        _check("robot", robot)
        if kind not in KINDS:
            raise ValueError(f"unknown calibration kind {kind!r}")
        return self.root / robot / kind

    # --- writes: never overwrite -------------------------------------------

    def add(self, robot, kind, values, *, sessions=(), method, intervals=None, created_at=None,
            extra=None) -> str:
        """Store one run's result as a new candidate record; returns its id."""
        if not isinstance(values, dict) or not values:
            raise ValueError("calibration values must be a non-empty mapping")
        body = {"schema": SCHEMA, "kind": kind, "robot": robot, "created_at": created_at or _now(),
                "sessions": list(sessions), "method": str(method), "values": values,
                "intervals": intervals or {}, "extra": extra or {}}
        sha = content_sha(body)
        folder = self._dir(robot, kind) / "records"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = re.sub(r"[^0-9A-Za-z]", "", body["created_at"])[:20]
        record_id = f"{stamp}_{sha[:12]}"
        path = folder / f"{record_id}.json"
        # O_EXCL: an existing record is never replaced, even with equal content.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({**body, "sha256": sha}, stream, indent=1, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        return record_id

    def _event(self, robot, kind, event):
        folder = self._dir(robot, kind)
        folder.mkdir(parents=True, exist_ok=True)
        with open(folder / "events.jsonl", "a", encoding="utf-8") as stream:
            stream.write(json.dumps({"at": _now(), **event}, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def set_status(self, robot, kind, record_id, status, *, actor, note=""):
        """Accept or reject a record (an operator action)."""
        if status not in ("accepted", "rejected"):
            raise ValueError("status must be accepted or rejected")
        if not str(actor).strip():
            raise ValueError("a status change needs an actor")
        self.load(robot, kind, record_id)  # must exist and verify
        self._event(robot, kind, {"record": record_id, "status": status, "actor": str(actor), "note": note})

    def pin(self, robot, kind, record_id, *, actor, note=""):
        """Pin current to one accepted record (rollback), or None to follow the newest accepted."""
        if record_id is not None and self._statuses(robot, kind).get(record_id) != "accepted":
            raise ValueError("only an accepted record can be pinned")
        self._event(robot, kind, {"pin": record_id, "actor": str(actor), "note": note})

    # --- reads ---------------------------------------------------------------

    def load(self, robot, kind, record_id) -> dict:
        _check("record", record_id)
        path = self._dir(robot, kind) / "records" / f"{record_id}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        body = {k: v for k, v in record.items() if k != "sha256"}
        if record.get("sha256") != content_sha(body) or record.get("kind") != kind or record.get("robot") != robot:
            raise ValueError(f"calibration record {record_id} failed its sha256 or identity check")
        return {**record, "id": record_id}

    def _events(self, robot, kind):
        path = self._dir(robot, kind) / "events.jsonl"
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _statuses(self, robot, kind):
        status = {}
        for event in self._events(robot, kind):
            if "status" in event:
                status[event["record"]] = event["status"]
        return status

    def _pin(self, robot, kind):
        pin = None
        for event in self._events(robot, kind):
            if "pin" in event:
                pin = event["pin"]
        return pin

    def records(self, robot, kind):
        """Every record, oldest first, with its derived status and whether it is current."""
        folder = self._dir(robot, kind) / "records"
        ids = sorted(p.stem for p in folder.glob("*.json")) if folder.is_dir() else []
        status = self._statuses(robot, kind)
        current = self.current(robot, kind)
        out = []
        for record_id in ids:
            try:
                rec = self.load(robot, kind, record_id)
            except (OSError, ValueError) as exc:
                out.append({"id": record_id, "status": "invalid", "error": str(exc)})
                continue
            s = status.get(record_id, "candidate")
            if s == "accepted" and (current is None or current["id"] != record_id):
                s = "superseded"
            out.append({**rec, "status": s, "current": current is not None and current["id"] == record_id})
        return out

    def current(self, robot, kind):
        """The pinned accepted record, else the newest accepted one, else None."""
        status = self._statuses(robot, kind)
        accepted = []
        for record_id, s in status.items():
            if s != "accepted":
                continue
            try:
                accepted.append(self.load(robot, kind, record_id))
            except (OSError, ValueError):
                continue  # a damaged record never becomes current
        if not accepted:
            return None
        pin = self._pin(robot, kind)
        for rec in accepted:
            if rec["id"] == pin:
                return {**rec, "pinned": True}
        return {**max(accepted, key=lambda r: (r["created_at"], r["id"])), "pinned": False}


def resolve(kind, fallback, *, fallback_source, robot=None, root=None, store=None):
    """(values, source) for a runtime consumer: the current accepted record or the fallback.

    source is a one-line string to log: which record (id, sha) or which static file."""
    try:
        store = store or CalibrationStore(root)
        rec = store.current(robot or default_robot(), kind)
    except (OSError, ValueError) as exc:
        return dict(fallback), f"{fallback_source} (calibration store unreadable: {exc})"
    if rec is None:
        return dict(fallback), f"{fallback_source} (no accepted {kind} record)"
    values = {**fallback, **rec["values"]}
    return values, (f"calibration record {rec['id']} sha256 {rec['sha256'][:12]}"
                    f"{' (pinned)' if rec.get('pinned') else ''}")
