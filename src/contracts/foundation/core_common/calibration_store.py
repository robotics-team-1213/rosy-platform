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
import logging
import math
import os
import re
import socket
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "rosy.calibration.record/1"
KINDS = ("camera_profile", "wheel_odometry", "lidar_mount")
STATUSES = ("candidate", "accepted", "rejected")
DEFAULT_ROOT = "/var/lib/rosy/calibration"
_LOG = logging.getLogger(__name__)
# Plausibility at runtime and at accept (check_values). Pinky Pro numbers: the
# C1 nose sits near scan angle 180 deg; bringup seeds 0.027 m / 0.0961 m.
LIDAR_YAW_WINDOW_DEG = (150.0, 210.0)
LIDAR_YAW_TOLERANCE_DEG = 15.0
NOMINAL_WHEEL_RADIUS_M = 0.027
NOMINAL_WHEEL_SEPARATION_M = 0.0961
WHEEL_TOLERANCE = 0.10
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
        if record_id is not None and self._statuses(robot, kind).get(record_id, ("",))[0] != "accepted":
            raise ValueError("only an accepted record can be pinned")
        self._event(robot, kind, {"pin": record_id, "actor": str(actor), "note": note})

    # --- reads ---------------------------------------------------------------

    def load(self, robot, kind, record_id) -> dict:
        _check("record", record_id)
        path = self._dir(robot, kind) / "records" / f"{record_id}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict):
            raise ValueError(f"calibration record {record_id} is not an object")
        body = {k: v for k, v in record.items() if k != "sha256"}
        if record.get("sha256") != content_sha(body) or record.get("kind") != kind or record.get("robot") != robot:
            raise ValueError(f"calibration record {record_id} failed its sha256 or identity check")
        if not isinstance(record.get("values"), dict) or not isinstance(record.get("created_at"), str):
            raise ValueError(f"calibration record {record_id} lacks values or created_at")
        return {**record, "id": record_id}

    def _events(self, robot, kind):
        """Well-formed events in file order. A torn or undecodable line (power cut
        mid-append) or a malformed event is logged and skipped, never fatal."""
        path = self._dir(robot, kind) / "events.jsonl"
        if not path.is_file():
            return []
        out = []
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except ValueError:
                _LOG.warning("%s:%d: undecodable calibration event skipped", path, number)
                continue
            status_ok = (isinstance(event, dict) and isinstance(event.get("record"), str)
                         and event.get("status") in STATUSES)
            pin_ok = (isinstance(event, dict) and "pin" in event
                      and (event["pin"] is None or isinstance(event["pin"], str)))
            if not (status_ok or pin_ok):
                _LOG.warning("%s:%d: malformed calibration event skipped", path, number)
                continue
            out.append(event)
        return out

    def _statuses(self, robot, kind):
        """{record: (status, sequence number of its last status event)}."""
        status = {}
        for seq, event in enumerate(self._events(robot, kind)):
            if "status" in event:
                status[event["record"]] = (event["status"], seq)
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
            except Exception as exc:  # noqa: BLE001 - a damaged record is listed, not fatal
                out.append({"id": record_id, "status": "invalid", "error": str(exc)})
                continue
            s = status.get(record_id, ("candidate", -1))[0]
            if s == "accepted" and (current is None or current["id"] != record_id):
                s = "superseded"
            out.append({**rec, "status": s, "current": current is not None and current["id"] == record_id})
        return out

    def current(self, robot, kind):
        """The pinned accepted record, else the most recently accepted one, else None.

        "Most recently accepted" follows the order of the accept events, not
        created_at: re-accepting an older record makes it current again."""
        accepted = []
        for record_id, (s, seq) in self._statuses(robot, kind).items():
            if s != "accepted":
                continue
            try:
                accepted.append((seq, self.load(robot, kind, record_id)))
            except Exception as exc:  # noqa: BLE001 - a damaged record never becomes current
                _LOG.warning("calibration record %s/%s/%s skipped: %s", robot, kind, record_id, exc)
        if not accepted:
            return None
        pin = self._pin(robot, kind)
        for _seq, rec in accepted:
            if rec["id"] == pin:
                return {**rec, "pinned": True}
        return {**max(accepted, key=lambda item: item[0])[1], "pinned": False}


def _real(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def check_values(kind, values, *, nominal=None):
    """Why these values may not be used at runtime (None = plausible).

    lidar_mount: lidar_yaw_offset a finite real whose angle lies in
    LIDAR_YAW_WINDOW_DEG or within LIDAR_YAW_TOLERANCE_DEG of
    nominal["lidar_forward_deg"] (the hand value). wheel_odometry: radius and
    separation finite reals within WHEEL_TOLERANCE of nominal (default the
    bringup seed). camera_profile: pitch_rad and height_m finite reals in a
    physical range."""
    if not isinstance(values, dict):
        return "values are not a mapping"
    nominal = nominal or {}
    if kind == "lidar_mount":
        yaw = values.get("lidar_yaw_offset")
        if not _real(yaw):
            return "lidar_yaw_offset missing or not a finite number"
        deg = math.degrees(yaw) % 360.0
        hand = nominal.get("lidar_forward_deg")
        near_hand = _real(hand) and abs((deg - float(hand) + 180.0) % 360.0 - 180.0) <= LIDAR_YAW_TOLERANCE_DEG
        if not (LIDAR_YAW_WINDOW_DEG[0] <= deg <= LIDAR_YAW_WINDOW_DEG[1] or near_hand):
            return f"lidar_yaw_offset {deg:.1f} deg outside {LIDAR_YAW_WINDOW_DEG} and not near the hand value"
        return None
    if kind == "wheel_odometry":
        for key, default in (("wheel_radius", NOMINAL_WHEEL_RADIUS_M),
                             ("wheel_separation", NOMINAL_WHEEL_SEPARATION_M)):
            value, ref = values.get(key), float(nominal.get(key, default))
            if not _real(value):
                return f"{key} missing or not a finite number"
            if abs(value - ref) > WHEEL_TOLERANCE * ref:
                return f"{key} {value} outside {ref} +-{WHEEL_TOLERANCE:.0%}"
        return None
    if kind == "camera_profile":
        pitch, height = values.get("pitch_rad"), values.get("height_m")
        if not (_real(pitch) and _real(height)):
            return "pitch_rad/height_m missing or not finite numbers"
        if not (-0.2 <= pitch <= 0.6 and 0.02 <= height <= 0.2):
            return f"pitch_rad {pitch} or height_m {height} outside the physical range"
        return None
    return f"unknown kind {kind!r}"


def resolve(kind, fallback, *, fallback_source, robot=None, root=None, store=None, nominal=None):
    """(values, source) for a runtime consumer: the current accepted record or the fallback.

    source is a one-line string to log: which record (id, sha) or which static
    file. Any store failure, and an accepted record whose values fail
    check_values, falls back to the static values and says why."""
    try:
        store = store or CalibrationStore(root)
        rec = store.current(robot or default_robot(), kind)
    except Exception as exc:  # noqa: BLE001 - runtime must start on the static values
        _LOG.warning("calibration store unreadable for %s: %s", kind, exc)
        return dict(fallback), f"{fallback_source} (calibration store unreadable: {exc})"
    if rec is None:
        return dict(fallback), f"{fallback_source} (no accepted {kind} record)"
    why = check_values(kind, rec["values"], nominal=nominal)
    if why:
        _LOG.warning("accepted %s record %s rejected at runtime: %s", kind, rec["id"], why)
        return dict(fallback), f"{fallback_source} (accepted record {rec['id']} rejected: {why})"
    values = {**fallback, **rec["values"]}
    return values, (f"calibration record {rec['id']} sha256 {rec['sha256'][:12]}"
                    f"{' (pinned)' if rec.get('pinned') else ''}")
