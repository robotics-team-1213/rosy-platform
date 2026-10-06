"""D-468 image-bound selected boundary geometry; no inferred calibration quality."""
import hashlib
import json
import math

#: GAZEBO ground only: heuristic edge-detector lateral error, not a measured bound.
GAZEBO_DETECTOR_LATERAL_PX = 2.0


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
    # GAZEBO (allow_simulation_ground only): the sim camera's height, pitch and intrinsics are
    # exact, so the error left is the edge detector's, taken as 2 px lateral at the farthest range.
    uncertainty = (GAZEBO_DETECTOR_LATERAL_PX*float(ground.max_range_m)/float(ground.focal_px)
                   if source == "GAZEBO" else None)
    return dict(stamp=float(stamp), geometry_id=identity, ground_source=source,
                uncertainty_m=uncertainty, boundaries=boundaries)
