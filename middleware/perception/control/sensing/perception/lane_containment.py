"""D-468 image-bound selected boundary geometry with its stated projection uncertainty.

uncertainty_m bounds the lateral error of a selected boundary over every x the receiver
uses it at. It comes only from stated error bounds: a camera_profile record's score bands
(D-47), or for the URDF nominal profile the conservative bounds camera_nominal.yaml
carries (D-397). Without one it stays None and the D-468 receiver refuses.

The ground model this producer runs on is never promoted: the line observer labels it
from camera_ground_source, so a record-backed ground is still sent as NOMINAL and the
CORE driver hold (D-344) still applies. CALIBRATED is never produced (user decision
2026-10-06).
"""
import hashlib
import itertools
import json
import math

from .camera_extrinsic import FINE_HEIGHT_STEP_M, FINE_PITCH_STEP_DEG, FINE_ROLL_STEP_DEG

#: Lateral error of the lane edge detector in image pixels on the Gazebo camera (547b2d509).
#: Real grounds take theirs from the profile key detector_lateral_px.
GAZEBO_DETECTOR_LATERAL_PX = 2.0
#: The receiver extrapolates a boundary this far past its observed support
#: (core_features.line_follow.lane_return_evidence.LaneReturnEvidence.MAX_EXTRAPOLATION_M).
RECEIVER_EXTRAPOLATION_M = 0.3


def _real(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def geometry_error(profile, intervals, *, overridden=()):
    """(pitch_rad, height_m, roll_rad, detector_px) error bounds of the ground from ``profile``, or None.

    ``intervals`` are the accepted camera_profile record's (None = no record, the URDF
    nominal file stands). A record's bands are fit-score half-widths rounded by the fit;
    each is floored at one fine search step of the fit (camera_extrinsic), and a band that
    is not positive is refused. The ground ignores roll, so a record's fitted roll is error
    too. An operator override of pitch or height states no error: None.
    """
    if {"pitch_rad", "height_m"} & set(overridden):
        return None
    px = profile.get("detector_lateral_px")
    if not (_real(px) and px > 0):
        return None
    if intervals is None:
        bounds = [profile.get(k) for k in ("pitch_uncertainty_rad", "height_uncertainty_m", "roll_uncertainty_rad")]
        if not all(_real(b) and b >= 0 for b in bounds):
            return None
        return (*(float(b) for b in bounds), float(px))
    band = intervals.get("uncertainty") if isinstance(intervals, dict) else None
    if not isinstance(band, dict):
        return None
    pitch, roll_band, roll, height = band.get("pitch_deg"), band.get("roll_deg"), profile.get("roll_rad"), band.get("height_m")
    if not all(_real(v) for v in (pitch, roll_band, roll)) or min(pitch, roll_band) <= 0:
        return None
    if height is None:
        # A record that kept the base height (height_source base) has no height band.
        height = profile.get("height_uncertainty_m")
        if not (_real(height) and height >= 0):
            return None
    elif not (_real(height) and height > 0):
        return None
    else:
        height = max(height, FINE_HEIGHT_STEP_M)
    return (math.radians(max(pitch, FINE_PITCH_STEP_DEG)), float(height),
            abs(roll)+math.radians(max(roll_band, FINE_ROLL_STEP_DEG)), float(px))


def _ray(h, pitch, x, y):
    """Normalized image coordinates (right, down) of the floor point x ahead of the lens, y aside."""
    depth = x*math.cos(pitch)+h*math.sin(pitch)
    return y/depth, (h*math.cos(pitch)-x*math.sin(pitch))/depth


def _floor(h, pitch, roll, a, b):
    """The floor point a camera at (h, pitch, roll) sees along normalized ray (a, b), or None."""
    a, b = a*math.cos(roll)+b*math.sin(roll), -a*math.sin(roll)+b*math.cos(roll)
    denominator = math.sin(pitch)+b*math.cos(pitch)
    if denominator <= 0:
        return None
    depth = h/denominator
    return depth*(math.cos(pitch)-b*math.sin(pitch)), a*depth


def projection_uncertainty_m(ground, error, segments):
    """Largest lateral error of the boundaries ``segments`` over the x range the receiver uses.

    Each segment is the two read ends ((x, y), (x, y)) on the floor, x ahead of the lens.
    The read ends are imaged with the assumed geometry, each moved by the detector's pixels,
    and read back with every corner (and centre) of the pitch/height/roll bounds; the true
    line through them is compared with the read one at both ends of the support widened by
    RECEIVER_EXTRAPOLATION_M (lines differ linearly, so the ends hold the maximum). The
    vertical difference is used, which is not smaller than the perpendicular one.
    Not modelled: camera yaw (the receiver's own odometry-matched heading carries it, and
    D-47 found a residual of about -0.2 deg), lens distortion (the NOMINAL intrinsics are
    undistorted pinhole fits, RMS 1.08 px, inside the detector pixels) and fx error (fx is
    fixed by the profile; a scale error moves y by the same share as height, far below the
    height bound). A ray that may clear the true horizon gives 1.0, the contract maximum,
    which the receiver refuses as excessive. No segments: the detector pixels at max range.
    """
    pitch_e, height_e, roll_e, px = error
    h, th, f = ground.height_m, ground.pitch_rad, ground.focal_px
    if not segments:
        return px*(ground.max_range_m*math.cos(th)+h*math.sin(th))/f
    worst = 0.
    for ends in segments:
        (x1, y1), (x2, y2) = ends
        slope = (y2-y1)/(x2-x1)
        rays = [_ray(h, th, x, y) for x, y in ends]
        extent = (min(x1, x2)-RECEIVER_EXTRAPOLATION_M, max(x1, x2)+RECEIVER_EXTRAPOLATION_M)
        for sp, sh, sr, su1, su2 in itertools.product((-1, 0, 1), (-1, 0, 1), (-1, 0, 1), (-1, 1), (-1, 1)):
            true = [_floor(h+sh*height_e, th+sp*pitch_e, sr*roll_e, a+su*px/f, b)
                    for (a, b), su in zip(rays, (su1, su2))]
            if None in true or abs(true[1][0]-true[0][0]) < 1e-9:
                return 1.0
            (tx1, ty1), (tx2, ty2) = true
            true_slope = (ty2-ty1)/(tx2-tx1)
            for x in extent:
                worst = max(worst, abs(y1+slope*(x-x1)-(ty1+true_slope*(x-tx1))))
    return min(worst, 1.0)


def containment_payload(keeper, ground, *, stamp, source, camera_x, geometry_bounds=None):
    if ground is None or source not in ("NOMINAL", "CALIBRATED", "GAZEBO"):
        return None
    geometry = [source, camera_x, ground.height_m, ground.pitch_rad,
                ground.focal_px, ground.principal_x, ground.principal_y, ground.max_range_m]
    identity = hashlib.sha256(json.dumps(geometry, allow_nan=False).encode()).hexdigest()
    boundaries = []
    for edge in keeper.get("boundaries", []):
        if edge.get("selected") is not True:
            continue
        first, last = edge["ends_m"]
        dx = float(last[0])-float(first[0])
        if abs(dx) < .01:
            continue
        slope = (float(last[1])-float(first[1]))/dx
        intercept = float(first[1])-slope*float(first[0])
        if not math.isfinite(slope) or not math.isfinite(intercept):
            continue
        boundaries.append(dict(side=edge["side"], slope=slope, intercept_m=intercept,
            observed_x_min_m=min(float(first[0]), float(last[0])),
            observed_x_max_m=max(float(first[0]), float(last[0]))))
    # GAZEBO (allow_simulation_ground only): exact sim geometry, only the detector's pixels.
    # NOMINAL/CALIBRATED without a stated geometry error stay None: the receiver must not
    # replace that null with a safe tolerance. Segments are taken from the lens (x - camera_x).
    error = (0., 0., 0., GAZEBO_DETECTOR_LATERAL_PX) if source == "GAZEBO" else geometry_bounds
    uncertainty = None
    if error is not None:
        segments = [tuple((x-camera_x, b["slope"]*x+b["intercept_m"])
                          for x in (b["observed_x_min_m"], b["observed_x_max_m"])) for b in boundaries]
        uncertainty = projection_uncertainty_m(ground, error, segments)
    return dict(stamp=float(stamp), geometry_id=identity, ground_source=source,
                uncertainty_m=uncertainty, boundaries=boundaries)
