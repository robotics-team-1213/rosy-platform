#!/usr/bin/env python3
"""A printed ArUco marker on the gripper, found by the top camera in one frame (2026-10-30).

The look found the jaws by differencing frames while they opened and closed: the arm link hid one finger at some
yaws (the mark jumped to the other finger, 70 mm off), opening shook the link into the blob, and a small opening left
none. A marker gives the gripper's position and yaw from one still frame. Measured at the top camera's 1.1 px/mm with
blur and JPEG: 15 mm and up were found 20/20 with a centre within 0.4 px, 12 mm 16/20. The finger top is 8 mm wide,
so the marker goes on the gripper body's top face, 20 mm (it shows ~1.2x larger at hover height). Each arm slot has
its own ids in DICT_4X4_100 (D-933, D-954: slot n's gripper is 50 + 15 (n - 1)), past the site's DICT_4X4_50 ids
0-49, so neither the ChArUco board nor a Pinky's ceiling sticker reads as an arm marker. Container tags are
DICT_4X4_250 ids 100-199 (D-996 6), so find() reads DICT_4X4_250: its ids 0-99 are the same pictures as before.
A container carries its tag twice, roof and one side face (12 mm roof on a 1-slot container, 20 mm otherwise).

  cell_marks.py sheet OUT.png [--mm 20 25] [--ids 50]     print at 100 %, cut out with the white margin
  cell_marks.py sheet OUT.png --mm 12 20 --ids 100 101 --faces roof side    container tags, one per face
  cell_marks.py find FRAME.jpg                           list markers seen: id, centre px, yaw deg, side px
"""
from __future__ import annotations

import argparse
import json
import math
import sys

import numpy as np

DPI = 300


_ARUCO_CACHE: dict = {}


def _dictionary():
    import cv2

    dictionary = _ARUCO_CACHE.get("dict")
    if dictionary is None:
        dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_250)
        _ARUCO_CACHE["dict"] = dictionary
    return dictionary


def sheet(sizes_mm=(20, 25), ids=(50,), dpi: int = DPI, faces=("",)):
    """A printable page (A4 at dpi) with each id at each size (once per face), a white margin and a label."""
    import cv2

    px_per_mm = dpi / 25.4
    page = np.full((round(297 * px_per_mm), round(210 * px_per_mm)), 255, np.uint8)
    y = round(15 * px_per_mm)
    draw_marker = getattr(cv2.aruco, "generateImageMarker", None) or cv2.aruco.drawMarker
    for mm in sizes_mm:
        side, x = round(mm * px_per_mm), round(15 * px_per_mm)
        for i in ids:
            for face in faces:
                if x + side > page.shape[1]:  # row full: wrap instead of drawing past the page edge
                    x, y = round(15 * px_per_mm), y + side + round(20 * px_per_mm)
                page[y:y + side, x:x + side] = draw_marker(_dictionary(), int(i), side)
                cv2.putText(page, f"id {i} {face} {mm:g} mm".replace("  ", " "), (x, y + side + round(5 * px_per_mm)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, 0, 2)
                x += side + round(20 * px_per_mm)
        y += side + round(20 * px_per_mm)
    return page


def find(img) -> dict:
    """{id: {"centre_px": [x, y], "yaw_deg": direction of the marker's top edge, "side_px": mean side}}."""
    import cv2

    grey = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if hasattr(cv2.aruco, "ArucoDetector"):
        detector = _ARUCO_CACHE.get("detector")
        if detector is None:
            detector = cv2.aruco.ArucoDetector(_dictionary(), cv2.aruco.DetectorParameters())
            _ARUCO_CACHE["detector"] = detector
        corners, ids, _ = detector.detectMarkers(grey)
    else:  # OpenCV 4.6 (Ubuntu 24.04's python3-opencv)
        corners, ids, _ = cv2.aruco.detectMarkers(grey, _dictionary())
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
    s.add_argument("--ids", type=int, nargs="+", default=[50])
    s.add_argument("--faces", nargs="+", default=[""], help="one copy per face label, e.g. roof side")
    f = sub.add_parser("find")
    f.add_argument("frame")
    args = ap.parse_args(argv)
    if args.cmd == "sheet":
        cv2.imwrite(args.out, sheet(args.mm, args.ids, faces=args.faces))
        print(f"{args.out}: print at 100 % ({DPI} dpi), check one marker with a ruler")
    else:
        print(json.dumps(find(cv2.imread(args.frame)), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
