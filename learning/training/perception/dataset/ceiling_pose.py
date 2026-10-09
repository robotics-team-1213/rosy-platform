"""D-563 3: robot map poses from a recorded ceiling camera, fused with robot odometry.

  detect --rec DIR --marker-id N [--marker-height-m 0.125] [--marker-size-m 0.030]
         [--heading-edge 0,1] [--out DIR/poses.jsonl]

DIR is a tools/capture/ceiling_record.py recording (frames.jsonl, frames/, calibration.json).
Each frame's robot ArUco marker (D-562: DICT_4X4_50, id = robot number; the detected black
square of the 40 mm sticker is 30 mm) is mapped through the approved tracking calibration
(D-457 map_to_image, D-560 map plane) into map metres, parallax-corrected to the floor under
the marker (camera solved from the homography + lens, as the tracker does). Row:
{t (site clock captured_at), seq, x, y, yaw, src: "aruco", reproj_err} where reproj_err is the
RMS deviation (m) of the four mapped corners from the marker's half-diagonal; yaw is the
direction from the centre to the heading-edge midpoint (site config heading_edge).

``fuse`` (used by map_projected_drivable.py) gives each robot camera stamp a map pose: the
nearest detection within max_gap_s, carried to the stamp by the odometry's relative motion;
the stamp is unusable without a detection, without odometry, or when the detections before and
after it disagree once carried (pose/clock error). robot time = site time + clock_offset_s;
``estimate_clock_offset`` takes it from the motion onset in both series.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
for _p in (HERE, REPO / "operations" / "vision", REPO / "contracts" / "foundation",
           REPO / "operations" / "apps" / "games"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from geometry import world_to_base, wrap  # noqa: E402

ROBOT_TOP_HEIGHT_M = 0.125  # rosy_vision.track.model.ROBOT_TOP_HEIGHT_M (marker on the top deck)
MARKER_BLACK_M = 0.030      # D-562: 40 mm sticker, one white cell border -> 30 mm black square
FUSE = {"max_gap_s": 1.0, "max_disagree_m": 0.05, "max_disagree_yaw": math.radians(10.0),
        "sigma_aruco_m": 0.02, "sigma_aruco_yaw": math.radians(3.0), "drift_per_m": 0.05,
        "max_reproj_m": 0.008}


def read_calibration(rec_dir, source_id="ceiling_north"):
    """(raw bytes, {"record", "frame_lens"}) from calibration.json (ceiling_record.py) or
    calibrations.json (a saved GET /api/fleet/calibrations response)."""
    rec_dir = Path(rec_dir)
    if (rec_dir / "calibration.json").is_file():
        raw = (rec_dir / "calibration.json").read_bytes()
        return raw, json.loads(raw)
    raw = (rec_dir / "calibrations.json").read_bytes()
    records = [r for r in json.loads(raw).get("calibrations", []) if r.get("source_id") == source_id]
    return raw, {"source_id": source_id, "record": records[0] if records else None, "frame_lens": None}


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


def _carry(det, odom_a, odom_t):
    """Detection pose moved by the odometry's relative motion from odom_a to odom_t."""
    dx, dy = world_to_base(odom_a, np.array([[odom_t[0], odom_t[1]]]))[0]
    c, s = math.cos(det[2]), math.sin(det[2])
    return det[0] + c * dx - s * dy, det[1] + s * dx + c * dy, float(wrap(det[2] + odom_t[2] - odom_a[2]))


def fuse(detections, odom, stamps, *, clock_offset_s=0.0, params=FUSE):
    """Per robot stamp: {t, x, y, yaw, usable, reason, anchor_dt, sigma_m, sigma_yaw}."""
    p = {**FUSE, **params}
    dets = sorted((d["t"] + clock_offset_s, d["x"], d["y"], d["yaw"]) for d in detections
                  if d["reproj_err"] <= p["max_reproj_m"])
    times = [d[0] for d in dets]
    out = []
    for t in stamps:
        i = int(np.searchsorted(times, t))
        near = [dets[j] for j in (i - 1, i) if 0 <= j < len(dets) and abs(dets[j][0] - t) <= p["max_gap_s"]]
        row = {"t": t, "usable": False, "reason": "no_detection"}
        odom_t = odom.at(t)
        carried = []
        for det in near:
            odom_a = odom.at(det[0])
            if odom_a is not None and odom_t is not None:
                carried.append((abs(det[0] - t), _carry(det[1:], odom_a, odom_t),
                                math.hypot(odom_t[0] - odom_a[0], odom_t[1] - odom_a[1]),
                                abs(odom_t[2] - odom_a[2])))
        if near and not carried:
            row["reason"] = "no_odom"
        elif len(carried) == 2 and (
                math.dist(carried[0][1][:2], carried[1][1][:2]) > p["max_disagree_m"]
                or abs(float(wrap(carried[0][1][2] - carried[1][1][2]))) > p["max_disagree_yaw"]):
            row["reason"] = "disagree"
        elif carried:
            dt, (x, y, yaw), moved, turned = min(carried)
            row.update(x=x, y=y, yaw=yaw, usable=True, reason=None, anchor_dt=dt,
                       sigma_m=p["sigma_aruco_m"] + p["drift_per_m"] * moved,
                       sigma_yaw=p["sigma_aruco_yaw"] + p["drift_per_m"] * turned)
        out.append(row)
    return out


def estimate_clock_offset(detections, odom, *, moved_m=0.03, max_reproj_m=FUSE["max_reproj_m"]):
    """robot - site clock from the first time each series has moved moved_m from its start, or None."""
    def onset(t, x, y):
        far = np.hypot(np.asarray(x) - x[0], np.asarray(y) - y[0]) > moved_m
        return float(np.asarray(t)[far.argmax()]) if far.any() else None
    if not detections or not len(odom):
        return None
    d = sorted((r for r in detections if r["reproj_err"] <= max_reproj_m), key=lambda r: r["t"])
    if not d:
        return None
    a = onset([r["t"] for r in d], [r["x"] for r in d], [r["y"] for r in d])
    b = onset(odom.t, odom.x, odom.y)
    return None if a is None or b is None else b - a


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("detect")
    p.add_argument("--rec", type=Path, required=True)
    p.add_argument("--marker-id", type=int, required=True, help="D-562: the robot number")
    p.add_argument("--marker-height-m", type=float, default=ROBOT_TOP_HEIGHT_M)
    p.add_argument("--marker-size-m", type=float, default=MARKER_BLACK_M)
    p.add_argument("--heading-edge", default="0,1", help="site-cameras.yaml heading_edge of this robot")
    p.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    edge = tuple(int(v) for v in args.heading_edge.split(","))
    poses, frames = detect(args.rec, args.marker_id, height_m=args.marker_height_m,
                           size_m=args.marker_size_m, heading_edge=edge)
    out = args.out or args.rec / "poses.jsonl"
    out.write_text("".join(json.dumps(r) + "\n" for r in poses), encoding="utf-8")
    print(json.dumps({"frames": frames, "detections": len(poses), "out": str(out)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
