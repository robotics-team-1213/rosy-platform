"""Name an anonymous camera detection by motion (2026-11-21 user rule: the site must work out where its robots are).

LED identity (D-472) needs the robot's lamp, which refuses while it shows caution. Here the evidence is motion
alone: one robot's own pose says it moved, exactly one camera detection moved the same distance, and every other
robot and detection stood still. Pure: numbers in, at most one (robot, point) out. Anything ambiguous starts over.
The binding it gives is used like an LED one (observation only); D-989 still needs a 0.5 m span that fits.
"""

from __future__ import annotations

import math
from typing import Mapping, Optional, Sequence

#: Site settings (identity: in the sightings YAML) carry these; the values here are only the defaults there.
#: min_move: shorter moves are inside camera noise. tol: camera and robot distances agree within this
#: (camera error about 5 cm on site 2026-11-21). still: anything that moved less stood still.

Point = tuple[float, float]


class MotionMatcher:
    """One camera source. ``observe`` each detection frame with the anonymous points and the robots' own poses."""

    def __init__(self, step_m: float, *, min_move_m: float, tol_m: float, still_m: float, window_s: float) -> None:
        self._step_m, self._min_move_m, self._tol_m = step_m, min_move_m, tol_m
        self._still_m, self._window_s = still_m, window_s
        self._base: Optional[tuple[float, list[Point], dict[str, Point]]] = None
        self._now: list[Point] = []

    def _restart(self, now: float, points: Sequence[Point], robots: Mapping[str, Optional[Point]]) -> None:
        self._base = (now, list(points), {rid: xy for rid, xy in robots.items() if xy is not None})
        self._now = list(points)

    def observe(self, now: float, points: Sequence[Point],
                robots: Mapping[str, Optional[Point]]) -> Optional[tuple[str, Point, float]]:
        """(robot_id, its detection now, metres moved) when the motion names exactly one; else None."""
        if self._base is None or not 0.0 <= now - self._base[0] <= self._window_s:
            self._restart(now, points, robots)
            return None
        _, base_points, base_robots = self._base
        followed: list[Point] = []
        for last in self._now:  # each baseline track continues in its nearest point, one point per track
            near = sorted(points, key=lambda p: math.dist(p, last))
            if not near or math.dist(near[0], last) > self._step_m or near[0] in followed:
                self._restart(now, points, robots)  # a track was lost or two merged: who is who is gone
                return None
            followed.append(near[0])
        self._now = followed
        if set(base_robots) - {rid for rid, xy in robots.items() if xy is not None}:
            self._restart(now, points, robots)  # a robot stopped reporting: it may be the one moving
            return None
        moved = {rid: math.dist(robots[rid], xy) for rid, xy in base_robots.items()}
        movers = [rid for rid, d in moved.items() if d >= self._min_move_m]
        if not movers:
            return None
        track_moved = [math.dist(a, b) for a, b in zip(base_points, followed)]
        mover = movers[0]
        fits = [i for i, d in enumerate(track_moved) if abs(d - moved[mover]) <= self._tol_m]
        clear = (len(movers) == 1 and len(fits) == 1
                 and all(d < self._still_m for rid, d in moved.items() if rid != mover)
                 and all(d < self._still_m for i, d in enumerate(track_moved) if i != fits[0]))
        found = (mover, followed[fits[0]], moved[mover]) if clear else None
        self._restart(now, points, robots)
        return found
