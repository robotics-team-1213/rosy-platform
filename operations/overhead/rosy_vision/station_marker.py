"""Approved planar marker geometry shared by relative and fixed-map station cameras."""
import math

import numpy as np

from core_common.protocol.station_charging import Pose2D
from .detect import detect_markers
from .project import MARKER_SIDE_BAND, MAX_MARKER_SIDE_RATIO, MIN_MARKER_SIDE_PX


def validate_marker_calibration(calibration, matrix, *, plane):
    if not all(isinstance(value, str) and value.strip() for value in (
            calibration.station_id, calibration.source_id, calibration.source_epoch, calibration.revision)):
        raise ValueError('STATION_CALIBRATION_ID_REQUIRED')
    if (type(calibration.marker_id) is not int or calibration.marker_id < 0
            or not isinstance(calibration.marker_mount, Pose2D)):
        raise ValueError('STATION_MARKER_SPEC_REQUIRED')
    numbers = (*matrix, calibration.marker_side_m, calibration.uncertainty_m, calibration.uncertainty_rad)
    if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in numbers):
        raise ValueError('STATION_CALIBRATION_NOT_FINITE')
    if (len(matrix) != 9 or calibration.marker_side_m <= 0
            or min(calibration.uncertainty_m, calibration.uncertainty_rad) < 0):
        raise ValueError('STATION_CALIBRATION_INVALID')
    if (calibration.plane != plane or calibration.lens_rectified is not True or calibration.approved is not True
            or abs(np.linalg.det(np.asarray(matrix).reshape(3, 3))) < 1e-12):
        raise ValueError('STATION_CALIBRATION_NOT_APPROVED')


def marker_pose(jpeg, *, marker_id, marker_side_m, marker_mount, matrix, detected=None):
    quad = (detect_markers(jpeg) if detected is None else detected).get(marker_id)
    if quad is None:
        return None
    pixels = np.asarray(quad, dtype=float)
    pixel_sides = np.linalg.norm(pixels - np.roll(pixels, 1, axis=0), axis=1)
    if min(pixel_sides) < MIN_MARKER_SIDE_PX or max(pixel_sides) / min(pixel_sides) > MAX_MARKER_SIDE_RATIO:
        return None
    homogeneous = np.column_stack((pixels, np.ones(4))) @ np.asarray(matrix).reshape(3, 3).T
    if np.any(np.abs(homogeneous[:, 2]) < 1e-12):
        return None
    corners = homogeneous[:, :2] / homogeneous[:, 2:]
    sides = np.linalg.norm(corners - np.roll(corners, 1, axis=0), axis=1)
    lo, hi = MARKER_SIDE_BAND
    if not np.isfinite(corners).all() or any(not lo <= side / marker_side_m <= hi for side in sides):
        return None
    centre = corners.mean(axis=0)
    front = (corners[0] + corners[1]) / 2 - centre
    raw = math.atan2(front[1], front[0]) - marker_mount.yaw
    heading = math.atan2(math.sin(raw), math.cos(raw))
    c, s = math.cos(heading), math.sin(heading)
    return Pose2D(x=float(centre[0]-c*marker_mount.x+s*marker_mount.y),
                  y=float(centre[1]-s*marker_mount.x-c*marker_mount.y), yaw=heading)
