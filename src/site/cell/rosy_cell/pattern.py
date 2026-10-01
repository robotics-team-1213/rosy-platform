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
