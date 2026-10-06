"""D-468 image-bound selected boundary geometry with its stated projection uncertainty.

uncertainty_m bounds the lateral error of a selected boundary. It comes only from
stated error bounds: a camera_profile record's score bands (D-47), or for the URDF
nominal profile the largest measured deviation it carries (camera_nominal.yaml,
D-397). Without one it stays None and the D-468 receiver refuses.
"""
import hashlib
import json
import math

#: Lateral error of the lane edge detector in image pixels (the GAZEBO declaration).
DETECTOR_LATERAL_PX = 2.0


def _real(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def geometry_error(profile, intervals, *, overridden=()):
    """(pitch_rad, height_m, roll_rad) error bounds of the ground built from ``profile``, or None.

    ``intervals`` are the accepted camera_profile record's (None = no record, the URDF
    nominal file stands). The ground ignores roll, so a record's fitted roll is error too.
    An operator override of pitch or height states no error: None.
    """
    if {"pitch_rad", "height_m"} & set(overridden):
        return None
    if intervals is None:
        bounds = [profile.get(k) for k in ("pitch_uncertainty_rad", "height_uncertainty_m", "roll_uncertainty_rad")]
        return tuple(float(b) for b in bounds) if all(_real(b) and b >= 0 for b in bounds) else None
    band = intervals.get("uncertainty") if isinstance(intervals, dict) else None
    if not isinstance(band, dict):
        return None
    # A record that kept the base height (height_source base) has no height band.
    height = band.get("height_m")
    height = profile.get("height_uncertainty_m") if height is None else height
    pitch, roll_band, roll = band.get("pitch_deg"), band.get("roll_deg"), profile.get("roll_rad")
    if not all(_real(v) for v in (pitch, roll_band, roll, height)) or min(pitch, roll_band, height) < 0:
        return None
    return math.radians(pitch), float(height), abs(roll)+math.radians(roll_band)


def projection_uncertainty_m(ground, error, *, far_m, lateral_m):
    """Lateral error bound of a floor point read ``far_m`` ahead of the lens, ``lateral_m`` aside.

    A pixel reads y proportional to h/sin(beta), beta = atan(h/d) its ray's depression, so a true
    pitch off by dp and height off by dh read y*(h+dh)/h*sin(beta)/sin(beta+dp): the worst corner,
    exact (the NOMINAL bounds are too large for a first-order term). Roll moves the point by at
    most droll*max(h, d*sin(pitch)); the detector's pixels count at the depth d*cos(pitch) +
    h*sin(pitch). The terms are summed (a bound). A ray that may clear the true horizon has no
    bound: 1.0, the contract maximum, which the receiver refuses as excessive.
    """
    pitch_e, height_e, roll_e = error
    h, th, d = ground.height_m, ground.pitch_rad, max(float(far_m), 0.)
    beta = math.atan2(h, d)
    if beta-pitch_e <= 0:
        return 1.0
    scale = max(abs(1-(h+sh*height_e)/h*math.sin(beta)/math.sin(beta+sp*pitch_e))
                for sh in (-1, 1) for sp in (-1, 1))
    depth = d*math.cos(th)+h*math.sin(th)
    return min(1.0, DETECTOR_LATERAL_PX*depth/ground.focal_px + abs(lateral_m)*scale
               + roll_e*max(h, d*math.sin(th)))


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
    # replace that null with a safe tolerance. Evaluated at the farthest observed point
    # (base_link x less the lens offset) and the widest boundary offset, where it is largest.
    error = (0., 0., 0.) if source == "GAZEBO" else geometry_bounds
    uncertainty = None
    if error is not None:
        far = max((b["observed_x_max_m"]-camera_x for b in boundaries), default=ground.max_range_m)
        lateral = max((abs(b["slope"]*x+b["intercept_m"]) for b in boundaries
                       for x in (b["observed_x_min_m"], b["observed_x_max_m"])), default=0.)
        uncertainty = projection_uncertainty_m(ground, error, far_m=far, lateral_m=lateral)
    return dict(stamp=float(stamp), geometry_id=identity, ground_source=source,
                uncertainty_m=uncertainty, boundaries=boundaries)
