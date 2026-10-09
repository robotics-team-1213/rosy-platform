"""Audit sampled ring poses against paint centre circles using the SIM URDF hull."""

import argparse
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tools" / "calibration"))
import urdf_nominal as urdf  # noqa: E402

CENTER = (-0.3357, 0.0011)
INNER = 0.155
OUTER = 0.345
SECTORS = (("ring_s", -137.7, -52.5), ("ring_e", -52.5, 52.3), ("ring_n", 52.3, 137.1))


def hull(points):
    ordered = sorted(set(points))
    if len(ordered) < 3:
        raise ValueError("degenerate footprint")

    def cross(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    lower, upper = [], []
    for point in ordered:
        while len(lower) > 1 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    for point in reversed(ordered):
        while len(upper) > 1 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]


def sim_footprint():
    links, joints = urdf.expand(is_sim=True)
    poses = urdf.frames(joints)
    points = []
    for link in links:
        for spec in link["collisions"]:
            transform = urdf._mul(poses[link["name"]], urdf._matrix(spec["xyz"], spec["rpy"]))
            points.extend(tuple(urdf._apply(transform, point)[:2]) for point in urdf._shape_points(spec))
    result = hull(points)
    radius = max(math.hypot(x, y) for x, y in result)
    if abs(radius - urdf.nominal()["footprint"]["rotation_radius_sim_box_m"]) > 1e-5:
        raise ValueError("SIM footprint does not match nominal rotation radius")
    return result, radius


def segment_distance(point, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = max(0.0, min(1.0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / (dx * dx + dy * dy)))
    return math.hypot(point[0] - a[0] - t * dx, point[1] - a[1] - t * dy)


def audit(rows, body):
    result = {name: [] for name, _, _ in SECTORS}
    previous = None
    max_vertex_step = 0.0
    for row in rows:
        if not str(row.get("reason") or "").startswith("lane_arc") or not row.get("gt"):
            continue
        x, y, yaw = row["gt"]
        if not all(math.isfinite(v) for v in (x, y, yaw)):
            raise ValueError("non-finite GT pose")
        angle = math.degrees(math.atan2(y - CENTER[1], x - CENTER[0]))
        name = next((name for name, low, high in SECTORS if low <= angle < high), None)
        if name is None:
            continue
        c, s = math.cos(yaw), math.sin(yaw)
        polygon = [(x + c * bx - s * by, y + s * bx + c * by) for bx, by in body]
        if previous is not None:
            max_vertex_step = max(max_vertex_step, *(math.dist(a, b) for a, b in zip(previous, polygon)))
        previous = polygon
        inner_gap = min(segment_distance(CENTER, a, b) for a, b in zip(polygon, polygon[1:] + polygon[:1])) - INNER
        outer_gap = OUTER - max(math.dist(CENTER, p) for p in polygon)
        result[name].append((inner_gap, outer_gap, row.get("sim_t"), [x, y, yaw]))
    if any(not values for values in result.values()):
        raise ValueError("missing ring sector GT")
    return {
        "sim_footprint_vertices": len(body),
        "maximum_sampled_vertex_step_m": round(max_vertex_step, 6),
        "continuous_lane_containment_proof": False,
        "sectors": {name: {
            "samples": len(values),
            "minimum_inner_paint_centre_gap_m": round(min(v[0] for v in values), 6),
            "minimum_outer_paint_centre_gap_m": round(min(v[1] for v in values), 6),
            "samples_crossing_either_paint_centre": sum(min(v[:2]) < 0 for v in values),
            "worst_sample": min(values, key=lambda v: min(v[:2]))[2:],
        } for name, values in result.items()},
    }


def selfcheck():
    assert hull([(0, 0), (1, 0), (1, 1), (0, 1), (0.5, 0.5)]) == [(0, 0), (1, 0), (1, 1), (0, 1)]
    assert segment_distance((0, 0), (1, -1), (1, 1)) == 1.0


if __name__ == "__main__":
    selfcheck()
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path, help="extracted closed-loop run directory")
    args = parser.parse_args()
    body, radius = sim_footprint()
    report = {"sim_footprint_radius_m": round(radius, 6), "runs": {}}
    for model in ("threshold", "v11"):
        path = args.root / f"loop_{model}" / "lap_d567_baseline" / "log.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        report["runs"][model] = audit(rows, body)
    print(json.dumps(report, indent=2))
