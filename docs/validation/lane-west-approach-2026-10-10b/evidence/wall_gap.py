"""Compare archived west HOLD poses with the actual STL perimeter wall and SIM URDF hull."""

import argparse
import importlib.util
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def wall_limits(walls):
    assert len(walls) == 4
    left = max(w.cx + w.size_x / 2 for w in walls if w.cx < -1)
    right = min(w.cx - w.size_x / 2 for w in walls if w.cx > 1)
    bottom = max(w.cy + w.size_y / 2 for w in walls if w.cy < -0.5)
    top = min(w.cy - w.size_y / 2 for w in walls if w.cy > 0.5)
    return left, right, bottom, top


def body_wall_gap(body, pose, limits):
    x, y, yaw = pose
    if not all(math.isfinite(v) for v in pose):
        raise ValueError("invalid Gazebo GT pose")
    c, s = math.cos(yaw), math.sin(yaw)
    points = [(x + c * bx - s * by, y + s * bx + c * by) for bx, by in body]
    left, right, bottom, top = limits
    return min(min(px for px, _ in points) - left, right - max(px for px, _ in points),
               min(py for _, py in points) - bottom, top - max(py for _, py in points))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--urdf-root", required=True, type=Path)
    parser.add_argument("run_root", type=Path)
    args = parser.parse_args()
    prior = load_module("prior_footprint_audit", ROOT / "docs/validation/lane-bend-map-footprint-2026-10-10/evidence/audit.py")
    body, _, _ = prior._archived_body(args.urdf_root)
    scene_script = ROOT / "middleware/perception/map/map_v2_fleet/scripts/stl_scene.py"
    stl_scene = load_module("stl_scene_for_wall_gap", scene_script)
    scene = stl_scene.load_scene(next(scene_script.parents[1].glob("260919*.STL")))
    limits = wall_limits(scene.walls)
    runs = []
    for path in sorted(args.run_root.glob("fwest_*")):
        rows = [json.loads(line) for line in (path / "log.jsonl").read_text(encoding="utf-8").splitlines()]
        stopped = [r for r in rows if r.get("reason") == "obstacle_ahead" and r.get("body_gap_m") is not None]
        if not stopped:
            raise ValueError(f"{path.name}: no obstacle stop with body gap")
        row = stopped[-1]
        runs.append({"run": path.name, "sim_t": row["sim_t"], "gt": row["gt"],
                     "reported_path_body_gap_m": row["body_gap_m"],
                     "stl_wall_body_gap_m": round(body_wall_gap(body, row["gt"], limits), 6),
                     "ir_mm": row["ir"]})
    if len(runs) != 10:
        raise ValueError(f"expected ten west runs, got {len(runs)}")
    print(json.dumps({"stl_sha256": scene.source_sha256, "wall_inner_limits_m": limits,
                      "runs": runs}, indent=2))


if __name__ == "__main__":
    main()
