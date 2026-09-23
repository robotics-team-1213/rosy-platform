"""Route model shared by both junction prototypes (Task 3-5): a directed
sequence of lane_graph segments, how far along it a pose is, the distance
to the next node, and the tangent to leave on. ROS-free.

`locate` restricts its nearest-point search to a +-SEARCH_WINDOW_M window
around the previous fix, for the same reason as junction_score's
`_nearest_on_path`: a road segment and its paired ring arc join the same
two nodes, so their combined path can double back on itself in space and an
unrestricted global search is ambiguous there.
"""

import math
from dataclasses import dataclass

import numpy as np

#: Nearest-point search window (see module docstring); matches
#: junction_score.SEARCH_WINDOW_M.
SEARCH_WINDOW_M = 0.5


@dataclass
class DirectedSegment:
    """One lane_graph segment walked in a fixed direction."""

    key: str
    points: np.ndarray   # (N, 2)
    arc: np.ndarray      # (N,) cumulative length from points[0]
    from_node: str
    to_node: str

    @classmethod
    def from_graph(cls, graph, key):
        name, way = key.split(":")
        seg = graph["segments"][name]
        if way == "r" and "reverse" not in seg["directions"]:
            raise ValueError(f"segment {name!r} is one-way, cannot use {key!r}")
        points = np.array(seg["points"], float)
        from_node, to_node = seg["from"], seg["to"]
        if way == "r":
            points = points[::-1]
            from_node, to_node = to_node, from_node
        arc = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))])
        return cls(key=key, points=points, arc=arc, from_node=from_node, to_node=to_node)

    @property
    def length_m(self) -> float:
        return float(self.arc[-1])


@dataclass
class Fix:
    """Where a pose sits on a LaneRoute."""

    segment_index: int
    s_m: float
    lateral_m: float
    distance_to_node_m: float
    heading: float


class LaneRoute:
    """Directed chain of lane_graph segments a follower is meant to drive."""

    def __init__(self, graph, keys):
        if not keys:
            raise ValueError("route needs at least one segment")
        self.segments = list(keys)
        self._segs = [DirectedSegment.from_graph(graph, k) for k in keys]
        for a, b in zip(self._segs, self._segs[1:]):
            if a.to_node != b.from_node:
                raise ValueError(f"segments {a.key!r} and {b.key!r} are not connected "
                                  f"({a.to_node!r} != {b.from_node!r})")
        # Combined polyline over every segment; each later segment's first
        # point (the shared node) is dropped since the previous segment
        # already ends there.
        chunks = [self._segs[0].points]
        starts = [0]
        for seg in self._segs[1:]:
            starts.append(starts[-1] + len(chunks[-1]) - 1)
            chunks.append(seg.points[1:])
        self._points = np.vstack(chunks)
        self._arc = np.concatenate(
            [[0.0], np.cumsum(np.linalg.norm(np.diff(self._points, axis=0), axis=1))])
        self.length_m = float(self._arc[-1])
        self._seg_start_s = [float(self._arc[i]) for i in starts]
        self._prev_s = None

    def _segment_at(self, s: float) -> int:
        idx = int(np.searchsorted(self._seg_start_s, s, side="right")) - 1
        return min(max(idx, 0), len(self._segs) - 1)

    def locate(self, xy) -> Fix:
        p = np.asarray(xy, float)
        a, b = self._points[:-1], self._points[1:]
        idx = np.arange(len(a))
        if self._prev_s is not None:
            lo, hi = self._prev_s - SEARCH_WINDOW_M, self._prev_s + SEARCH_WINDOW_M
            mask = (self._arc[:-1] >= lo) & (self._arc[:-1] <= hi)
            if mask.any():
                a, b, idx = a[mask], b[mask], idx[mask]
        ab = b - a
        ab_len2 = np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-12)
        t = np.clip(np.einsum("ij,ij->i", p - a, ab) / ab_len2, 0.0, 1.0)
        proj = a + ab * t[:, None]
        d2 = np.einsum("ij,ij->i", p - proj, p - proj)
        k = int(np.argmin(d2))
        i = int(idx[k])
        seg_len = float(np.linalg.norm(ab[k]))
        direction = ab[k] / max(seg_len, 1e-12)
        s = float(self._arc[i] + t[k] * seg_len)
        normal = np.array([-direction[1], direction[0]])
        lateral = float(np.dot(p - proj[k], normal))
        segment_index = self._segment_at(s)
        next_start = (self._seg_start_s[segment_index + 1] if segment_index + 1 < len(self._segs)
                      else self.length_m)
        fix = Fix(segment_index=segment_index,
                   s_m=s - self._seg_start_s[segment_index],
                   lateral_m=lateral,
                   distance_to_node_m=next_start - s,
                   heading=math.atan2(direction[1], direction[0]))
        self._prev_s = s
        return fix

    def exit_heading(self, segment_index: int) -> float:
        """Tangent of the next segment near the node segment_index exits
        into."""
        if segment_index + 1 >= len(self._segs):
            raise ValueError("no next segment to exit into")
        pts = self._segs[segment_index + 1].points
        i = min(3, len(pts) - 1)
        d = pts[i] - pts[0]
        return math.atan2(d[1], d[0])

    def point_ahead(self, xy, lookahead_m: float):
        """Point `lookahead_m` ahead of `xy`'s projection, following the
        route across segment boundaries."""
        self.locate(xy)
        target_s = min(self._prev_s + lookahead_m, self.length_m)
        idx = max(1, min(int(np.searchsorted(self._arc, target_s)), len(self._points) - 1))
        a, b = self._points[idx - 1], self._points[idx]
        seg_len = self._arc[idx] - self._arc[idx - 1]
        t = 0.0 if seg_len <= 0.0 else (target_s - self._arc[idx - 1]) / seg_len
        point = a + t * (b - a)
        return float(point[0]), float(point[1])

    def heading_at(self, segment_index: int, s_m: float) -> float:
        target_s = min(max(self._seg_start_s[segment_index] + s_m, 0.0), self.length_m)
        idx = max(1, min(int(np.searchsorted(self._arc, target_s)), len(self._points) - 1))
        d = self._points[idx] - self._points[idx - 1]
        return math.atan2(d[1], d[0])
