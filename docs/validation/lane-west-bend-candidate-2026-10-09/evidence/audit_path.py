"""Sampled SIM footprint distance to the west lane paint-centre proxy and ring."""

import argparse
import json
import math
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "docs/validation/lane-loop-failure-audit-2026-10-09/evidence"))
from ring_footprint import audit as ring_audit, sim_footprint  # noqa: E402

HALF_WIDTH_M = 0.0925
WEST_CORNER_BOX = (-1.35, -1.05, -0.55, -0.18)


def segment_distance(point, a, b):
    vx, vy = b[0] - a[0], b[1] - a[1]
    t = max(0.0, min(1.0, ((point[0]-a[0])*vx + (point[1]-a[1])*vy) / (vx*vx + vy*vy)))
    return math.hypot(point[0]-a[0]-t*vx, point[1]-a[1]-t*vy)


def corner_audit(rows, body, centreline):
    samples = []
    previous = None
    max_step = 0.0
    for row in rows:
        pose = row.get("gt")
        if pose is None:
            continue
        x, y, yaw = pose
        if not all(math.isfinite(v) for v in pose):
            raise ValueError("non-finite GT pose")
        x0, x1, y0, y1 = WEST_CORNER_BOX
        if not x0 <= x <= x1 or not y0 <= y <= y1:
            continue
        c, s = math.cos(yaw), math.sin(yaw)
        polygon = [(x+c*bx-s*by, y+s*bx+c*by) for bx, by in body]
        # Vertices plus edge midpoints are a sampled geometric proxy, not a continuous sweep.
        points = polygon + [((a[0]+b[0])/2, (a[1]+b[1])/2)
                            for a, b in zip(polygon, polygon[1:]+polygon[:1])]
        margin = HALF_WIDTH_M - max(min(segment_distance(p, a, b)
                                        for a, b in zip(centreline, centreline[1:])) for p in points)
        if previous is not None:
            max_step = max(max_step, *(math.dist(a, b) for a, b in zip(previous, polygon)))
        previous = polygon
        samples.append((margin, row.get("sim_t"), pose))
    if not samples:
        raise ValueError("no west corner GT samples")
    return {
        "samples": len(samples),
        "minimum_sampled_margin_to_paint_centre_m": round(min(v[0] for v in samples), 6),
        "samples_crossing_paint_centre": sum(v[0] < 0 for v in samples),
        "maximum_sampled_vertex_step_m": round(max_step, 6),
        "worst_sample": min(samples)[1:],
        "continuous_lane_containment_proof": False,
    }


def selfcheck():
    assert segment_distance((0, 0), (1, -1), (1, 1)) == 1.0
    assert segment_distance((0, 0), (0, 1), (1, 1)) == 1.0


if __name__ == "__main__":
    selfcheck()
    parser = argparse.ArgumentParser()
    parser.add_argument("logs", nargs="+", type=Path)
    args = parser.parse_args()
    body, radius = sim_footprint()
    graph = yaml.safe_load((REPO / "middleware/perception/map/map_v2_fleet/lane_graph.yaml").read_text())
    line = graph["segments"]["west"]["points"]
    report = {"sim_footprint_radius_m": round(radius, 6), "runs": {}}
    for path in args.logs:
        rows = [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines()]
        entry = {"west_corner": corner_audit(rows, body, line)}
        if any(str(r.get("reason") or "").startswith("lane_arc") for r in rows):
            try:
                entry["ring"] = ring_audit(rows, body)
            except ValueError:
                entry["ring"] = "incomplete"
        report["runs"][str(path)] = entry
    print(json.dumps(report, indent=2))
