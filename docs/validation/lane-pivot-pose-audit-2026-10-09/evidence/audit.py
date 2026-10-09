"""Read-only SIM audit of the first ring arc's pivot, odom, and ground truth.

Usage: python audit.py --centre -0.3357 0.0011 --radius 0.2514 RUN_DIR [RUN_DIR ...]
GT is evaluation only. This script does not produce a driving correction.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path


def wrap(angle):
    return math.atan2(math.sin(angle), math.cos(angle))


def _errors(row):
    gt, odom = row["gt"], row["odom"]
    return {
        "odom_gt_xy_mm": round(1000 * math.dist(odom[:2], gt[:2]), 3),
        "odom_gt_yaw_deg": round(math.degrees(wrap(odom[2] - gt[2])), 3),
    }


def audit(run_dir, centre, radius):
    log_path = run_dir / "log.jsonl"
    rows = [json.loads(line) for line in log_path.open(encoding="utf-8")]
    arc_index = next(i for i, row in enumerate(rows)
                     if str(row.get("reason") or "").startswith("lane_arc") and row.get("gt")
                     and row.get("odom"))
    arc = rows[arc_index]
    turns = [row for row in rows[:arc_index]
             if row.get("reason") == "junction_turning" and row.get("gt") and row.get("odom")]
    if not turns:
        raise ValueError(f"no turn before first arc: {run_dir}")
    pivot = turns[-1]
    gt = arc["gt"]
    tangent = math.atan2(gt[1] - centre[1], gt[0] - centre[0]) + math.pi / 2
    result = {
        "group": run_dir.parent.name,
        "run": run_dir.name,
        "log_sha256": hashlib.sha256(log_path.read_bytes()).hexdigest(),
        "turn_place_id": pivot["junction"].get("place_id"),
        "fleet_turn_deg": pivot["junction"].get("turn_deg"),
        "pivot_sim_t_s": pivot["sim_t"],
        "arc_sim_t_s": arc["sim_t"],
        "pivot_odom_gt": _errors(pivot),
        "arc_odom_gt": _errors(arc),
        "arc_heading_minus_map_tangent_deg": round(math.degrees(wrap(gt[2] - tangent)), 3),
        "arc_radial_error_m": round(math.dist(gt[:2], centre) - radius, 4),
    }
    frames_path = run_dir / "frames.npz"
    if frames_path.exists():
        import numpy as np

        with np.load(frames_path) as frames:
            stamps = frames["stamp"]
            index = int(np.argmin(np.abs(stamps - arc["sim_t"])))
            result["nearest_camera_frame"] = {
                "frame_sha256": hashlib.sha256(frames_path.read_bytes()).hexdigest(),
                "frame_minus_arc_ms": round(1000 * float(stamps[index] - arc["sim_t"]), 2),
                "frame_minus_odom_stamp_ms": round(1000 * float(stamps[index] - frames["odom"][index, 5]), 2),
            }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--centre", type=float, nargs=2, required=True)
    parser.add_argument("--radius", type=float, required=True)
    parser.add_argument("run_dir", type=Path, nargs="+")
    args = parser.parse_args()
    if args.radius <= 0 or not math.isfinite(args.radius) or any(not math.isfinite(v) for v in args.centre):
        parser.error("finite centre and positive finite radius required")
    for run_dir in args.run_dir:
        print(json.dumps(audit(run_dir, args.centre, args.radius), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
