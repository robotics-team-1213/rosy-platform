"""AMCL initial pose helpers. Zero covariance is ignored by the filter."""

from __future__ import annotations

import math

# 0.5 m std on x/y, ~15 deg on yaw. Off-diagonals stay zero.
_XY_VARIANCE = 0.25
_YAW_VARIANCE = math.radians(15.0) ** 2


def amcl_pose_covariance() -> list[float]:
    cov = [0.0] * 36
    cov[0] = _XY_VARIANCE
    cov[7] = _XY_VARIANCE
    cov[35] = _YAW_VARIANCE
    return cov
