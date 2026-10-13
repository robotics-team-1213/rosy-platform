"""Read-only sampled footprint audit of archived D-507 Gazebo GT logs.

Input run directories stay outside git. White STL floor triangles contain lane
edges and other markings, so contact is reported as paint contact, not a
human-approved physical boundary identity or a continuous collision proof.
"""

import argparse
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[4]
for relative in ("contracts/foundation", "middleware/perception",
                 "middleware/perception/test"):
    sys.path.insert(0, str(ROOT / relative))

from lane_sim import stl_world  # noqa: E402

FOOTPRINT_SCRIPT = ROOT / "docs/validation/lane-loop-failure-audit-2026-10-09/evidence/ring_footprint.py"
spec = importlib.util.spec_from_file_location("ring_footprint_for_bend_audit", FOOTPRINT_SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

PASS_REASONS = frozenset(("junction_bending", "junction_reacquiring"))


def _archived_body(urdf_root):
    source = urdf_root / "tools/calibration/urdf_nominal.py"
    spec = importlib.util.spec_from_file_location("archived_urdf_nominal", source)
    urdf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(urdf)
    links, joints = urdf.expand(is_sim=True)
    poses = urdf.frames(joints)
    points = []
    for link in links:
        for collision in link["collisions"]:
            transform = urdf._mul(poses[link["name"]], urdf._matrix(collision["xyz"], collision["rpy"]))
            points.extend(tuple(urdf._apply(transform, point)[:2]) for point in urdf._shape_points(collision))
    body = module.hull(points)
    radius = max(math.hypot(x, y) for x, y in body)
    if abs(radius - urdf.nominal()["footprint"]["rotation_radius_sim_box_m"]) > 1e-5:
        raise ValueError("archived SIM footprint does not match nominal rotation radius")
    return body, radius, source


def _polygon(world, body, pose):
    x, y, yaw = pose
    c, s = math.cos(yaw), math.sin(yaw)
    points = [(x + c * bx - s * by, y + s * bx + c * by) for bx, by in body]
    return np.rint(world.px(points)).astype(np.int32)


def _footprint_at(world, distances, body, pose):
    polygon = _polygon(world, body, pose)
    low, high = polygon.min(axis=0) - 1, polygon.max(axis=0) + 2
    x0, y0 = low
    x1, y1 = high
    if x0 < 0 or y0 < 0 or x1 > world.paint.shape[1] or y1 > world.paint.shape[0]:
        raise ValueError("body footprint outside the audited world raster")
    mask = np.zeros((y1 - y0, x1 - x0), np.uint8)
    cv2.fillPoly(mask, [polygon - low], 1)
    cells = mask > 0
    contact = int(np.count_nonzero(cells & (world.paint[y0:y1, x0:x1] > 0)))
    gap_m = float(distances[y0:y1, x0:x1][cells].min()) * 0.001
    return contact, gap_m, polygon


def audit_run(path, world, distances, body):
    summary_path, log_path = path / "summary.json", path / "log.jsonl"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    sampled, previous, largest_step_m = [], None, 0.0
    for row in rows:
        if row.get("reason") not in PASS_REASONS or not row.get("gt"):
            continue
        pose = row["gt"]
        if len(pose) != 3 or not all(math.isfinite(v) for v in pose):
            raise ValueError(f"invalid Gazebo GT in {log_path}")
        count, gap_m, polygon = _footprint_at(world, distances, body, pose)
        if previous is not None:
            largest_step_m = max(largest_step_m, float(np.linalg.norm(polygon - previous, axis=1).max()) * 0.001)
        previous = polygon
        sampled.append({"sim_t": row.get("sim_t"), "gt": pose, "reason": row["reason"],
                        "paint_pixels": count, "paint_gap_m": gap_m,
                        "ir": row.get("ir"), "body_gap_m": row.get("body_gap_m")})
    touching = [row for row in sampled if row["paint_pixels"]]
    return {"run": path.name, "result": summary.get("result"),
            "log_sha256": hashlib.sha256(log_path.read_bytes()).hexdigest(),
            "sampled_pass_poses": len(sampled), "paint_contact_poses": len(touching),
            "maximum_paint_pixels": max((r["paint_pixels"] for r in sampled), default=0),
            "minimum_sampled_paint_gap_m": min((r["paint_gap_m"] for r in sampled), default=None),
            "maximum_sampled_vertex_step_m": largest_step_m,
            "first_contact": touching[0] if touching else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--urdf-root", required=True, type=Path,
                        help="archived source tree copied from the run's model PC")
    parser.add_argument("run_roots", nargs="+", type=Path)
    args = parser.parse_args()
    world = stl_world()
    body, radius, urdf_source = _archived_body(args.urdf_root)
    distances = cv2.distanceTransform((world.paint == 0).astype(np.uint8), cv2.DIST_L2, 5)
    scene_path = next((ROOT / "middleware/perception/map/map_v2_fleet").glob("260919*.STL"))
    archived_xacro = args.urdf_root / "middleware/apps/device/pinky/description/urdf/rosy.urdf.xacro"
    runs = []
    for root in args.run_roots:
        for path in sorted(root.iterdir()):
            if path.is_dir() and (path / "summary.json").is_file() and (path / "log.jsonl").is_file():
                runs.append({"batch": root.name, **audit_run(path, world, distances, body)})
    if not runs:
        raise ValueError("no archived runs found")
    print(json.dumps({"map_stl_sha256": hashlib.sha256(scene_path.read_bytes()).hexdigest(),
                      "archived_urdf_nominal_sha256": hashlib.sha256(urdf_source.read_bytes()).hexdigest(),
                      "archived_rosy_xacro_sha256": hashlib.sha256(archived_xacro.read_bytes()).hexdigest(),
                      "sim_body_radius_m": radius, "body_vertices": len(body),
                      "paint_raster_m": 0.001, "continuous_sweep_proven": False,
                      "runs": runs}, indent=2))


if __name__ == "__main__":
    main()
