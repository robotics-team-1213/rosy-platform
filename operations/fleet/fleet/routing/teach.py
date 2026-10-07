"""D-494 6: teach a lane by driving it — the pure part.

Recording keeps a map pose when it is ``LOCALIZED`` or bridged at most ``MAX_BRIDGE_M``,
at least ``SPACING_M`` from the last kept point. Stopping simplifies with Ramer–Douglas–Peucker
(``RDP_TOL_M``) and proposes the existing places within ``SNAP_M`` of each end. Confirming
appends the edge (and new places) to a site map body; the caller validates and saves it as the
draft. Standard library only; ``fleet.server.teach_service`` owns the clock and the robot reads.
"""

from __future__ import annotations

import copy
import math
from typing import Optional, Union

from fleet.routing.graph import pinned

SPACING_M = 0.10
MAX_BRIDGE_M = 0.5
RDP_TOL_M = 0.02
SNAP_M = 0.15

Point = tuple[float, float]


def keep(points: list[Point], pose) -> Optional[Point]:
    """The point to append for ``pose`` (a ``MapPose``), or None."""
    if pose is None or pose.x is None or pose.y is None or pose.state == "UNKNOWN":
        return None
    if pose.state != "LOCALIZED" and not pose.dead_reckon_m <= MAX_BRIDGE_M:
        return None
    point = (float(pose.x), float(pose.y))
    if points and math.dist(points[-1], point) < SPACING_M:
        return None
    return point


def _off_segment(p: Point, a: Point, b: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    span2 = dx * dx + dy * dy
    t = 0.0 if span2 == 0.0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / span2))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def simplify(points: list[Point], tol: float = RDP_TOL_M) -> list[Point]:
    """Ramer–Douglas–Peucker: keeps a point farther than ``tol`` from its span's chord.

    Distance is to the chord segment, so a closed loop (start == end) still keeps its far side.
    Iterative, so a 20k-point recording cannot hit the recursion limit."""
    if len(points) < 3:
        return list(points)
    kept = {0, len(points) - 1}
    spans = [(0, len(points) - 1)]
    while spans:
        first, last = spans.pop()
        far, index = -1.0, None
        for i in range(first + 1, last):
            off = _off_segment(points[i], points[first], points[last])
            if off > far:
                far, index = off, i
        if index is not None and far > tol:
            kept.add(index)
            spans += [(first, index), (index, last)]
    return [points[i] for i in sorted(kept)]


def candidates(places, point: Point, within: float = SNAP_M) -> list[dict]:
    """Existing places within ``within`` of ``point``, nearest first; empty means a new place."""
    near = sorted(((math.dist(point, (p["x"], p["y"])), p) for p in places), key=lambda item: item[0])
    return [{"place_id": p["id"], "name": p["name"], "distance_m": round(d, 3)} for d, p in near if d <= within]


def _free_id(prefix: str, taken) -> str:
    n = 1
    while f"{prefix}{n}" in taken:
        n += 1
    return f"{prefix}{n}"


class TeachRefused(ValueError):
    def __init__(self, code: str, detail: dict) -> None:
        super().__init__(code)
        self.code, self.detail = code, detail


def _place(body: dict, ref: Union[str, dict], end: Point, which: str) -> str:
    """An existing place id within ``SNAP_M`` of ``end``, or a new place at ``end``."""
    if isinstance(ref, str):
        found = next((p for p in body["places"] if p["id"] == ref), None)
        if found is None:
            raise TeachRefused("TEACH_UNKNOWN_PLACE", {"end": which, "place_id": ref})
        if math.dist(end, (found["x"], found["y"])) > SNAP_M:
            raise TeachRefused("TEACH_PLACE_TOO_FAR", {"end": which, "place_id": ref, "within_m": SNAP_M})
        return ref
    return add_place(body, ref["name"], ref.get("kind", "junction"), end[0], end[1])


def add_place(body: dict, name: str, kind: str, x: float, y: float, yaw: Optional[float] = None) -> str:
    place_id = _free_id("teach_p", {p["id"] for p in body["places"]})
    place = {"id": place_id, "name": name, "x": round(x, 4), "y": round(y, 4), "kind": kind}
    if yaw is not None:
        place["yaw"] = yaw
    body["places"].append(place)
    return place_id


def append_edge(base: dict, polyline: list[Point], *, start: Union[str, dict], end: Union[str, dict],
                direction: str, drive_mode: str, speed_cap_mps: float, width_m: float) -> tuple[dict, str]:
    """A copy of ``base`` (a site map body) with the taught edge; ``start``/``end`` are a place id
    or ``{name, kind}`` for a new place at that end. The polyline ends are pinned onto the places."""
    body = copy.deepcopy(base)
    a = _place(body, start, polyline[0], "from")
    b = _place(body, end, polyline[-1], "to")
    xy = {p["id"]: (p["x"], p["y"]) for p in body["places"]}
    edge_id = _free_id("teach_e", {e["id"] for e in body["edges"]})
    body["edges"].append({"id": edge_id, "from": a, "to": b,
                          "polyline": [list(p) for p in pinned(polyline, xy[a], xy[b])],
                          "direction": direction, "drive_mode": drive_mode,
                          "speed_cap_mps": speed_cap_mps, "width_m": width_m})
    return body, edge_id
