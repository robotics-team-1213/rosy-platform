"""Pitch corners for the homography. The math lives in core_common.homography (no OpenCV)."""

from __future__ import annotations

from core_common.homography import Homography, Point, fit
from games.field.geometry import Field

__all__ = ["Homography", "Point", "field_corners", "fit"]


def field_corners(field: Field) -> tuple[Point, Point, Point, Point]:
    half_l = field.length_m / 2
    half_w = field.width_m / 2
    return (
        (-half_l, -half_w),
        (half_l, -half_w),
        (half_l, half_w),
        (-half_l, half_w),
    )
