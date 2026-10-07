"""D-468 image-bound selected boundary geometry with its stated projection uncertainty.

Boundaries are the drivable (inner) edge of the painted lines: the keeper's fitted paint
centre moved half the paint width (PAINT_HALF_WIDTH_M) toward the lane.

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
import json
import math

import numpy as np

from .camera_extrinsic import FINE_STEPS, PC_FINE_STEPS

#: Half the painted line width. The keeper fits the paint centre; the payload sends the
#: paint's inner (drivable) edge, so each boundary moves this far toward the lane. 260919
#: STL straights: tape 25.0 mm, centres 185 mm apart (lane_half_width_m 0.0925), the map
#: bundle's own lane_graph.py clearance basis. STL nominal, unmeasured: a tape measurement
#: of the physical mat replaces it. Tested against the STL; node parameter lane_paint_half_width_m.
PAINT_HALF_WIDTH_M = 0.0125
#: Lateral error of the lane edge detector in image pixels on the Gazebo camera (547b2d509).
#: Real grounds take theirs from the profile key detector_lateral_px.
GAZEBO_DETECTOR_LATERAL_PX = 2.0
#: The receiver extrapolates a boundary this far past its observed support
#: (core_features.line_follow.lane_return_evidence.LaneReturnEvidence.MAX_EXTRAPOLATION_M).
RECEIVER_EXTRAPOLATION_M = 0.3
#: Roll levels sampled across +-its bound (odd, so 0 is one). The re-review's 41-201 level
#: scan found the worst roll interior, at most 0.3 % above the corners-and-centre value.
ROLL_LEVELS = 7
#: Raise on the sampled worst for roll between levels: the 0.3 % gap above with 3 levels,
#: times about seven for safety. Checked by the 21-level test truths.
SAMPLING_MARGIN = 0.02


def _real(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def geometry_error(profile, intervals, *, overridden=()):
    """(pitch_rad, height_m, roll_rad, detector_px) error bounds of the ground from ``profile``, or None.

    ``intervals`` are the accepted camera_profile record's (None = no record, the URDF
    nominal file stands). A record's bands are fit half-widths; each is floored at one
    grid step of the fit, intervals["fit_step"]: a camera_extrinsic grid fit states its
    steps (one without fit_step predates them and ran the robot grid, FINE_STEPS), and a
    continuous fit (camera_board/1) states zero steps. Its bands are only the scatter of its
    views, blind to error they share (distortion, intrinsics, print scale, elevation), so a
    record with any step finer than the PC grid (PC_FINE_STEPS) must also state
    intervals["systematic"] {pitch_deg, roll_deg, height_m} from an independent truth check.
    A stated systematic is added to each band, whatever the steps. A band that is not positive,
    or a fit_step or systematic that is not three non-negative reals, is refused. The ground ignores roll, so a
    record's fitted roll is error too. An operator override of pitch or height states no
    error: None.
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
    step = intervals.get("fit_step", FINE_STEPS) if isinstance(intervals, dict) else None
    if not isinstance(band, dict) or not isinstance(step, dict):
        return None
    step = [step.get(k) for k in ("pitch_deg", "roll_deg", "height_m")]
    if not all(_real(v) and v >= 0 for v in step):
        return None
    pitch_step, roll_step, height_step = step
    keys = ("pitch_deg", "roll_deg", "height_m")
    shared = intervals.get("systematic")
    if shared is None and not any(s < PC_FINE_STEPS[k] for s, k in zip(step, keys)):
        shared = dict.fromkeys(keys, 0.)
    shared = [shared.get(k) for k in keys] if isinstance(shared, dict) else [None]
    if not all(_real(v) and v >= 0 for v in shared):
        return None
    pitch_shared, roll_shared, height_shared = shared
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
        height = max(height, height_step)+height_shared
    return (math.radians(max(pitch, pitch_step)+pitch_shared), float(height),
            abs(roll)+math.radians(max(roll_band, roll_step)+roll_shared), float(px))


def _ray(h, pitch, x, y):
    """Normalized image coordinates (right, down) of the floor point x ahead of the lens, y aside."""
    depth = x*math.cos(pitch)+h*math.sin(pitch)
    return y/depth, (h*math.cos(pitch)-x*math.sin(pitch))/depth


def _floor(h, pitch, roll, a, b):
    """Floor points (x, y) a camera at (h, pitch, roll) sees along normalized rays (a, b); NaN above the horizon."""
    a, b = a*np.cos(roll)+b*np.sin(roll), -a*np.sin(roll)+b*np.cos(roll)
    denominator = np.sin(pitch)+b*np.cos(pitch)
    depth = np.where(denominator > 0, h/np.where(denominator > 0, denominator, 1.), np.nan)
    return depth*(np.cos(pitch)-b*np.sin(pitch)), a*depth


def projection_uncertainty_m(ground, error, segments):
    """Largest lateral error of the boundaries ``segments`` over the x range the receiver uses.

    Each segment is the two read ends ((x, y), (x, y)) on the floor, x ahead of the lens.
    The read ends are imaged with the assumed geometry, each end's image column moved by
    +-the detector's pixels (row error is not modelled: a column shift already moves a steep
    line the most), and read back with pitch and height at -bound/0/+bound and roll at
    ROLL_LEVELS levels across +-bound (the error is not monotone in roll: its worst case can
    be interior). The true line through them is compared with the read one at both ends of
    the support widened by RECEIVER_EXTRAPOLATION_M (lines differ linearly, so the ends hold
    the maximum), as the vertical difference (not smaller than the perpendicular one), and
    the worst is raised by SAMPLING_MARGIN for the roll between sampled levels.
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
    sp, sh, sr, su1, su2 = (v.ravel() for v in np.meshgrid(
        (-1, 0, 1), (-1, 0, 1), np.linspace(-1, 1, ROLL_LEVELS), (-1, 1), (-1, 1), indexing="ij"))
    hs, pitches, rolls = h+sh*height_e, th+sp*pitch_e, sr*roll_e
    worst = 0.
    for ends in segments:
        (x1, y1), (x2, y2) = ends
        slope = (y2-y1)/(x2-x1)
        (a1, b1), (a2, b2) = (_ray(h, th, x, y) for x, y in ends)
        tx1, ty1 = _floor(hs, pitches, rolls, a1+su1*px/f, b1)
        tx2, ty2 = _floor(hs, pitches, rolls, a2+su2*px/f, b2)
        span = tx2-tx1
        if not (np.all(np.isfinite(span)) and np.all(np.abs(span) > 1e-9)):
            return 1.0
        true_slope = (ty2-ty1)/span
        for x in (min(x1, x2)-RECEIVER_EXTRAPOLATION_M, max(x1, x2)+RECEIVER_EXTRAPOLATION_M):
            worst = max(worst, float(np.max(np.abs(y1+slope*(x-x1)-(ty1+true_slope*(x-tx1))))))
    return min(worst*(1+SAMPLING_MARGIN), 1.0)


def containment_payload(keeper, ground, *, stamp, source, camera_x, geometry_bounds=None,
                        paint_half_width_m=PAINT_HALF_WIDTH_M):
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
    # The imaged paint segments above set the uncertainty; the corridor edge is the paint's
    # inner side: half the paint width inward, perpendicular to the line.
    for b in boundaries:
        b["intercept_m"] -= (1 if b["side"] == "left" else -1)*paint_half_width_m*math.hypot(1, b["slope"])
    edges = {b["side"]: b["intercept_m"] for b in boundaries}
    if len(edges) == 2 and edges["left"] <= edges["right"]:
        boundaries = []
    return dict(stamp=float(stamp), geometry_id=identity, ground_source=source,
                uncertainty_m=uncertainty, boundaries=boundaries)
