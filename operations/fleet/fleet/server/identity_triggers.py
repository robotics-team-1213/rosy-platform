"""D-596 2: when Fleet asks a robot for an LED identify by itself. Pure; nothing here moves a robot.

``AutoTriggers.due`` reads the D-457 tracking snapshot and the robots' fresh states and names the
robots to ask, each with a reason:

- ``marker_missing``: the robot's top marker was seen and has been missing for
  ``auto_marker_missing_s`` while an anonymous blob lies near where the robot is expected
  (``expected``: Fleet's map pose bridged by odom from the last sighting, within ``auto_near_m``
  plus ODOM_ERROR_PER_M of the odom path since it; else the last marker place, else the robot's
  own map pose, within ``auto_near_m``).
- ``split``: the robot's confirmed track was dropped because two blobs met (``overlap``) and an
  anonymous blob near its predicted place now stands alone again (no other within ``overlap_m``).
- ``odom_reset``: the robot's reported pose jumped to its odom origin while an anonymous blob is
  on the camera.

A blob below MIN_BLOB_SCORE (a sliver of a lane line or noise, not a robot-sized blob) never
counts. Never: a robot without a fresh state, with ``safety.estop`` not exactly false (D-472 5),
one showing a caution (``caution``: rosy-face refuses the blink then, so the request would only
come back as ``none``), one already confirmed or pending, one asked within ``auto_min_interval_s``, or one no camera source
watches. The caller (IdentityService.tick) owns those sets and the colour rules.
"""

from __future__ import annotations

import math
from typing import Mapping, Optional

#: An odom pose this close to (0, 0) after one farther than ODOM_RESET_FROM_M is an odom reset.
ODOM_RESET_AT_M = 0.05
ODOM_RESET_FROM_M = 0.3
#: D-596 7: auto_min_interval_s times this, by automatic requests since the marker was last seen
#: (30 s, 2 min, then 5 min while it stays hidden).
BACKOFF = (1, 4, 10)
#: Blobs scored below this are not a robot (site 2026-10-10: 0.054 on a lane line next to the
#: robot's last place made rosy_41 look found; robots and D-547 guesses score 0.35-1.0).
MIN_BLOB_SCORE = 0.1
#: Expected-place radius growth per metre of odom since the anchor (D-598: raw odom reaches 10-15 cm
#: per metre on corners). ponytail: a fixed p90 rate; use D-598 2's per-robot error bound once it exists.
ODOM_ERROR_PER_M = 0.15
MAX_NEAR_M = 1.0


def caution(state) -> bool:
    """CORE's face cautions (display.py face_cautions): rosy-face shows the caution lamp then and
    refuses an identify blink (D-472 5), so Fleet does not ask."""
    if not isinstance(state, Mapping):
        return False
    line = state.get("line_follow") if isinstance(state.get("line_follow"), Mapping) else {}
    docking = state.get("docking") if isinstance(state.get("docking"), Mapping) else {}
    return ((line.get("mode") not in (None, "OFF") and line.get("state") == "HOLD")
            or docking.get("state") == "DOCK_FAILED")


def _robot_sized(blob: Mapping) -> bool:
    score = blob.get("score")
    return score is None or (isinstance(score, (int, float)) and score >= MIN_BLOB_SCORE)


def _point(raw) -> Optional[tuple[float, float]]:
    try:
        x, y = float(raw["x"]), float(raw["y"])
    except (KeyError, TypeError, ValueError):
        return None
    return (x, y) if math.isfinite(x) and math.isfinite(y) else None


class AutoTriggers:
    def __init__(self, config) -> None:
        self.config = config
        self._marker: dict[str, tuple[float, float, float]] = {}   # robot -> (seen at, x, y)
        self._lost_since: dict[str, float] = {}
        self._odom: dict[str, tuple[float, float]] = {}
        self._reset_at: dict[str, float] = {}
        self._auto_asked: dict[str, int] = {}  # automatic requests since the marker was last seen

    def due(self, now: float, snapshot: Mapping, states: Mapping[str, Optional[Mapping]], *,
            watched: set, skip: set, last_reason: Mapping[str, Optional[str]],
            map_poses: Optional[Mapping] = None) -> list[tuple[str, str]]:
        cfg = self.config
        rows = {row.get("robot_id"): row for row in snapshot.get("robots") or []}
        blobs = [p for p in (_point(u) for u in snapshot.get("unknown") or []
                             if u.get("marker_id") is None and _robot_sized(u)) if p is not None]
        found = []
        for robot_id in sorted(watched):
            row = rows.get(robot_id) or {}
            self._remember(robot_id, row, states.get(robot_id), now)
            state = states.get(robot_id)
            if (robot_id in skip or not isinstance(state, Mapping)
                    or (state.get("safety") or {}).get("estop") is not False or caution(state)):
                continue
            predicted = self.expected(robot_id, (map_poses or {}).get(robot_id), row)
            near = [] if predicted is None else [
                b for b in blobs if math.hypot(b[0] - predicted[0], b[1] - predicted[1]) <= predicted[2]]
            lost = self._lost_since.get(robot_id)
            if near and lost is not None and now - lost >= cfg.auto_marker_missing_s:
                found.append((robot_id, "marker_missing"))
            elif near and last_reason.get(robot_id) == "overlap" and any(
                    all(o is b or math.hypot(o[0] - b[0], o[1] - b[1]) > cfg.overlap_m for o in blobs)
                    for b in near):
                found.append((robot_id, "split"))
            elif blobs and now - self._reset_at.get(robot_id, -math.inf) <= cfg.auto_min_interval_s:
                found.append((robot_id, "odom_reset"))
        return found

    def asked(self, robot_id: str, *, auto: bool = False) -> None:
        """A request went out: the odom reset is answered, a new one must happen first."""
        self._reset_at.pop(robot_id, None)
        if auto:
            self._auto_asked[robot_id] = self._auto_asked.get(robot_id, 0) + 1

    def backoff(self, robot_id: str) -> int:
        """Multiplier of the per-robot interval for the next automatic request."""
        return BACKOFF[min(max(self._auto_asked.get(robot_id, 0) - 1, 0), len(BACKOFF) - 1)]

    def expected(self, robot_id: str, map_pose, row: Optional[Mapping] = None
                 ) -> Optional[tuple[float, float, float]]:
        """(x, y, radius) where the robot should be, or None.

        Fleet's map pose (D-494 3) first while it has one (LOCALIZED or DEGRADED): it starts at the
        last sighting and follows odom, so a robot that drove off its last marker place is looked
        for where it went, not where it was (site 2026-10-10: rosy_41 0.58 m from its old place,
        a ghost blob left there). The radius grows with the odom path since the anchor. Then the
        last marker place, then the tracking row's map pose (both ``auto_near_m``)."""
        near = self.config.auto_near_m
        x, y = getattr(map_pose, "x", None), getattr(map_pose, "y", None)
        if getattr(map_pose, "state", None) in ("LOCALIZED", "DEGRADED") and x is not None and y is not None:
            path = getattr(map_pose, "dead_reckon_m", 0.0) or 0.0
            return float(x), float(y), min(near + ODOM_ERROR_PER_M * path, max(MAX_NEAR_M, near))
        marker = self._marker.get(robot_id)
        if marker is not None:
            return marker[1], marker[2], near
        point = _point((row or {}).get("pose") or {})
        return None if point is None else (*point, near)

    def _remember(self, robot_id: str, row: Mapping, state: Optional[Mapping], now: float) -> None:
        if row.get("status") == "MARKER":
            point = _point(row.get("camera") or {})
            if point is not None:
                self._marker[robot_id] = (now, *point)
            self._lost_since.pop(robot_id, None)
            self._auto_asked.pop(robot_id, None)
        elif robot_id in self._marker:
            self._lost_since.setdefault(robot_id, now)
        pose = _point((state or {}).get("pose") or {}) if isinstance(state, Mapping) else None
        if pose is None:
            return
        before = self._odom.get(robot_id)
        if (before is not None and math.hypot(*before) > ODOM_RESET_FROM_M
                and math.hypot(*pose) <= ODOM_RESET_AT_M):
            self._reset_at[robot_id] = now
        self._odom[robot_id] = pose
