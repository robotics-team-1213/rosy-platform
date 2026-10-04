"""Approved overhead-camera calibration records for markerless tracking (D-457 1).

An operator applies a D-375 lane-paint fit in the console; Fleet keeps one record per
camera source. Vision reads only its own source's record with that source's token and
uses it only to place anonymous display detections. A record is never a sighting
calibration, a CameraMap, a task input or a motion input (D-268; D-375 5 is amended
for this display path only).
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Sequence

from .sqlite_policy import configure_connection, enable_wal

REVISION_PREFIX = "paint-"
MAX_IMAGE_SIDE = 8192
_LOG = logging.getLogger(__name__)
_LENS_KEYS = ("kind", "focal_mm", "hfov_deg")


@dataclass(frozen=True)
class CalibrationRecord:
    source_id: str
    map_id: str
    calibration_revision: str
    map_to_image: tuple[float, ...]                    # 9 values, row-major: map metres -> frame pixels
    image_width: int
    image_height: int
    track_bounds_m: tuple[float, float, float, float]  # min_x, min_y, max_x, max_y
    lens: Optional[tuple[str, float, float]]           # (kind, focal_mm, hfov_deg) as Vision reported
    fit_score: float
    frame_seq: Optional[int]
    approved_by: str
    approved_at: float

    def to_dict(self) -> dict:
        min_x, min_y, max_x, max_y = self.track_bounds_m
        return {
            "source_id": self.source_id,
            "map_id": self.map_id,
            "calibration_revision": self.calibration_revision,
            "map_to_image": list(self.map_to_image),
            "image": {"width": self.image_width, "height": self.image_height},
            "track_bounds_m": {"min_x": min_x, "min_y": min_y, "max_x": max_x, "max_y": max_y},
            "lens": None if self.lens is None else dict(zip(_LENS_KEYS, self.lens)),
            "fit_score": self.fit_score,
            "frame_seq": self.frame_seq,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "use": "display-only",
        }

    @classmethod
    def from_dict(cls, row: Mapping) -> "CalibrationRecord":
        bounds = row["track_bounds_m"]
        lens = row.get("lens")
        return cls(
            source_id=row["source_id"],
            map_id=row["map_id"],
            calibration_revision=row["calibration_revision"],
            map_to_image=tuple(float(value) for value in row["map_to_image"]),
            image_width=int(row["image"]["width"]),
            image_height=int(row["image"]["height"]),
            track_bounds_m=(float(bounds["min_x"]), float(bounds["min_y"]),
                            float(bounds["max_x"]), float(bounds["max_y"])),
            lens=None if lens is None else (str(lens["kind"]), float(lens["focal_mm"]),
                                            float(lens["hfov_deg"])),
            fit_score=float(row["fit_score"]),
            frame_seq=row.get("frame_seq"),
            approved_by=row["approved_by"],
            approved_at=float(row["approved_at"]),
        )


def build_record(*, source_id: str, map_id: str, map_to_image: Sequence[float], image_width: int,
                 image_height: int, track_bounds_m: Sequence[float], lens: Optional[Mapping],
                 fit_score: float, frame_seq: Optional[int], approved_by: str,
                 approved_at: float) -> CalibrationRecord:
    """Validate one operator-approved fit and derive its revision. Raises ``ValueError``."""
    matrix = tuple(float(value) for value in map_to_image)
    if len(matrix) != 9 or not all(math.isfinite(value) for value in matrix):
        raise ValueError("map_to_image must be nine finite numbers")
    for side in (image_width, image_height):
        if type(side) is not int or not 0 < side <= MAX_IMAGE_SIDE:
            raise ValueError(f"image sides must be integers in 1..{MAX_IMAGE_SIDE}")
    bounds = tuple(float(value) for value in track_bounds_m)
    if (len(bounds) != 4 or not all(math.isfinite(value) for value in bounds)
            or bounds[0] >= bounds[2] or bounds[1] >= bounds[3]):
        raise ValueError("track bounds must be a finite non-empty rectangle")
    scale = max(abs(value) for value in matrix)
    if scale == 0.0 or abs(_det3(matrix)) / scale ** 3 < 1e-9:
        raise ValueError("map_to_image is singular")
    g, h, i = matrix[6:]
    weights = [g * x + h * y + i for x in (bounds[0], bounds[2]) for y in (bounds[1], bounds[3])]
    same_side = all(w > 0 for w in weights) or all(w < 0 for w in weights)
    if any(abs(w) <= 1e-9 for w in weights) or not same_side:
        raise ValueError("map_to_image has a horizon inside the track bounds")
    score = float(fit_score)
    if not 0.0 <= score <= 1.0:
        raise ValueError("fit_score must be in [0, 1]")
    lens_value = None if lens is None else _lens(lens)
    if frame_seq is not None and (type(frame_seq) is not int or frame_seq < 0):
        raise ValueError("frame_seq must be a non-negative integer")
    if not source_id or not map_id or not approved_by:
        raise ValueError("source, map and approver are required")
    if not math.isfinite(approved_at) or approved_at <= 0.0:
        raise ValueError("approved_at must be a positive finite time")
    revision_fields = {
        "source_id": source_id, "map_id": map_id, "map_to_image": list(matrix),
        "image": [image_width, image_height], "track_bounds_m": list(bounds),
        "lens": None if lens_value is None else list(lens_value), "approved_at": float(approved_at),
    }
    canonical = json.dumps(revision_fields, sort_keys=True, separators=(",", ":"), allow_nan=False)
    revision = REVISION_PREFIX + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
    return CalibrationRecord(source_id, map_id, revision, matrix, image_width, image_height,
                             bounds, lens_value, score, frame_seq, approved_by, float(approved_at))


def _lens(lens: Mapping) -> tuple[str, float, float]:
    try:
        kind, focal, hfov = str(lens["kind"]), float(lens["focal_mm"]), float(lens["hfov_deg"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("lens needs kind, focal_mm and hfov_deg") from exc
    if not kind or not 0.0 < focal <= 1000.0 or not 0.0 < hfov < 180.0:
        raise ValueError("lens values are out of range")
    return kind, focal, hfov


def _det3(m: Sequence[float]) -> float:
    a, b, c, d, e, f, g, h, i = m
    return a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)


class TrackingCalibrationStore:
    """One record per source: SQLite tables beside the sighting tables when ``path`` is set
    (``--sightings-db``), memory only otherwise (records are then lost on restart)."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._records: dict[str, CalibrationRecord] = {}
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            enable_wal(connection)
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS tracking_calibrations (
                    source_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tracking_calibration_audit (
                    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    calibration_revision TEXT,
                    principal_id TEXT,
                    at REAL NOT NULL
                );
                """
            )
            rows = connection.execute(
                "SELECT source_id, payload_json FROM tracking_calibrations ORDER BY source_id").fetchall()
        if os.name != "nt":
            self.path.chmod(0o600)
        for row in rows:
            try:
                stored = CalibrationRecord.from_dict(json.loads(row["payload_json"]))
                record = build_record(
                    source_id=stored.source_id, map_id=stored.map_id, map_to_image=stored.map_to_image,
                    image_width=stored.image_width, image_height=stored.image_height,
                    track_bounds_m=stored.track_bounds_m,
                    lens=None if stored.lens is None else dict(zip(_LENS_KEYS, stored.lens)),
                    fit_score=stored.fit_score, frame_seq=stored.frame_seq,
                    approved_by=stored.approved_by, approved_at=stored.approved_at)
                if record.calibration_revision != stored.calibration_revision:
                    raise ValueError("revision does not match the stored fit")
            except (ValueError, KeyError, TypeError) as exc:
                _LOG.warning("skipping unusable tracking calibration row %r: %s", row["source_id"], exc)
                continue
            self._records[record.source_id] = record

    def get(self, source_id: str) -> Optional[CalibrationRecord]:
        return self._records.get(source_id)

    def all(self) -> list[CalibrationRecord]:
        return [self._records[key] for key in sorted(self._records)]

    def put(self, record: CalibrationRecord) -> None:
        if self.path is not None:
            payload = json.dumps(record.to_dict(), separators=(",", ":"), allow_nan=False)
            with closing(self._connect()) as connection:
                with connection:
                    connection.execute(
                        """INSERT INTO tracking_calibrations(source_id, payload_json) VALUES (?, ?)
                           ON CONFLICT(source_id) DO UPDATE SET payload_json=excluded.payload_json""",
                        (record.source_id, payload),
                    )
                    connection.execute(
                        """INSERT INTO tracking_calibration_audit
                           (event, source_id, calibration_revision, principal_id, at)
                           VALUES ('calibration.approved', ?, ?, ?, ?)""",
                        (record.source_id, record.calibration_revision, record.approved_by,
                         record.approved_at),
                    )
        self._records[record.source_id] = record

    def delete(self, source_id: str, *, principal_id: str, at: float) -> bool:
        if not math.isfinite(at):
            raise ValueError("at must be finite")
        record = self._records.get(source_id)
        if record is None:
            return False
        if self.path is not None:
            with closing(self._connect()) as connection:
                with connection:
                    connection.execute("DELETE FROM tracking_calibrations WHERE source_id = ?",
                                       (source_id,))
                    connection.execute(
                        """INSERT INTO tracking_calibration_audit
                           (event, source_id, calibration_revision, principal_id, at)
                           VALUES ('calibration.revoked', ?, ?, ?, ?)""",
                        (source_id, record.calibration_revision, principal_id, at),
                    )
        del self._records[source_id]
        return True

    def audit_events(self) -> list[dict]:
        if self.path is None:
            return []
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT event, source_id, calibration_revision, principal_id, at
                   FROM tracking_calibration_audit ORDER BY audit_id"""
            ).fetchall()
        return [dict(row) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        return configure_connection(connection)
