"""Operator reference poses in an approved map; never robot state or motion inputs."""
from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
import uuid

from fleet.server.sqlite_policy import configure_connection, enable_wal


class StartPointError(ValueError):
    """Same shape as the tracking error it replaces at this boundary (D-457 5):
    start points may not name the display-only tracking modules."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class StartPointService:
    def __init__(self, *, sources, calibrations) -> None:
        self.sources = {source.source_id: source for source in sources}
        self.calibrations = calibrations
        path = calibrations.path
        self.path = path.with_name("start-points.sqlite3") if path is not None else None
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self.path) if self.path else ":memory:", check_same_thread=False)
        configure_connection(self._db)
        if self.path is not None:
            enable_wal(self._db)
        with self._db:
            self._db.execute("CREATE TABLE IF NOT EXISTS start_points (source_id TEXT PRIMARY KEY, body TEXT NOT NULL)")

    def close(self):
        with self._lock:
            self._db.close()

    def _record(self, source_id):
        source = self.sources.get(source_id)
        if source is None:
            raise StartPointError(404, "UNKNOWN_SOURCE", "no configured source with this id")
        record = self.calibrations.get(source_id)
        if record is None or record.map_id != source.map_id:
            raise StartPointError(409, "CALIBRATION_REQUIRED", "approve markerless map calibration first")
        return record

    def _view(self, row):
        try:
            record = self._record(row["source_id"])
            valid = record.map_id == row["map_id"] and record.calibration_revision == row["calibration_revision"]
        except StartPointError:
            valid = False
        return {**row, "valid": valid, "use": "reference-only"}

    def listing(self):
        with self._lock:
            rows = [json.loads(row[0]) for row in self._db.execute("SELECT body FROM start_points ORDER BY source_id")]
        return {"start_points": [self._view(row) for row in rows], "persistent": self.path is not None}

    def save(self, source_id, body, *, principal_id):
        record = self._record(source_id)
        if body["map_id"] != record.map_id:
            raise StartPointError(409, "MAP_MISMATCH", "start point must use the calibrated map")
        if body["calibration_revision"] != record.calibration_revision:
            raise StartPointError(409, "CALIBRATION_CHANGED", "read the current calibration before saving")
        x, y, yaw = (body[key] for key in ("x", "y", "yaw"))
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (x, y, yaw)):
            raise StartPointError(400, "INVALID_START_POINT", "pose must contain finite numbers")
        lo_x, lo_y, hi_x, hi_y = record.track_bounds_m
        if not lo_x <= x <= hi_x or not lo_y <= y <= hi_y:
            raise StartPointError(400, "START_POINT_OUT_OF_BOUNDS", "start point is outside the calibrated track")
        if not -math.pi <= yaw <= math.pi:
            raise StartPointError(400, "INVALID_START_POINT", "yaw must be within -pi and pi")
        row = {"source_id": source_id, "map_id": record.map_id, "calibration_revision": record.calibration_revision,
               "x": x, "y": y, "yaw": yaw, "revision": uuid.uuid4().hex,
               "saved_by": principal_id, "saved_at": time.time()}
        with self._lock, self._db:
            self._db.execute("BEGIN IMMEDIATE")
            self._expect(source_id, body.get("expected_revision"))
            self._db.execute("INSERT OR REPLACE INTO start_points VALUES (?, ?)", (source_id, json.dumps(row)))
        return self._view(row)

    def _expect(self, source_id, revision):
        previous = self._db.execute("SELECT body FROM start_points WHERE source_id=?", (source_id,)).fetchone()
        current = json.loads(previous[0])["revision"] if previous else None
        if current != revision:
            raise StartPointError(409, "START_POINT_CHANGED", "another operator changed the start point; reload first")

    def delete(self, source_id, *, expected_revision, principal_id):
        if source_id not in self.sources:
            raise StartPointError(404, "UNKNOWN_SOURCE", "no configured source with this id")
        with self._lock, self._db:
            self._db.execute("BEGIN IMMEDIATE")
            self._expect(source_id, expected_revision)
            self._db.execute("DELETE FROM start_points WHERE source_id=?", (source_id,))
        return {"deleted": True, "source_id": source_id}
