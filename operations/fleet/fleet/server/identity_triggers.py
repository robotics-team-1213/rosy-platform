"""D-596 2: when Fleet asks a robot for an LED identify by itself. Pure; nothing here moves a robot.

``AutoTriggers.due`` reads the D-457 tracking snapshot and the robots' fresh states and names the
robots to ask, each with a reason:

- ``marker_missing``: the robot's top marker was seen and has been missing for
  ``auto_marker_missing_s`` while an anonymous blob lies within ``auto_near_m`` of where the
  marker was last seen (else the robot's own map pose).
- ``split``: the robot's confirmed track was dropped because two blobs met (``overlap``) and an
  anonymous blob near its predicted place now stands alone again (no other within ``overlap_m``).
- ``odom_reset``: the robot's reported pose jumped to its odom origin while an anonymous blob is
  on the camera.

Never: a robot without a fresh state, with ``safety.estop`` not exactly false (D-472 5), one
already confirmed or pending, one asked within ``auto_min_interval_s``, or one no camera source
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
            watched: set, skip: set, last_reason: Mapping[str, Optional[str]]) -> list[tuple[str, str]]:
        cfg = self.config
        rows = {row.get("robot_id"): row for row in snapshot.get("robots") or []}
        blobs = [p for p in (_point(u) for u in snapshot.get("unknown") or [] if u.get("marker_id") is None)
                 if p is not None]
        found = []
        for robot_id in sorted(watched):
            row = rows.get(robot_id) or {}
            self._remember(robot_id, row, states.get(robot_id), now)
            state = states.get(robot_id)
            if (robot_id in skip or not isinstance(state, Mapping)
                    or (state.get("safety") or {}).get("estop") is not False):
                continue
            marker = self._marker.get(robot_id)
            predicted = (marker[1], marker[2]) if marker else _point(row.get("pose") or {})
            near = [] if predicted is None else [
                b for b in blobs if math.hypot(b[0] - predicted[0], b[1] - predicted[1]) <= cfg.auto_near_m]
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

    def last_marker(self, robot_id: str) -> Optional[tuple[float, float]]:
        marker = self._marker.get(robot_id)
        return None if marker is None else (marker[1], marker[2])

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
