#!/usr/bin/env python3
"""A printed ArUco marker on the gripper, found by the top camera in one frame (2026-10-30).

The look found the jaws by differencing frames while they opened and closed: the arm link hid one finger at some
yaws (the mark jumped to the other finger, 70 mm off), opening shook the link into the blob, and a small opening left
none. A marker gives the gripper's position and yaw from one still frame. Measured at the top camera's 1.1 px/mm with
blur and JPEG: 15 mm and up were found 20/20 with a centre within 0.4 px, 12 mm 16/20. The finger top is 8 mm wide,
so the marker goes on the gripper body's top face, 20 mm (it shows ~1.2x larger at hover height).

  cell_marks.py sheet OUT.png [--mm 20 25] [--ids 0 1]    print at 100 %, cut out with the white margin
  cell_marks.py find FRAME.jpg                           list markers seen: id, centre px, yaw deg, side px
"""
from __future__ import annotations

import argparse
import json
import math
import sys

import numpy as np

DPI = 300


def _dictionary():
    import cv2

    return cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)


def sheet(sizes_mm=(20, 25), ids=(0, 1), dpi: int = DPI):
    """A printable page (A4 at dpi) with each id at each size, a white margin of one cell and a size label."""
    import cv2

    px_per_mm = dpi / 25.4
    page = np.full((round(297 * px_per_mm), round(210 * px_per_mm)), 255, np.uint8)
    y = round(15 * px_per_mm)
    for mm in sizes_mm:
        side, x = round(mm * px_per_mm), round(15 * px_per_mm)
        for i in ids:
            page[y:y + side, x:x + side] = cv2.aruco.generateImageMarker(_dictionary(), int(i), side)
            cv2.putText(page, f"id {i}  {mm} mm", (x, y + side + round(5 * px_per_mm)), cv2.FONT_HERSHEY_SIMPLEX,
                        0.9, 0, 2)
            x += side + round(20 * px_per_mm)
        y += side + round(20 * px_per_mm)
    return page


def find(img) -> dict:
    """{id: {"centre_px": [x, y], "yaw_deg": direction of the marker's top edge, "side_px": mean side}}."""
    import cv2

    grey = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    corners, ids, _ = cv2.aruco.ArucoDetector(_dictionary(), cv2.aruco.DetectorParameters()).detectMarkers(grey)
    out = {}
    for c, i in zip(corners if ids is not None else [], ids.flatten() if ids is not None else []):
        q = c[0]
        top = q[1] - q[0]
        out[int(i)] = {"centre_px": [round(float(v), 2) for v in q.mean(0)],
                       "yaw_deg": round(math.degrees(math.atan2(top[1], top[0])), 1),
                       "side_px": round(float(np.mean([np.linalg.norm(q[k] - q[k - 1]) for k in range(4)])), 1)}
    return out


def main(argv=None):
    import cv2

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sheet")
    s.add_argument("out")
    s.add_argument("--mm", type=float, nargs="+", default=[20, 25])
    s.add_argument("--ids", type=int, nargs="+", default=[0, 1])
    f = sub.add_parser("find")
    f.add_argument("frame")
    args = ap.parse_args(argv)
    if args.cmd == "sheet":
        cv2.imwrite(args.out, sheet(args.mm, args.ids))
        print(f"{args.out}: print at 100 % ({DPI} dpi), check one marker with a ruler")
    else:
        print(json.dumps(find(cv2.imread(args.frame)), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
