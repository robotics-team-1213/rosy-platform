"""Single-layer placements in the pallet frame."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .load import Box, Pallet

_EPS = 1e-9  # float slack so exact fits are not floored away; not a physical tolerance


@dataclass(frozen=True)
class Placement:
    x: float
    y: float
    yaw: float


def footprint(box: Box, yaw: float) -> tuple[float, float]:
    """(extent along pallet x, extent along pallet y) for a box at yaw 0 or pi/2."""
    # yaw is 0 or pi/2 by contract; |sin| > 0.5 just tells the two apart without float equality
    return (box.width, box.length) if abs(math.sin(yaw)) > 0.5 else (box.length, box.width)


def _count(span: float, size: float, gap: float) -> int:
    return max(0, math.floor((span + gap) / (size + gap) + _EPS))


def _extent(n: int, size: float, gap: float) -> float:
    return n * size + max(0, n - 1) * gap


def _block(box: Box, yaw: float, nx: int, ny: int, gap: float, x0: float, y0: float) -> list[Placement]:
    dx, dy = footprint(box, yaw)
    return [
        Placement(x0 + i * (dx + gap) + dx / 2, y0 + j * (dy + gap) + dy / 2, yaw)
        for j in range(ny)
        for i in range(nx)
    ]


def grid(box: Box, pallet: Pallet, *, gap: float, yaw: float) -> list[Placement]:
    dx, dy = footprint(box, yaw)
    nx, ny = _count(pallet.length, dx, gap), _count(pallet.width, dy, gap)
    x0 = (pallet.length - _extent(nx, dx, gap)) / 2
    y0 = (pallet.width - _extent(ny, dy, gap)) / 2
    return _block(box, yaw, nx, ny, gap, x0, y0)


def best_grid(box: Box, pallet: Pallet, *, gap: float) -> list[Placement]:
    straight = grid(box, pallet, gap=gap, yaw=0.0)
    turned = grid(box, pallet, gap=gap, yaw=math.pi / 2)
    return turned if len(turned) > len(straight) else straight


def split_block(box: Box, pallet: Pallet, *, gap: float) -> list[Placement]:
    """0-degree columns from x=0, then 90-degree columns in the remaining strip; the best split wins."""
    dx0, dy0 = footprint(box, 0.0)
    dx1, dy1 = footprint(box, math.pi / 2)
    ny0, ny1 = _count(pallet.width, dy0, gap), _count(pallet.width, dy1, gap)
    best: tuple[int, int, int] | None = None
    # an orientation with no rows holds no boxes, so it gets no columns (centring must ignore it)
    for k in range(_count(pallet.length, dx0, gap) + 1 if ny0 else 1):
        m = _count(pallet.length - k * (dx0 + gap), dx1, gap) if ny1 else 0
        total = k * ny0 + m * ny1
        if best is None or total > best[0]:
            best = (total, k, m)
    _, k, m = best
    joint = gap if k and m else 0.0
    length_a = _extent(k, dx0, gap)
    x0 = (pallet.length - (length_a + joint + _extent(m, dx1, gap))) / 2
    first = _block(box, 0.0, k, ny0, gap, x0, (pallet.width - _extent(ny0, dy0, gap)) / 2)
    second = _block(
        box, math.pi / 2, m, ny1, gap, x0 + length_a + joint, (pallet.width - _extent(ny1, dy1, gap)) / 2
    )
    return first + second


def mirrored(placements: list[Placement], pallet: Pallet) -> list[Placement]:
    """Reflect across the pallet's mid-length line (interlock with the layer below)."""
    return [Placement(pallet.length - p.x, p.y, p.yaw) for p in placements]


def layer_issues(placements: list[Placement], box: Box, pallet: Pallet, *, tol_m: float) -> list[str]:
    issues: list[str] = []
    rects = []
    for i, p in enumerate(placements):
        dx, dy = footprint(box, p.yaw)
        r = (p.x - dx / 2, p.y - dy / 2, p.x + dx / 2, p.y + dy / 2)
        if r[0] < -tol_m or r[1] < -tol_m or r[2] > pallet.length + tol_m or r[3] > pallet.width + tol_m:
            issues.append(f"box {i} overhangs the pallet")
        rects.append(r)
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            a, b = rects[i], rects[j]
            if min(a[2], b[2]) - max(a[0], b[0]) > tol_m and min(a[3], b[3]) - max(a[1], b[1]) > tol_m:
                issues.append(f"boxes {i} and {j} overlap")
    return issues


PATTERNS = {"grid": best_grid, "split": split_block}
