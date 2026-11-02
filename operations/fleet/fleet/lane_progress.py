"""D-941 2: following by lane progress on a one-lane loop.

Pure. ``s`` is the distance along the loop, the gap to the robot ahead is
``(s_lead - s_me) mod perimeter`` and the follower's speed is
``min(v_lead + K * (gap - target), v_cap(s))``, never below 0. Per D-941 the 20 Hz loop
belongs on the robot; Fleet uses this to pick leaders, relay ``(s, v)`` and show the gaps.
"""

from __future__ import annotations

import heapq
import math
from typing import Mapping, Optional, Sequence

TARGET_GAP_M = 0.6     # D-941 start value; replace with the measured body stop distance
K_PER_S = 0.5          # shortcut: nominal gain, tune on the track with two robots
MIN_GAP_M = 0.25       # closer than this the follower stops whatever the leader does
ON_LOOP_M = 0.1        # shortcut: about half a lane; use the lane width_m once robots are measured on it


def main_loop(site_map) -> Optional[list[str]]:
    """The shortest one-way cycle, in driving order: on the D-941 track the platoon loop, not the park detour.

    shortcut: the map has no loop marker; mark the loop on the map if a site gets two equally short cycles.
    """
    lanes = [e for e in site_map.edges if e.direction == "one_way"]
    length = {e.id: sum(math.dist(a, b) for a, b in zip(e.polyline, e.polyline[1:])) for e in lanes}
    best: tuple[float, list[str]] = (math.inf, [])
    for first in lanes:
        dist, back, heap = {first.to: 0.0}, {}, [(0.0, first.to)]
        while heap:
            d, node = heapq.heappop(heap)
            if node == first.from_ or d > dist[node]:
                continue
            for e in lanes:
                if e.from_ == node and d + length[e.id] < dist.get(e.to, math.inf):
                    dist[e.to], back[e.to] = d + length[e.id], e
                    heapq.heappush(heap, (dist[e.to], e.to))
        if first.from_ not in dist or length[first.id] + dist[first.from_] >= best[0]:
            continue
        path, node = [], first.from_
        while node != first.to:
            path.append(back[node].id)
            node = back[node].from_
        best = (length[first.id] + dist[first.from_], [first.id, *reversed(path)])
    return best[1] or None


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


def platoon(loop: Loop, poses: Mapping[str, tuple[float, float]]) -> list[dict]:
    """Display rows: each localized robot's progress, the robot ahead and how the gap stands."""
    on, rows = {}, {}
    for rid, (x, y) in poses.items():
        s, off = loop.project(x, y)
        if off <= ON_LOOP_M:
            on[rid] = s
            rows[rid] = {"robot_id": rid, "s_m": round(s, 3), "off_m": round(off, 3), "state": "alone"}
        else:
            rows[rid] = {"robot_id": rid, "s_m": None, "off_m": round(off, 3), "state": "off_loop"}
    for rid, (ahead, gap) in leaders(loop, on).items():
        state = "too_close" if gap < MIN_GAP_M else "close" if gap < TARGET_GAP_M else "ok"
        rows[rid].update(leader=ahead, gap_m=round(gap, 3), state=state)
    return [rows[rid] for rid in sorted(rows)]


def follower_speed(v_lead: float, gap: float, v_cap: float, *, target: float = TARGET_GAP_M,
                   k: float = K_PER_S) -> float:
    if gap < MIN_GAP_M:
        return 0.0
    return max(0.0, min(v_lead + k * (gap - target), v_cap))
