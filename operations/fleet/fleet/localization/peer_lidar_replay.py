"""Replay stationary peer LiDAR centroids in their shared native grid without commanding a robot.

Run with python -m fleet.localization.peer_lidar_replay SNAPSHOT.json. Timestamps are
seconds on a shared capture clock. Observer positions are native map metres and radians.
Cluster and exclusion coordinates are in base_link and the native grid respectively.
"""

import argparse
import json
import math
from pathlib import Path

from fleet.localization import cues

MAX_SAMPLE_SKEW_S = 0.3


def _vector(value, size):
    if not isinstance(value, (list, tuple)) or len(value) != size or not all(
        isinstance(v, (float, int)) and not isinstance(v, bool) and math.isfinite(v) for v in value
    ):
        raise ValueError(f"expected {size} finite coordinates")
    return value


def compare(snapshot):
    target = snapshot["target"]
    stamp, = _vector([target["stamp"]], 1)
    xy = _vector(target["native_xy"], 2)
    grid = target["grid_id"]
    if not isinstance(grid, str) or not grid or not target["robot_id"]:
        raise ValueError("target identity and native grid are required")
    if target["stationary"] is not True:
        raise ValueError("replay requires a stationary target")
    excluded = [_vector(point, 2) for point in snapshot["known_exclusions_xy"]]
    rows = {}
    for other in snapshot["observers"]:
        rid = other["robot_id"]
        if not rid or rid in rows or rid == target["robot_id"]:
            raise ValueError("each observer must have a distinct identity")
        out = rows[rid] = {}
        if other["stationary"] is not True:
            out["status"] = "observer_moving"
            continue
        if other["state"] != "LOCALIZED" or other["pose_frame"] != "map" or other["grid_id"] != grid:
            out["status"] = "untrusted_or_different_grid"
            continue
        scan_stamp, pose_stamp = _vector([other["scan_stamp"], other["pose_stamp"]], 2)
        if max(abs(scan_stamp - stamp), abs(pose_stamp - scan_stamp)) > MAX_SAMPLE_SKEW_S:
            out["status"] = "out_of_capture_window"
            continue
        pose = _vector(other["native_pose"], 3)
        matches = []
        for cluster in other["clusters_base_xy"]:
            point = cues.to_map(pose, _vector(cluster, 2))
            if math.dist(point, xy) <= cues.PEER_MATCH_M and all(
                math.dist(point, known) > cues.PEER_MATCH_M for known in excluded
            ):
                matches.append(point)
        out["count"] = len(matches)
        if len(matches) == 1:
            out.update(status="one_return", native_xy=matches[0], candidate_gap_m=math.dist(matches[0], xy))
        else:
            out["status"] = "ambiguous" if matches else "no_return"
    points = [r["native_xy"] for r in rows.values() if r["status"] == "one_return"]
    spread = max((math.dist(a, b) for i, a in enumerate(points) for b in points[i + 1:]), default=None)
    return {"target": target["robot_id"], "observers": rows, "observer_spread_m": spread}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(json.loads(args.snapshot.read_text(encoding="utf-8"))), indent=2))
