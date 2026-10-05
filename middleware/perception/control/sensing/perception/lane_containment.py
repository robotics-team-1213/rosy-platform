"""D-468 image-bound selected boundary geometry; no inferred calibration quality."""
import hashlib
import json
import math


def containment_payload(keeper, ground, *, stamp, source, camera_x):
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
    # No bound on real projection error has been established by the nominal rig.
    # The receiver must not silently replace this null with a safe tolerance.
    return dict(stamp=float(stamp), geometry_id=identity, ground_source=source,
                uncertainty_m=None, boundaries=boundaries)
