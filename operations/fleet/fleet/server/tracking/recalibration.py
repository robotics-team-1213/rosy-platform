"""Phase 4 overhead recalibration state machine: drift evaluation, shadow watch, and operator handoff."""

from __future__ import annotations

import math
import time
from typing import Any, Callable, Mapping, Optional, Sequence

from core_common.calibration_math import distort_point, undistort_point
from fleet.server.tracking_calibration import CalibrationRecord

WARN_MOVE_M = 0.015
AUTO_MAX_MOVE_M = 0.25
AUTO_MAX_ROT_DEG = 5.0
AUTO_MAX_RMS_M = 0.008
AUTO_MAX_SPREAD_M = 0.025
COOLDOWN_S = 600.0
SHADOW_BAD_POLLS = 2
SHADOW_GOOD_POLLS = 2


def matrix33(raw: Sequence) -> tuple[float, ...]:
    if len(raw) == 9 and all(not isinstance(v, (list, tuple)) for v in raw):
        rows = [float(v) for v in raw]
    else:
        rows = [float(v) for row in raw for v in row]
    if len(rows) != 9 or not all(math.isfinite(v) for v in rows):
        raise ValueError("matrix must be nine finite numbers")
    return tuple(rows)


def apply3(matrix: Sequence[float], x: float, y: float) -> Optional[tuple[float, float]]:
    a, b, c, d, e, f, g, h, i = matrix
    w = g * x + h * y + i
    if not math.isfinite(w) or abs(w) < 1e-9:
        return None
    return ((a * x + b * y + c) / w, (d * x + e * y + f) / w)


def invert3(m: Sequence[float]) -> Optional[tuple[float, ...]]:
    a, b, c, d, e, f, g, h, i = m
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if not math.isfinite(det) or abs(det) < 1e-12:
        return None
    return (
        (e * i - f * h) / det, -(b * i - c * h) / det, (b * f - c * e) / det,
        -(d * i - f * g) / det, (a * i - c * g) / det, -(a * f - c * d) / det,
        (d * h - e * g) / det, -(a * h - b * g) / det, (a * e - b * d) / det,
    )


def linear_relative(approved_i2m: Sequence[float],
                    proposal_i2m: Sequence[float]) -> Optional[tuple[tuple[float, float], ...]]:
    """``B @ inv(A)`` for the 2x2 linear parts on the map plane."""
    a = (approved_i2m[0], approved_i2m[1], approved_i2m[3], approved_i2m[4])
    det = a[0] * a[3] - a[1] * a[2]
    if not math.isfinite(det) or abs(det) < 1e-12:
        return None
    inv_a = ((a[3] / det, -a[1] / det), (-a[2] / det, a[0] / det))
    b = (proposal_i2m[0], proposal_i2m[1], proposal_i2m[3], proposal_i2m[4])
    rel = (
        (b[0] * inv_a[0][0] + b[1] * inv_a[1][0], b[0] * inv_a[0][1] + b[1] * inv_a[1][1]),
        (b[2] * inv_a[0][0] + b[3] * inv_a[1][0], b[2] * inv_a[0][1] + b[3] * inv_a[1][1]),
    )
    return rel if all(math.isfinite(v) for row in rel for v in row) else None


def evaluate_candidate_drift(
    approved: CalibrationRecord,
    candidate_m2i: Sequence[float],
    candidate_lens_profile: Optional[Mapping[str, Any]] = None,
) -> Optional[dict]:
    """Compare candidate against approved over a 3x3 grid on ``approved.track_bounds_m``."""
    cand_i2m = invert3(candidate_m2i)
    approved_i2m = invert3(approved.map_to_image)
    if cand_i2m is None or approved_i2m is None:
        return None
    min_x, min_y, max_x, max_y = approved.track_bounds_m
    mid_x, mid_y = 0.5 * (min_x + max_x), 0.5 * (min_y + max_y)
    corners = ((min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y))
    interior = ((mid_x, mid_y), (mid_x, min_y), (mid_x, max_y), (min_x, mid_y), (max_x, mid_y))
    corner_move = 0.0
    interior_move = 0.0
    for is_corner, pts in ((True, corners), (False, interior)):
        for mx, my in pts:
            px = apply3(approved.map_to_image, mx, my)
            if px is None:
                return None
            u, v = distort_point(px[0], px[1], approved.lens_profile) if approved.lens_profile else px
            if candidate_lens_profile:
                u, v = undistort_point(u, v, candidate_lens_profile)
            moved = apply3(cand_i2m, u, v)
            if moved is None:
                return None
            dist = math.hypot(moved[0] - mx, moved[1] - my)
            if is_corner:
                corner_move = max(corner_move, dist)
            else:
                interior_move = max(interior_move, dist)
    rel = linear_relative(approved_i2m, cand_i2m)
    if rel is None:
        return None
    rot = abs(math.degrees(math.atan2(rel[1][0] - rel[0][1], rel[0][0] + rel[1][1])))
    return {
        "move_m": round(max(corner_move, interior_move), 4),
        "corner_move_m": round(corner_move, 4),
        "interior_move_m": round(interior_move, 4),
        "rotation_deg": round(rot, 2),
    }


def _empty_row(source_id: str) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "state": "IDLE",
        "reason": None,
        "updated_at": None,
        "last_auto_at": None,
        "pending_candidate": None,
        "shadow": None,
        "metrics": None,
    }


class RecalibrationPipeline:
    """Tracks auto/manual recalibration candidates and post-apply shadow health verification."""

    def __init__(self, *, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._rows: dict[str, dict[str, Any]] = {}

    def _row(self, source_id: str) -> dict[str, Any]:
        row = self._rows.get(source_id)
        if row is None:
            row = _empty_row(source_id)
            self._rows[source_id] = row
        return row

    def status(self, source_id: str) -> dict[str, Any]:
        row = self._rows.get(source_id)
        return dict(row) if row is not None else _empty_row(source_id)

    def all_statuses(self) -> dict[str, dict[str, Any]]:
        return {sid: dict(row) for sid, row in self._rows.items()}

    def submit_candidate(
        self,
        source_id: str,
        candidate: Mapping[str, Any],
        *,
        approved: Optional[CalibrationRecord],
        route_active: bool = False,
        approve_fn: Optional[Callable[[dict[str, Any]], dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        now = self._clock()
        row = self._row(source_id)
        metrics = evaluate_candidate_drift(
            approved, candidate["map_to_image"], candidate.get("lens_profile")
        ) if approved is not None else None
        rms_m = float(candidate.get("rms_m", 0.0) or 0.0)
        spread_m = float(candidate.get("spread_m", 0.0) or 0.0)
        hold_reason: Optional[str] = candidate.get("hold_reason")
        if row["state"] == "ROLLED_BACK":
            hold_reason = hold_reason or "rolled_back_awaiting_operator"
        elif approved is not None and approved.frozen:
            hold_reason = hold_reason or "calibration_frozen"
        elif route_active:
            hold_reason = hold_reason or "active_trips"
        elif rms_m > AUTO_MAX_RMS_M:
            hold_reason = hold_reason or "rms_exceeds_auto_cap"
        elif spread_m > AUTO_MAX_SPREAD_M:
            hold_reason = hold_reason or "spread_exceeds_auto_cap"
        elif metrics is None and approved is not None:
            hold_reason = hold_reason or "incomparable_candidate"
        elif metrics is not None and (metrics["move_m"] > AUTO_MAX_MOVE_M or metrics["rotation_deg"] > AUTO_MAX_ROT_DEG):
            hold_reason = hold_reason or "drift_exceeds_auto_cap"
        elif row["last_auto_at"] is not None and (now - row["last_auto_at"]) < COOLDOWN_S:
            hold_reason = hold_reason or "cooldown"

        cand_payload = {
            "source_id": source_id,
            "map_id": candidate.get("map_id"),
            "map_to_image": list(candidate["map_to_image"]),
            "image": dict(candidate["image"]),
            "track_bounds_m": dict(candidate["track_bounds_m"]),
            "fit_score": float(candidate["fit_score"]),
            "lens": dict(candidate["lens"]) if candidate.get("lens") else None,
            "frame_seq": candidate.get("frame_seq"),
            "lens_profile": dict(candidate["lens_profile"]) if candidate.get("lens_profile") else None,
            "metrics": {**(metrics or {}), "rms_m": round(rms_m, 5), "spread_m": round(spread_m, 5)},
        }

        if hold_reason is None and approve_fn is not None:
            applied = approve_fn({**cand_payload, "auto": True, "method": "auto_recal"})
            row["state"] = "AUTO_APPLIED"
            row["reason"] = "auto_applied"
            row["updated_at"] = now
            row["last_auto_at"] = now
            row["pending_candidate"] = None
            row["metrics"] = cand_payload["metrics"]
            row["shadow"] = {
                "applied_revision": applied["calibration_revision"],
                "prev_revision": approved.calibration_revision if approved is not None else None,
                "pre_move_m": (metrics or {}).get("move_m"),
                "bad_streak": 0,
                "good_streak": 0,
            }
            return {"action": "auto_applied", "record": applied, **dict(row)}

        if row["state"] != "ROLLED_BACK":
            row["state"] = "NEEDS_OPERATOR"
        row["reason"] = hold_reason or "operator_review"
        row["updated_at"] = now
        row["metrics"] = cand_payload["metrics"]
        row["pending_candidate"] = {**cand_payload, "reason": row["reason"], "submitted_at": now}
        return {"action": "held", **dict(row)}

    def observe_health(
        self,
        source_id: str,
        *,
        health_state: str,
        move_m: Optional[float],
        current_revision: Optional[str],
        rollback_fn: Optional[Callable[[str, str], dict[str, Any]]] = None,
    ) -> Optional[dict[str, Any]]:
        row = self._rows.get(source_id)
        shadow = row.get("shadow") if row is not None else None
        if not shadow or shadow.get("applied_revision") != current_revision:
            return None
        now = self._clock()
        if health_state in ("drifting", "mismatch"):
            shadow["bad_streak"] = int(shadow.get("bad_streak", 0)) + 1
            shadow["good_streak"] = 0
            if shadow["bad_streak"] >= SHADOW_BAD_POLLS and shadow.get("prev_revision") and rollback_fn is not None:
                prev_rev = str(shadow["prev_revision"])
                restored = rollback_fn(source_id, prev_rev)
                row["state"] = "ROLLED_BACK"
                row["reason"] = "shadow_health_regression"
                row["updated_at"] = now
                row["shadow"] = None
                row["metrics"] = {"rolled_back_from": current_revision, "restored_revision": restored.get("calibration_revision"), "move_m": move_m}
                return restored
        elif health_state == "fresh":
            shadow["good_streak"] = int(shadow.get("good_streak", 0)) + 1
            shadow["bad_streak"] = 0
            if shadow["good_streak"] >= SHADOW_GOOD_POLLS:
                row["state"] = "IDLE"
                row["reason"] = "shadow_verified"
                row["updated_at"] = now
                row["shadow"] = None
        return None

    def accept_pending(
        self,
        source_id: str,
        *,
        approved_by: str,
        approve_fn: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        row = self._rows.get(source_id)
        pending = row.get("pending_candidate") if row is not None else None
        if not pending:
            raise LookupError("no pending recalibration candidate")
        payload = {k: v for k, v in pending.items() if k not in ("reason", "submitted_at")}
        applied = approve_fn({**payload, "auto": False, "method": "recal_approved"})
        now = self._clock()
        row["state"] = "IDLE"
        row["reason"] = f"accepted_by:{approved_by}"
        row["updated_at"] = now
        row["pending_candidate"] = None
        row["shadow"] = None
        return {"record": applied, "recalibration": dict(row)}

    def dismiss_pending(self, source_id: str, *, principal_id: str) -> dict[str, Any]:
        row = self._row(source_id)
        row["state"] = "IDLE"
        row["reason"] = f"dismissed_by:{principal_id}"
        row["updated_at"] = self._clock()
        row["pending_candidate"] = None
        return dict(row)
