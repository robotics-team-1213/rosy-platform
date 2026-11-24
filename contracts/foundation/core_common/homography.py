"""Four-point homography (pixel quad to metres). Pure math, no OpenCV."""

from __future__ import annotations

import math
from dataclasses import dataclass

from core_common.calibration_math import fit_homography_dlt

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


def fit(src_px: tuple[Point, ...] | list[Point], dst_m: tuple[Point, ...] | list[Point]) -> Homography:
    if len(src_px) != 4 or len(dst_m) != 4:
        raise ValueError("homography needs four corner pairs")
    try:
        return Homography(h=tuple(fit_homography_dlt(src_px, dst_m)))
    except ValueError as exc:
        raise ValueError("degenerate homography") from exc
