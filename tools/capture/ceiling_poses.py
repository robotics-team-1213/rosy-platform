#!/usr/bin/env python3
"""D-563 3: robot map poses from a ceiling_record.py recording (the Rosy Cam side of the labels).

  ceiling_poses.py --rec DIR --marker-id N [--marker-height-m 0.125] [--marker-size-m 0.030]
                   [--heading-edge 0,1] [--out DIR/poses.jsonl]

Each frame's robot ArUco marker (D-562: DICT_4X4_50, id = robot number; the detected black
square of the 40 mm sticker is 30 mm) is mapped through the approved tracking calibration
(D-457 map_to_image, D-560 map plane) into map metres, parallax-corrected to the floor under
the marker (camera solved from the homography + lens, as the tracker does). Row:
{t (site clock captured_at), seq, x, y, yaw, src: "aruco", reproj_err} where reproj_err is the
RMS deviation (m) of the four mapped corners from the marker's half-diagonal; yaw is the
direction from the centre to the heading-edge midpoint (site config heading_edge; 0,1 measured
forward on 8kcn 2026-10-09). learning/.../dataset/ceiling_pose.py fuses the rows with odometry.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO / "operations" / "vision", REPO / "contracts" / "foundation", REPO / "operations" / "apps" / "games",
           REPO / "learning" / "training" / "perception" / "dataset"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from ceiling_pose import read_calibration  # noqa: E402
from rosy_vision.track.model import ROBOT_TOP_HEIGHT_M  # noqa: E402  (marker on the top deck)

MARKER_BLACK_M = 0.030  # D-562: 40 mm sticker, one white cell border -> 30 mm black square


def load_calibration(rec_dir, frame_size, frame_lens=None):
    """(image_to_map 3x3, camera (x, y, height) or None, record) for frames of frame_size."""
    from rosy_vision.track import geometry
    from rosy_vision.track.calibration import from_record
    doc = read_calibration(rec_dir)[1]
    doc["frame_lens"] = doc.get("frame_lens") or frame_lens
    record = doc.get("record")
    if not record:
        raise ValueError("calibration.json has no approved tracking record for this source")
    calibration = from_record(record, source_id=record["source_id"], map_id=record["map_id"],
                              frame_size=frame_size, lens=doc.get("frame_lens") or record.get("lens"))
    if calibration is None:
        raise ValueError("tracking record does not fit these frames (source, map, lens or aspect)")
    matrix = geometry.as_matrix(calibration.image_to_map)
    camera = geometry.camera_from_homography(matrix, calibration.image_size, calibration.hfov_deg)
    return matrix, camera, record


def marker_pose(quad, image_to_map, camera, *, height_m=ROBOT_TOP_HEIGHT_M, size_m=MARKER_BLACK_M,
                heading_edge=(0, 1)):
    """Image quad -> (x, y, yaw, reproj_err) on the floor under the marker, or None."""
    from rosy_vision.track import geometry
    corners = geometry.apply(image_to_map, np.asarray(quad, float))
    if not np.all(np.isfinite(corners)):
        return None
    if camera is not None:
        corners = np.array([geometry.parallax_correct(c, camera, height_m) for c in corners])
    centre = corners.mean(axis=0)
    tip = corners[list(heading_edge)].mean(axis=0)
    err = math.sqrt(float(np.mean((np.linalg.norm(corners - centre, axis=1) - size_m / math.sqrt(2)) ** 2)))
    return float(centre[0]), float(centre[1]), math.atan2(tip[1] - centre[1], tip[0] - centre[0]), err


def detect(rec_dir, marker_id, *, height_m=ROBOT_TOP_HEIGHT_M, size_m=MARKER_BLACK_M, heading_edge=(0, 1)):
    from rosy_vision.detect import detect_markers
    rec_dir = Path(rec_dir)
    rows = [json.loads(line) for line in (rec_dir / "frames.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]
    cache, poses = {}, []
    for row in rows:
        size = (row["width"], row["height"])
        if size not in cache:
            cache[size] = load_calibration(rec_dir, size, row.get("lens"))
        matrix, camera, _ = cache[size]
        quad = detect_markers((rec_dir / row["file"]).read_bytes()).get(marker_id)
        pose = None if quad is None else marker_pose(quad, matrix, camera, height_m=height_m, size_m=size_m,
                                                     heading_edge=heading_edge)
        if pose is not None:
            poses.append({"t": row["captured_at"], "seq": row["seq"], "x": pose[0], "y": pose[1],
                          "yaw": pose[2], "src": "aruco", "reproj_err": pose[3],
                          "parallax": camera is not None})
    return poses, len(rows)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--rec", type=Path, required=True)
    p.add_argument("--marker-id", type=int, required=True, help="D-562: the robot number")
    p.add_argument("--marker-height-m", type=float, default=ROBOT_TOP_HEIGHT_M)
    p.add_argument("--marker-size-m", type=float, default=MARKER_BLACK_M)
    p.add_argument("--heading-edge", default="0,1", help="site-cameras.yaml heading_edge of this robot")
    p.add_argument("--out", type=Path)
    args = p.parse_args(argv)
    edge = tuple(int(v) for v in args.heading_edge.split(","))
    poses, frames = detect(args.rec, args.marker_id, height_m=args.marker_height_m,
                           size_m=args.marker_size_m, heading_edge=edge)
    out = args.out or args.rec / "poses.jsonl"
    out.write_text("".join(json.dumps(r) + "\n" for r in poses), encoding="utf-8")
    print(json.dumps({"frames": frames, "detections": len(poses), "out": str(out)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
