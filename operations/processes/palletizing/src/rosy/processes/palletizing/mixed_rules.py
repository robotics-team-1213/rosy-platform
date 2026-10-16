"""Placement rules of D-781 §3 for the mixed planner, on axis-aligned boxes in one pallet frame.

A Placed box is stored by its min corner (x, y, z) in its pallet frame and its extents after
yaw (lx along pallet x, ly along pallet y, h). Rules here are pure functions of the boxes
already placed, so the planner can test a candidate before committing it.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .mixed_cell import EPS, Finger, Rect

# support_ratio_v1 (Zhao et al. 2021, D-781 §1): (ratio above, supported corners needed).
SUPPORT_RATIO_V1 = ((0.60, 4), (0.80, 3), (0.95, 0))


@dataclass(frozen=True)
class Placed:
    index: int
    sku: str
    pallet_id: str
    x: float
    y: float
    z: float
    lx: float
    ly: float
    h: float
    yaw_deg: int
    mass_kg: float
    max_load_on_top_kg: float
    grasp_depth: float

    @property
    def top(self) -> float:
        return self.z + self.h

    @property
    def footprint(self) -> Rect:
        return (self.x, self.y, self.x + self.lx, self.y + self.ly)

    @property
    def centre(self) -> tuple[float, float]:
        return (self.x + self.lx / 2, self.y + self.ly / 2)


def overlap_area(a: Rect, b: Rect) -> float:
    dx = min(a[2], b[2]) - max(a[0], b[0])
    dy = min(a[3], b[3]) - max(a[1], b[1])
    return dx * dy if dx > EPS and dy > EPS else 0.0


def expand(r: Rect, d: float) -> Rect:
    return (r[0] - d, r[1] - d, r[2] + d, r[3] + d)


def bounding(rects: Iterable[Rect]) -> Rect:
    rs = list(rects)
    return (min(r[0] for r in rs), min(r[1] for r in rs), max(r[2] for r in rs), max(r[3] for r in rs))


def finger_rects(p: Placed, finger: Finger) -> tuple[Rect, Rect]:
    """The two strips beside the grasped width faces that the open fingers sweep on the way down.

    At yaw 0 the item width runs along pallet y, so the fingers sit beyond y_min and y_max; at
    yaw 90 the width runs along x.
    """
    out, half = finger.reach_out_m, finger.breadth_m / 2
    x0, y0, x1, y1 = p.footprint
    cx, cy = p.centre
    if p.yaw_deg == 0:
        return ((cx - half, y0 - out, cx + half, y0), (cx - half, y1, cx + half, y1 + out))
    return ((x0 - out, cy - half, x0, cy + half), (x1, cy - half, x1 + out, cy + half))


def finger_low_z(p: Placed, finger: Finger) -> float:
    """Lowest point the fingertips reach when the item sits in place (TCP is grasp_depth below the top)."""
    return p.top - p.grasp_depth - finger.overhang_m


def envelope(p: Placed, finger: Finger) -> Rect:
    return bounding((p.footprint, *finger_rects(p, finger)))


def rest_z(footprint: Rect, placed: Sequence[Placed]) -> float:
    """Height an item comes to rest at when lowered over `footprint` (gravity drop)."""
    return max((q.top for q in placed if overlap_area(footprint, q.footprint) > 0), default=0.0)


def supporters(p: Placed, placed: Sequence[Placed]) -> list[tuple[Placed, float]]:
    """Boxes whose top touches p's bottom, with their contact area."""
    if p.z <= EPS:
        return []
    out = []
    for q in placed:
        if q is not p and abs(q.top - p.z) <= 1e-7:
            area = overlap_area(p.footprint, q.footprint)
            if area > 0:
                out.append((q, area))
    return out


def support_ratio_and_corners(p: Placed, placed: Sequence[Placed]) -> tuple[float, int]:
    if p.z <= EPS:
        return 1.0, 4
    sup = supporters(p, placed)
    ratio = sum(a for _, a in sup) / (p.lx * p.ly)
    x0, y0, x1, y1 = p.footprint
    corners = 0
    for cx, cy in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
        if any(q.x - EPS <= cx <= q.x + q.lx + EPS and q.y - EPS <= cy <= q.y + q.ly + EPS for q, _ in sup):
            corners += 1
    return ratio, corners


def support_ok(ratio: float, corners: int) -> bool:
    # "more than" the ratio (D-781 §1): exactly 60 % with four corners fails.
    return any(ratio > need + EPS and corners >= n for need, n in SUPPORT_RATIO_V1)


def loads_on_top(placed: Sequence[Placed]) -> dict[int, float]:
    """Mass (kg) each box carries from the boxes above it.

    A box hands its own mass plus its carried load down to its supporters in proportion to
    contact area. Boxes are processed from the top down so every load is complete when passed on.
    """
    carried = {p.index: 0.0 for p in placed}
    for p in sorted(placed, key=lambda b: (-b.z, b.index)):
        sup = supporters(p, placed)
        total = sum(a for _, a in sup)
        for q, area in sup:
            carried[q.index] += (p.mass_kg + carried[p.index]) * area / total
    return carried


def load_problems(placed: Sequence[Placed]) -> list[Placed]:
    carried = loads_on_top(placed)
    return [p for p in placed if carried[p.index] > p.max_load_on_top_kg + 1e-12]


def gap_conflict(p: Placed, placed: Sequence[Placed], gap: float) -> bool:
    """Another box overlaps p's height band and is closer than `gap` in the plane (or overlaps it)."""
    grown = expand(p.footprint, max(gap - EPS, 0.0))
    return any(q.z < p.top - EPS and q.top > p.z + EPS and overlap_area(grown, q.footprint) > 0 for q in placed)


def in_approach(p: Placed, q: Placed, finger: Finger) -> bool:
    """q's body lies in the volume p needs free while it is lowered and released.

    That volume is the column over p's footprint above p's bottom and the two finger strips
    from the fingertip low point upwards. If q is in it, q must be placed after p (D-781 §4).
    """
    if overlap_area(p.footprint, q.footprint) > 0 and q.top > p.z + EPS and q.z >= p.top - 1e-7:
        return True
    low = finger_low_z(p, finger)
    return q.top > low + EPS and any(overlap_area(r, q.footprint) > 0 for r in finger_rects(p, finger))
