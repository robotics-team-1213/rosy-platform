#!/usr/bin/env python3
"""Evidence video of a keep_run.py run: camera frames + state/error/pose overlay
+ a top-down minimap of the lane graph with the ground-truth track.

  python make_video.py RUN_DIR lane_graph.yaml OUT.mp4 [--fps 8]

Needs opencv, numpy, yaml and ffmpeg on PATH. Keep the output outside the
public repository (D-226).
"""
from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import tempfile

import cv2
import numpy as np
import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from keep_run import CROSS_M, LANE_HALF_M, TOUCH_M, lane_polylines, nearest_centre  # noqa: E402

MAP_W, MAP_H = 640, 300
BOUNDS = (-1.45, 1.45, -0.68, 0.68)  # x0, x1, y0, y1 (m)


def to_map(x, y):
    x0, x1, y0, y1 = BOUNDS
    scale = min(MAP_W / (x1 - x0), MAP_H / (y1 - y0))
    return int((x - x0) * scale), int(MAP_H - (y - y0) * scale)


def base_map(polylines):
    img = np.full((MAP_H, MAP_W, 3), 40, np.uint8)
    for pts in polylines.values():
        d = np.gradient(pts, axis=0)
        n = np.stack([-d[:, 1], d[:, 0]], axis=1) / np.maximum(np.hypot(*d.T), 1e-9)[:, None]
        for s in (1, -1):
            edge = pts + s * LANE_HALF_M * n
            cv2.polylines(img, [np.array([to_map(*p) for p in edge], np.int32)], False, (200, 200, 200), 2)
        cv2.polylines(img, [np.array([to_map(*p) for p in pts], np.int32)], False, (90, 90, 90), 1)
    return img


def main():
    p = argparse.ArgumentParser()
    p.add_argument("run")
    p.add_argument("graph")
    p.add_argument("out")
    p.add_argument("--fps", type=float, default=8.0)
    p.add_argument("--max-sim-t", type=float, default=None, help="stop at this sim time (s)")
    args = p.parse_args()
    polylines = lane_polylines(yaml.safe_load(open(args.graph)))
    rows = list(csv.DictReader(open(os.path.join(args.run, "frames.csv"))))
    if args.max_sim_t is not None:
        rows = [r for r in rows if float(r["sim_t"]) <= args.max_sim_t]
    track = []
    base = base_map(polylines)
    with tempfile.TemporaryDirectory() as tmp:
        for k, row in enumerate(rows):
            cam = cv2.imread(os.path.join(args.run, "frames", row["frame"]))
            if cam is None:
                continue
            cam = cv2.resize(cam, (640, 480), interpolation=cv2.INTER_NEAREST)
            x, y, yaw = float(row["x"]), float(row["y"]), float(row["yaw"])
            lateral, _, segment = nearest_centre(polylines, x, y)
            track.append((x, y, lateral))
            colour = (0, 200, 0) if lateral <= TOUCH_M else (0, 200, 255) if lateral <= CROSS_M else (0, 0, 255)
            err = row["error"] or "-"
            lines = [f"sim t {float(row['sim_t']):6.1f} s   {row['state']} ({row['reason']})",
                     f"error {err[:6]:>6}   pose ({x:+.3f}, {y:+.3f}) yaw {np.degrees(yaw):+.0f} deg",
                     f"lateral {lateral * 1000:5.1f} mm from lane centre ({segment})"]
            cv2.rectangle(cam, (0, 0), (640, 70), (0, 0, 0), -1)
            for i, text in enumerate(lines):
                cv2.putText(cam, text, (8, 20 + 22 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                            colour if i == 2 else (255, 255, 255), 1, cv2.LINE_AA)
            minimap = base.copy()
            for a, b in zip(track[:-1], track[1:]):
                c = (0, 200, 0) if b[2] <= TOUCH_M else (0, 200, 255) if b[2] <= CROSS_M else (0, 0, 255)
                cv2.line(minimap, to_map(a[0], a[1]), to_map(b[0], b[1]), c, 2)
            tip = to_map(x + 0.08 * np.cos(yaw), y + 0.08 * np.sin(yaw))
            cv2.arrowedLine(minimap, to_map(x, y), tip, (255, 0, 255), 2, tipLength=0.4)
            cv2.imwrite(os.path.join(tmp, f"{k:05d}.png"), np.vstack([cam, minimap]))
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", str(args.fps),
                        "-i", os.path.join(tmp, "%05d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        args.out], check=True)
    print("wrote", args.out, len(rows), "frames")


if __name__ == "__main__":
    main()
