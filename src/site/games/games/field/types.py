"""Pose and velocity on the pitch. No camera, no ROS."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Pose2D:
    x: float
    y: float
    yaw: float


@dataclass(frozen=True)
class Twist:
    linear: float
    angular: float


ZERO = Twist(0.0, 0.0)
