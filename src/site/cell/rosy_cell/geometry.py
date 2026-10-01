"""Frames taught by three points: origin, a point on +x, a point on the +y side of the plane."""

from __future__ import annotations

import math
from dataclasses import dataclass

Vec3 = tuple[float, float, float]


class FrameError(ValueError):
    """The three taught points do not define a usable frame."""


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _length(a: Vec3) -> float:
    return math.sqrt(_dot(a, a))


def _unit(a: Vec3) -> Vec3:
    n = _length(a)
    return (a[0] / n, a[1] / n, a[2] / n)


@dataclass(frozen=True)
class Frame:
    origin: Vec3
    x_axis: Vec3
    y_axis: Vec3
    z_axis: Vec3

    @classmethod
    def from_three_points(
        cls, origin: Vec3, x_point: Vec3, plane_point: Vec3, *, min_span_m: float, min_angle_deg: float
    ) -> Frame:
        vx = _sub(x_point, origin)
        vp = _sub(plane_point, origin)
        if _length(vx) < min_span_m:
            raise FrameError("x_point is closer than min_span_m to the origin")
        if _length(vp) < min_span_m:
            raise FrameError("plane_point is closer than min_span_m to the origin")
        ex = _unit(vx)
        normal = _cross(ex, vp)
        if _length(normal) / _length(vp) < math.sin(math.radians(min_angle_deg)):
            raise FrameError("plane_point lies almost on the x axis")
        ez = _unit(normal)
        ey = _cross(ez, ex)
        return cls(origin=tuple(origin), x_axis=ex, y_axis=ey, z_axis=ez)

    def to_base(self, p: Vec3) -> Vec3:
        return tuple(
            self.origin[i] + self.x_axis[i] * p[0] + self.y_axis[i] * p[1] + self.z_axis[i] * p[2]
            for i in range(3)
        )

    def yaw_to_base(self, yaw: float) -> float:
        c, s = math.cos(yaw), math.sin(yaw)
        v = tuple(self.x_axis[i] * c + self.y_axis[i] * s for i in range(3))
        return math.atan2(v[1], v[0])

    def tilt_deg(self) -> float:
        return math.degrees(math.acos(max(-1.0, min(1.0, self.z_axis[2]))))
