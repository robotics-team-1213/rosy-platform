"""Ground projection and centre pursuit geometry for drivable steering."""

import math

import numpy as np

ROW_BAND_M = 0.03
MAX_TARGET_CURVATURE = 5.0


def _row_x(rows, ground, x_offset):
    """base_link x of the floor at each image row (inf at or above the horizon)."""
    ray = ground.pitch_rad + np.arctan((np.asarray(rows, float) - ground.principal_y) / ground.focal_px)
    with np.errstate(divide="ignore"):
        return np.where(ray > 0.0, ground.height_m / np.tan(np.maximum(ray, 1e-9)), np.inf) + x_offset


def _col_y(cols, rows, ground):
    """base_link y (left +) of image columns at those rows (GroundPlane.lateral)."""
    denominator = (ground.focal_px * math.sin(ground.pitch_rad)
                   + (np.asarray(rows, float) - ground.principal_y) * math.cos(ground.pitch_rad))
    return (ground.principal_x - np.asarray(cols, float)) * ground.height_m / np.maximum(denominator, 1e-9)


def _centre_target(xs, centre, lookahead):
    """(point, curvature, band). Station is arc length `lookahead` along the centre.
    Curvature is that span's heading change when it bends with the chord and harder;
    the chord wins for a return onto a straighter centre. The point is on that arc.
    """
    xs, centre = np.asarray(xs, float), np.asarray(centre, float)
    order = np.argsort(xs)
    keep = np.isfinite(xs[order]) & np.isfinite(centre[order]) & (xs[order] > 0.0)
    order, band = order[keep], np.zeros(xs.shape, bool)
    if order.size == 0:
        return None, 0.0, band
    sx, sy = xs[order], centre[order]
    px, py = np.concatenate(([0.0], sx)), np.concatenate(([0.0], sy))
    arc = np.concatenate(([0.0], np.cumsum(np.hypot(np.diff(px), np.diff(py)))))
    reach = min(float(lookahead), float(arc[-1]))
    near = np.abs(arc[1:] - reach) <= ROW_BAND_M
    if not near.any():
        near = np.zeros(sx.shape, bool)
        near[int(np.argmin(np.abs(arc[1:] - reach)))] = True
    tx, ty = float(np.median(sx[near])), float(np.median(sy[near]))
    d2 = tx * tx + ty * ty
    k_chord = 0.0 if d2 < 1e-6 else 2.0 * ty / d2
    heading = np.arctan2(np.diff(py), np.diff(px))
    walked = heading[arc[1:] <= reach + 1e-6]
    k_path = 0.0
    if walked.size >= 2 and reach > 1e-3:
        k_path = math.atan2(math.sin(walked[-1] - walked[0]), math.cos(walked[-1] - walked[0])) / reach
    k = k_path if abs(k_path) > abs(k_chord) and k_path * k_chord >= 0.0 else k_chord
    k = float(max(-MAX_TARGET_CURVATURE, min(MAX_TARGET_CURVATURE, k)))
    point = (reach, ty) if abs(k) < 1e-3 else (
        math.sin(k * reach) / k, (1.0 - math.cos(k * reach)) / k)
    band[order[near]] = True
    return point, k, band
