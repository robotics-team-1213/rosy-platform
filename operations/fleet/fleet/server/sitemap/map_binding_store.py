"""D-1022: approved robot map -> site frame bindings, one active row per robot, history kept.

A binding names the grid the robot actually loaded (CORE ``map_grid_id``) and the site map version it was
fitted against. Fleet refits from the submitted pairs itself; the client's numbers are never stored. A new
approval supersedes the robot's previous one; revocation keeps the row. Nothing here moves a robot.
"""

from __future__ import annotations

import json
import math
import sqlite3
import threading
import uuid
from typing import Callable, Mapping, Optional

from fleet.localization.map_binding import BindingError, Fit, judge

MAX_POINTS = 32


def _points(raw, field: str) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    if not isinstance(raw, list) or len(raw) > MAX_POINTS:
        raise BindingError("BAD_POINTS", f"{field} must be a list of at most {MAX_POINTS} pairs")
    out = []
    for item in raw:
        try:
            site, robot = item["site"], item["robot"]
            pair = ((float(robot[0]), float(robot[1])), (float(site[0]), float(site[1])))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise BindingError("BAD_POINTS", f"{field} items are {{site: [x, y], robot: [x, y]}}") from exc
        if not all(math.isfinite(v) for p in pair for v in p):
            raise BindingError("BAD_POINTS", f"{field} values must be finite")
        out.append(pair)
    if len({r for r, _ in out}) < len(out) or len({s for _, s in out}) < len(out):  # robot == site is a real pair
        raise BindingError("BAD_POINTS", f"{field} repeats a point")
    return out


def _localized(state: Mapping) -> tuple[str, str]:
    """(map_id, map_grid_id) of a robot LOCALIZED in its map frame on a loaded grid, else BindingError."""
    loc = state.get("localization") or {}
    if loc.get("state") != "LOCALIZED" or loc.get("pose_frame") != "map":
        raise BindingError("ROBOT_NOT_LOCALIZED", "the robot must be LOCALIZED in its map frame")
    grid = state.get("map_grid_id")
    if not isinstance(grid, str) or not grid.startswith("occupancy:"):
        raise BindingError("NO_GRID_ID", "the robot does not report the grid it loaded (map_grid_id)")
    return str(state.get("map_id") or grid), grid


def _site_matches(binding: Mapping, site: Optional[tuple[str, int]],
                  frame_for_version: Optional[Callable[[int], Optional[str]]] = None) -> bool:
    if site is None or binding["site_map_id"] != site[0]:
        return False
    if binding["site_map_version"] == int(site[1]):
        return True
    if frame_for_version is None:
        return False
    bound_frame = binding.get("site_frame_sha256") or frame_for_version(int(binding["site_map_version"]))
    cur_frame = frame_for_version(int(site[1]))
    return bool(bound_frame and cur_frame and bound_frame == cur_frame)


class MapBindingStore:
    def __init__(self, db: sqlite3.Connection, lock: threading.RLock, clock: Callable[[], float],
                 event: Callable[[str, str, dict], None],
                 frame_for_version: Optional[Callable[[int], Optional[str]]] = None) -> None:
        self._db, self._lock, self._clock, self._event = db, lock, clock, event
        self._frame_for_version = frame_for_version
        self.auto_notes: dict[str, dict] = {}  # robot id -> last auto-rebind attempt (map_binding_auto)
        with self._lock, self._db:
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS robot_map_bindings (
                    binding_id TEXT PRIMARY KEY, robot_id TEXT NOT NULL, robot_map_id TEXT NOT NULL,
                    robot_grid_id TEXT NOT NULL, site_map_id TEXT NOT NULL, site_map_version INTEGER NOT NULL,
                    fit TEXT NOT NULL, approved_by TEXT NOT NULL, approved_at REAL NOT NULL,
                    revoked_by TEXT, revoked_at REAL, revoke_reason TEXT, site_frame_sha256 TEXT, grid_sig TEXT)""")
            columns = {row[1] for row in self._db.execute("PRAGMA table_info(robot_map_bindings)")}
            for column in ("site_frame_sha256", "grid_sig"):
                if column not in columns:
                    self._db.execute(f"ALTER TABLE robot_map_bindings ADD COLUMN {column} TEXT")

    def approve(self, robot_id: str, state: Mapping, site: tuple[str, int], pairs, holdout,
                principal_id: str, grid_sig: Optional[dict] = None) -> dict:  # grid_sig: map_binding.grid_signature
        robot_map_id, grid = _localized(state)
        pairs, holdout = _points(pairs, "pairs"), _points(holdout, "holdout")
        if ({r for r, _ in pairs} & {r for r, _ in holdout}) or ({s for _, s in pairs} & {s for _, s in holdout}):
            raise BindingError("BAD_POINTS", "a holdout point repeats a fit point; measure it separately")
        fit, errors = judge([p[0] for p in pairs], [p[1] for p in pairs], holdout)
        body = {"yaw": fit.yaw, "tx": fit.tx, "ty": fit.ty, "residual_max_m": fit.max, "residual_rms_m": fit.rms,
                "pairs": [{"robot": list(r), "site": list(s)} for r, s in pairs],
                "holdout": [{"robot": list(r), "site": list(s), "err_m": e} for (r, s), e in zip(holdout, errors)]}
        frame_sha = self._frame_for_version(int(site[1])) if self._frame_for_version is not None else None
        binding_id, now = uuid.uuid4().hex, self._clock()
        with self._lock, self._db:
            self._db.execute("UPDATE robot_map_bindings SET revoked_by = ?, revoked_at = ?, revoke_reason = "
                             "'superseded' WHERE robot_id = ? AND revoked_at IS NULL", (principal_id, now, robot_id))
            self._db.execute("INSERT INTO robot_map_bindings (binding_id, robot_id, robot_map_id, robot_grid_id, "
                             "site_map_id, site_map_version, fit, approved_by, approved_at, site_frame_sha256, grid_sig) "
                             "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                             (binding_id, robot_id, robot_map_id, grid, site[0], int(site[1]), json.dumps(body),
                              principal_id, now, frame_sha, json.dumps(grid_sig) if grid_sig else None))
            self._event("map_binding_approve", principal_id, {"robot_id": robot_id, "binding_id": binding_id,
                        "robot_grid_id": grid, "site_map_version": int(site[1]), "residual_max_m": fit.max})
        return self.active(robot_id)

    def set_grid_sig(self, binding_id: str, grid_sig: dict) -> bool:  # once, for a binding approved without one
        with self._lock, self._db:
            return bool(self._db.execute("UPDATE robot_map_bindings SET grid_sig = ? WHERE binding_id = ? AND "
                                         "grid_sig IS NULL AND revoked_at IS NULL", (json.dumps(grid_sig), binding_id)).rowcount)

    def revoke(self, robot_id: str, principal_id: str, reason: str = "revoked") -> bool:
        with self._lock, self._db:
            changed = self._db.execute("UPDATE robot_map_bindings SET revoked_by = ?, revoked_at = ?, "
                                       "revoke_reason = ? WHERE robot_id = ? AND revoked_at IS NULL",
                                       (principal_id, self._clock(), reason[:120], robot_id)).rowcount
            if changed:
                self._event("map_binding_revoke", principal_id, {"robot_id": robot_id, "reason": reason[:120]})
        return bool(changed)

    def active(self, robot_id: str) -> Optional[dict]:
        with self._lock:
            row = self._db.execute(
                "SELECT binding_id, robot_map_id, robot_grid_id, site_map_id, site_map_version, fit, approved_by, "
                "approved_at, site_frame_sha256, grid_sig FROM robot_map_bindings WHERE robot_id = ? AND revoked_at IS NULL",
                (robot_id,)).fetchone()
        if row is None:
            return None
        return {"binding_id": row[0], "robot_id": robot_id, "robot_map_id": row[1], "robot_grid_id": row[2],
                "site_map_id": row[3], "site_map_version": row[4], "fit": json.loads(row[5]),
                "approved_by": row[6], "approved_at": row[7], "site_frame_sha256": row[8],
                "grid_sig": json.loads(row[9]) if row[9] else None}

    def history(self, robot_id: str, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT binding_id, robot_grid_id, site_map_version, approved_by, approved_at, revoked_by, "
                "revoked_at, revoke_reason FROM robot_map_bindings WHERE robot_id = ? ORDER BY approved_at DESC, rowid DESC "
                "LIMIT ?", (robot_id, limit)).fetchall()
        keys = ("binding_id", "robot_grid_id", "site_map_version", "approved_by", "approved_at", "revoked_by",
                "revoked_at", "revoke_reason")
        return [dict(zip(keys, row)) for row in rows]

    def binding_for_grid(self, robot_id: str, robot_grid_id: Optional[str],
                         site: Optional[tuple[str, int]]) -> tuple[Optional[Fit], str]:
        """Read-only frame transform for a bound robot grid, even before the robot is LOCALIZED."""
        binding = self.active(robot_id)
        if binding is None:
            return None, "MAP_BINDING_REQUIRED"
        if not _site_matches(binding, site, getattr(self, "_frame_for_version", None)):
            return None, "MAP_BINDING_SITE_CHANGED"
        if robot_grid_id != binding["robot_grid_id"]:
            return None, "MAP_BINDING_GRID_CHANGED"
        f = binding["fit"]
        return Fit(f["yaw"], f["tx"], f["ty"], (f["residual_max_m"],)), ""

    def matching_fit(self, robot_id: str, state: Mapping, site: Optional[tuple[str, int]]) -> tuple[Optional[Fit], str]:
        """(fit, "") when the active binding covers this robot state and the active site map, else (None, reason)."""
        binding = self.active(robot_id)
        if binding is None:
            return None, "MAP_BINDING_REQUIRED"
        if not _site_matches(binding, site, getattr(self, "_frame_for_version", None)):
            return None, "MAP_BINDING_SITE_CHANGED"
        loc = state.get("localization") or {}
        if loc.get("state") != "LOCALIZED" or loc.get("pose_frame") != "map":
            return None, "ROBOT_NOT_LOCALIZED"  # first: an unreachable robot ({}) is not a changed grid
        if state.get("map_grid_id") != binding["robot_grid_id"]:
            return None, "MAP_BINDING_GRID_CHANGED"
        f = binding["fit"]
        return Fit(f["yaw"], f["tx"], f["ty"], (f["residual_max_m"],)), ""
