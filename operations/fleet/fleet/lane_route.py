"""Ordered lane-graph edges become one polyline and one short next point.

A console point goal stays ``{x, y, yaw}``. This module does not call CORE.
The far junction is not a goal: Nav2 would cut across the empty floor.
``STEP_M`` is the existing 0.20 m traffic sample. On the 0.2514 m ring that
straight step sags about 0.02 m, inside the 0.08 m lane band. The device goal
ball has to be shorter than this step, or the follower is already inside it
and only rotates.

A closed lap starts and ends on the same point. ``along_m`` keeps the
along-track progress so that shared point is the end once the route has
been followed, and the start on a fresh route.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import yaml

from fleet.meet.place import default_graph, painted_track

STEP_M = 0.20
OFF_M = 0.08
DONE_M = 0.05
MAX_EDGES = 8
#: Two projections of one pose (a closed junction) agree within a millimetre.
_TIE_M = 1e-3


class LaneRouteError(ValueError):
    """``str(self)`` is the API code."""


@dataclass(frozen=True)
class LaneStep:
    x: float
    y: float
    yaw: float
    s_m: float
    remaining_m: float
    #: Along-track pose used to choose this step. The caller keeps it.
    at_m: float = 0.0


_LINKS: dict[str, tuple[str, str]] | None = None


def segment_links(path: Path | None = None) -> dict[str, tuple[str, str]]:
    global _LINKS
    if path is None and _LINKS is not None:
        return _LINKS
    graph_path = default_graph() if path is None else Path(path)
    graph = yaml.safe_load(graph_path.read_text(encoding="utf-8"))
    segments = graph.get("segments") if isinstance(graph, dict) else None
    if not isinstance(segments, dict):
        raise ValueError(f"{graph_path} has no segments")
    links: dict[str, tuple[str, str]] = {}
    for name, segment in segments.items():
        if not isinstance(segment, dict):
            continue
        src, dst = segment.get("from"), segment.get("to")
        if isinstance(src, str) and isinstance(dst, str):
            links[str(name)] = (src, dst)
    if path is None:
        _LINKS = links
    return links


def route_lines(edge_ids: list[str] | tuple[str, ...]):
    """Stored polylines in order. Unknown or broken joins raise ``LaneRouteError``."""
    if not edge_ids:
        raise LaneRouteError("ROUTE_EMPTY")
    if len(edge_ids) > MAX_EDGES:
        raise LaneRouteError("ROUTE_TOO_LONG")
    painted = painted_track()
    links = segment_links()
    lines = []
    previous: str | None = None
    for edge_id in edge_ids:
        link = links.get(edge_id)
        if link is None:
            raise LaneRouteError("ROUTE_UNKNOWN_EDGE")
        src, dst = link
        if previous is not None and previous != src:
            raise LaneRouteError("ROUTE_DISCONTINUOUS")
        try:
            lines.append(painted.line(edge_id))
        except KeyError as exc:
            raise LaneRouteError("ROUTE_UNKNOWN_EDGE") from exc
        previous = dst
    return tuple(lines)


def _located(lines, x: float, y: float, along_m: float) -> tuple[float, float]:
    """``(at_m, total_m)`` of the pose on ``lines``.

    The closest projection wins. A closed junction is two projections of one
    pose; ``along_m`` picks the one the route has already reached.
    """
    if not math.isfinite(along_m) or along_m < 0.0:
        raise ValueError("along_m must be a nonnegative finite distance")
    best: float | None = None
    found: list[tuple[float, float]] = []
    cursor = 0.0
    for line in lines:
        dist, s_m, _tangent = line.project(x, y)
        found.append((dist, cursor + s_m))
        if best is None or dist < best:
            best = dist
        cursor += line.length_m
    if best is None or best > OFF_M:
        raise LaneRouteError("ROUTE_OFF_LANE")
    tied = [item for item in found if item[0] <= best + _TIE_M]
    _dist, at_m = min(tied, key=lambda item: (abs(item[1] - along_m), -item[1]))
    return at_m, cursor


def next_step(lines, x: float, y: float, *, along_m: float = 0.0) -> LaneStep | None:
    """The point ``STEP_M`` ahead on ``lines``, or None at the end.

    A pose more than ``OFF_M`` off the polyline raises ``ROUTE_OFF_LANE``.
    ``along_m`` is how far along this route the pose has already been. Zero
    is the start of a fresh route.
    """
    s_global, total = _located(lines, x, y, along_m)
    if total - s_global <= DONE_M:
        return None
    target = min(s_global + STEP_M, total)
    walked = 0.0
    for line in lines:
        end = walked + line.length_m
        if target <= end or line is lines[-1]:
            px, py, yaw = line.point_at(target - walked)
            return LaneStep(px, py, yaw, target, total - target, s_global)
        walked = end
    raise LaneRouteError("ROUTE_OFF_LANE")
