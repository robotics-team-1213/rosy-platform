"""Ideal fixed-radius arc sensitivity to pivot heading error; no sensor or controller model.

Usage: python simulate.py PIVOT_METRICS.jsonl
The independent Gazebo GT in the input is evaluation data, never a product pose.
"""
import hashlib
import json
import math
import sys
from pathlib import Path

RADIUS_M = 0.2514
ARC_M = 0.3722  # NE ring_n segment in the recorded D-520 run
STEP_M = 0.0001


def radial_error_m(heading_error_deg, distance_m):
    """Start on the map circle; follow an ideal equal-radius circle at a wrong tangent."""
    yaw = math.pi / 2 + math.radians(heading_error_deg)
    angle = yaw + distance_m / RADIUS_M
    x = RADIUS_M + RADIUS_M * (math.sin(angle) - math.sin(yaw))
    y = RADIUS_M * (math.cos(yaw) - math.cos(angle))
    return math.hypot(x, y) - RADIUS_M


def score(heading_error_deg):
    errors = [radial_error_m(heading_error_deg, i * STEP_M)
              for i in range(round(ARC_M / STEP_M) + 1)]
    crossing = next((i * STEP_M for i, err in enumerate(errors) if abs(err) >= 0.025), None)
    return {"first_25mm_m": crossing, "max_abs_radial_m": max(map(abs, errors)),
            "at_100mm_m": radial_error_m(heading_error_deg, 0.1)}


def main(path):
    assert max(abs(radial_error_m(0, s)) for s in (0, 0.1, ARC_M)) < 1e-12
    assert radial_error_m(10, 0.1) < 0 < radial_error_m(-10, 0.1)
    raw = path.read_bytes()
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    base = [row for row in rows if row["turn_place_id"] == "NE" and row["fleet_turn_deg"] == -97.4]
    if len(base) != 4:
        raise ValueError("expected four independent NE baseline runs")
    return {"source_sha256": hashlib.sha256(raw).hexdigest(), "radius_m": RADIUS_M, "arc_m": ARC_M,
            "model": "ideal_equal_radius_no_feedback", "runs": [
                {"run": row["run"], "measured_gt_heading_error_deg": row["arc_heading_minus_map_tangent_deg"],
                 "ideal_baseline": score(row["arc_heading_minus_map_tangent_deg"])} for row in base],
            "synthetic_pose_heading_error": [
                {"error_deg": err, **score(err)} for err in (-10, -5, -3, 0, 3, 5, 10)]}


if __name__ == "__main__":
    print(json.dumps(main(Path(sys.argv[1])), indent=2, sort_keys=True))
