"""Pixel quad to pitch metres. No OpenCV."""

from __future__ import annotations

import math
from dataclasses import dataclass

from games.field.geometry import Field

Point = tuple[float, float]


@dataclass(frozen=True)
class Homography:
    h: tuple[float, ...]  # row-major 3x3, h33 == 1

    def apply(self, u: float, v: float) -> Point:
        h = self.h
        w = h[6] * u + h[7] * v + h[8]
        if abs(w) < 1e-12:
            raise ValueError("homography w is zero")
        x = (h[0] * u + h[1] * v + h[2]) / w
        y = (h[3] * u + h[4] * v + h[5]) / w
        return x, y

    def yaw(self, a: Point, b: Point) -> float:
        x0, y0 = self.apply(*a)
        x1, y1 = self.apply(*b)
        return math.atan2(y1 - y0, x1 - x0)


def field_corners(field: Field) -> tuple[Point, Point, Point, Point]:
    half_l = field.length_m / 2
    half_w = field.width_m / 2
    return (
        (-half_l, -half_w),
        (half_l, -half_w),
        (half_l, half_w),
        (-half_l, half_w),
    )


def fit(src_px: tuple[Point, ...] | list[Point], dst_m: tuple[Point, ...] | list[Point]) -> Homography:
    if len(src_px) != 4 or len(dst_m) != 4:
        raise ValueError("homography needs four corner pairs")
    rows: list[list[float]] = []
    rhs: list[float] = []
    for (u, v), (x, y) in zip(src_px, dst_m):
        rows.append([u, v, 1.0, 0.0, 0.0, 0.0, -x * u, -x * v])
        rhs.append(x)
        rows.append([0.0, 0.0, 0.0, u, v, 1.0, -y * u, -y * v])
        rhs.append(y)
    solved = _gauss(rows, rhs)
    return Homography(h=tuple(solved + [1.0]))


def _gauss(matrix: list[list[float]], vector: list[float]) -> list[float]:
    n = len(vector)
    aug = [row[:] + [vector[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) < 1e-12:
            raise ValueError("degenerate homography")
        aug[col], aug[pivot] = aug[pivot], aug[col]
        scale = aug[col][col]
        for j in range(col, n + 1):
            aug[col][j] /= scale
        for row in range(n):
            if row == col:
                continue
            factor = aug[row][col]
            for j in range(col, n + 1):
                aug[row][j] -= factor * aug[col][j]
    return [aug[i][n] for i in range(n)]
