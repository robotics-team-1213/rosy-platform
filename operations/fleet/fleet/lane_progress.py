"""D-941 2: following by lane progress on a one-lane loop.

Pure. ``s`` is the distance along the loop, the gap to the robot ahead is
``(s_lead - s_me) mod perimeter`` and the follower's speed is
``min(v_lead + K * (gap - target), v_cap(s))``, never below 0. Per D-941 the 20 Hz loop
belongs on the robot; Fleet uses this to pick leaders, relay ``(s, v)`` and show the gaps.
"""

from __future__ import annotations

import math
from typing import Mapping, Sequence

TARGET_GAP_M = 0.6     # D-941 start value; replace with the measured body stop distance
K_PER_S = 0.5          # shortcut: nominal gain, tune on the track with two robots
MIN_GAP_M = 0.25       # closer than this the follower stops whatever the leader does


class Loop:
    """The loop as one closed polyline built from its edges in driving order."""

    def __init__(self, site_map, edge_ids: Sequence[str]) -> None:
        edges = {e.id: e for e in site_map.edges}
        pts: list[tuple[float, float]] = []
        for edge_id in edge_ids:
            line = [tuple(p) for p in edges[edge_id].polyline]
            if pts and math.dist(pts[-1], line[0]) > 0.05:
                raise ValueError(f"loop breaks before {edge_id}")
            pts.extend(line[1:] if pts else line)
        if math.dist(pts[0], pts[-1]) > 0.05:
            raise ValueError("loop does not close")
        self.points = pts
        self.starts = [0.0]
        for a, b in zip(pts, pts[1:]):
            self.starts.append(self.starts[-1] + math.dist(a, b))
        self.perimeter = self.starts[-1]

    def project(self, x: float, y: float) -> tuple[float, float]:
        """(s, distance off the lane) of the nearest loop point."""
        best = (math.inf, 0.0)
        for i, (a, b) in enumerate(zip(self.points, self.points[1:])):
            dx, dy = b[0] - a[0], b[1] - a[1]
            seg = dx * dx + dy * dy
            t = 0.0 if seg == 0 else max(0.0, min(1.0, ((x - a[0]) * dx + (y - a[1]) * dy) / seg))
            off = math.dist((x, y), (a[0] + t * dx, a[1] + t * dy))
            if off < best[0]:
                best = (off, (self.starts[i] + t * math.sqrt(seg)) % self.perimeter)
        return best[1], best[0]

    def gap(self, s_lead: float, s_me: float) -> float:
        return (s_lead - s_me) % self.perimeter


def leaders(loop: Loop, progress: Mapping[str, float]) -> dict[str, tuple[str, float]]:
    """Each robot's robot directly ahead and the gap to it (a lone robot has none)."""
    out = {}
    for me, s_me in progress.items():
        ahead = [(loop.gap(s, s_me), rid) for rid, s in progress.items() if rid != me]
        if ahead:
            gap, rid = min(ahead)
            out[me] = (rid, gap)
    return out


def follower_speed(v_lead: float, gap: float, v_cap: float, *, target: float = TARGET_GAP_M,
                   k: float = K_PER_S) -> float:
    if gap < MIN_GAP_M:
        return 0.0
    return max(0.0, min(v_lead + k * (gap - target), v_cap))
