#!/usr/bin/env python3
"""Replay a recorded SIM bend through the unchanged edge follower and inspect map alignment."""
import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "middleware/perception"), str(ROOT / "operations/fleet"),
                str(ROOT / "contracts/foundation")]
from control.sensing.perception.camera_ground import ground_plane  # noqa: E402
from control.sensing.perception.lane_bev import BEV_CELL_M, LaneEdgeFollower  # noqa: E402
from fleet.routing.graph import build_graph  # noqa: E402
from fleet.site_map import from_lane_graph  # noqa: E402


def signed_memory(memory, pose, arc):
    points = memory._keys * BEV_CELL_M  # offline inspection of the follower's actual carried cells
    forward = ((points[:, 0] - pose[0]) * math.cos(pose[2])
               + (points[:, 1] - pose[1]) * math.sin(pose[2]))
    offsets = []
    for x, y in points[(forward >= 0.09) & (forward <= 0.40)]:
        _, s, heading = arc.project(float(x), float(y))
        cx, cy, _ = arc.point_at(s)
        offsets.append(-(x - cx) * math.sin(heading) + (y - cy) * math.cos(heading))
    return {"ahead_cells": len(offsets),
            "median_signed_offset_m": round(float(np.median(offsets)), 4) if offsets else None,
            "p10_p90_m": [round(float(v), 4) for v in np.percentile(offsets, [10, 90])] if offsets else None}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("frames_npz")
    parser.add_argument("keep_jsonl")
    parser.add_argument("lane_graph_yaml")
    parser.add_argument("arc_id")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--frame-index", type=int)
    selection.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    frames = np.load(args.frames_npz)
    rows = [json.loads(line) for line in Path(args.keep_jsonl).read_text(encoding="utf-8").splitlines()]
    keep = {row["stamp"]: row for row in rows}
    if len(keep) != len(rows):
        raise ValueError("duplicate keeper stamps")
    stamps = frames["stamp"]
    if (args.frame_index is not None and not 0 <= args.frame_index < len(stamps)) or any(float(t) not in keep for t in stamps):
        raise ValueError("frame index or keeper stamp mismatch")
    geometry = keep[float(stamps[0])]["ground_projection"]
    if any(keep[float(t)].get("ground_projection") != geometry for t in stamps):
        raise ValueError("ground projection changed during replay")
    ground = ground_plane(**{key: geometry[key] for key in
                             ("height_m", "pitch_rad", "focal_px", "principal_x", "principal_y", "max_range_m")})
    if ground is None:
        raise ValueError("invalid recorded ground projection")
    arc = build_graph(from_lane_graph(args.lane_graph_yaml)).arcs[args.arc_id]
    follower = LaneEdgeFollower(camera_x_offset_m=geometry["camera_x_offset_m"])
    source_counts = {"LEFT": 0, "RIGHT": 0, "NONE": 0}
    bend_offsets = []
    for i in range(len(stamps) if args.summary else args.frame_index + 1):
        pose = tuple(map(float, frames["gt"][i]))
        if not all(math.isfinite(v) for v in pose):
            raise ValueError(f"missing SIM GT pose at frame {i}")
        follower.update(float(stamps[i]), pose, frames["frames"][i], ground,
                        lane_half_width_m=0.0925, bright_threshold=180)
        if args.summary:
            source = follower.last.get("source") or "NONE"
            source_counts[source] = source_counts.get(source, 0) + 1
            target = follower.last.get("target")
            if target is not None and -1.05 <= pose[0] <= -0.78 and pose[1] < -0.3:
                tx = pose[0] + target[0] * math.cos(pose[2]) - target[1] * math.sin(pose[2])
                ty = pose[1] + target[0] * math.sin(pose[2]) + target[1] * math.cos(pose[2])
                bend_offsets.append(arc.project(tx, ty)[0])
    if args.summary:
        print(json.dumps({"image_frames": len(stamps), "source_counts":
                          source_counts,
                          "bend_target_frames": len(bend_offsets),
                          "bend_max_target_map_offset_m": round(max(bend_offsets), 4) if bend_offsets else None},
                         indent=2))
        return
    target = follower.last.get("target")
    target_offset = None
    if target is not None:
        tx = pose[0] + target[0] * math.cos(pose[2]) - target[1] * math.sin(pose[2])
        ty = pose[1] + target[0] * math.sin(pose[2]) + target[1] * math.cos(pose[2])
        target_offset = round(arc.project(tx, ty)[0], 4)
    view = follower._view
    near = (view.x >= 0.09) & (view.x <= 0.25)
    left_y = view.y[(follower.last["memory"] > 0) & near]
    right_y = view.y[(follower.last["right_memory"] > 0) & near]
    pair_gap = round(float(np.median(left_y) - np.median(right_y)), 4) if len(left_y) and len(right_y) else None
    right_target, right_supported = follower._lookahead(view, follower.last["right_memory"], 0.0925)
    right_target_offset = None
    if right_target is not None:
        tx = pose[0] + right_target[0] * math.cos(pose[2]) - right_target[1] * math.sin(pose[2])
        ty = pose[1] + right_target[0] * math.sin(pose[2]) + right_target[1] * math.cos(pose[2])
        right_target_offset = round(arc.project(tx, ty)[0], 4)
    print(json.dumps({"frame_index": args.frame_index, "stamp": float(stamps[args.frame_index]),
                      "keeper_rows": len(rows), "image_frames": len(stamps),
                      "keeper_strategy": keep[float(stamps[args.frame_index])].get("strategy"),
                      "follower_source": follower.last.get("source"), "target_m": target,
                      "target_map_offset_m": target_offset, "lane_half_width_m": 0.0925,
                      "near_pair_gap_m": pair_gap, "right_fallback_supported": right_supported,
                      "right_fallback_target_map_offset_m": right_target_offset,
                      "left_memory": signed_memory(follower._left, pose, arc),
                      "right_memory": signed_memory(follower._right, pose, arc)}, indent=2))


if __name__ == "__main__":
    main()
