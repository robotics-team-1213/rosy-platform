"""Heights in the cell from the top depth camera, in the colour view's pixels: no ruler, no touch.

2026-11-01: a person's ruler, closed-jaw touches and hand-picked depth boxes all failed to give the belt's height.
The touches stopped at the planning floor, and a 16 g container slid away from the jaws without a contact. So the
heights come from the depth image instead:
- the table is the largest plane (RANSAC), and every height is measured from it, so a tilted camera does not matter;
- the depth view (wider field) is put onto the colour view by the containers themselves: the scale and shift where
  the colour mask of the objects lands best on what stands up in depth;
- an arm's FK zero is the top of the plate it stands on, read in a ring around its base.

The D435 runs without its SDK here (USB 2.0, v4l2 Z16), so its intrinsics are nominal (`FOCAL_PX`).

    python cell_depth.py --depth d.raw --colour c.jpg --px 345,80 --px 330,320   # read only
"""
from __future__ import annotations

import argparse
import json

import numpy as np

FOCAL_PX = 385.0  # D435 depth at 640 x 480, nominal
PLANE_MM = 4.0
RAISED_MM = (18.0, 120.0)  # what stands up from the table: containers, stacks (not the 10 mm pallet)


def points(depth, focal: float = FOCAL_PX):
    """(h, w, 3) camera-frame points in mm; zero depth (no return) stays zero."""
    h, w = depth.shape
    ys, xs = np.mgrid[0:h, 0:w]
    z = depth.astype(float)
    return np.dstack([(xs - w / 2) * z / focal, (ys - h / 2) * z / focal, z])


def table_plane(depth, tol_mm: float = PLANE_MM, tries: int = 400, seed: int = 0):
    """(unit normal toward the camera, offset): the plane with the most points within `tol_mm`, refitted on them."""
    pts = points(depth)[depth > 0][::7]
    rng, best, count = np.random.default_rng(seed), None, -1
    for _ in range(tries):
        a, b, c = pts[rng.choice(len(pts), 3, replace=False)]
        n = np.cross(b - a, c - a)
        if np.linalg.norm(n) < 1e-9:
            continue
        n = n / np.linalg.norm(n)
        k = int((np.abs((pts - a) @ n) < tol_mm).sum())
        if k > count:
            best, count = (n, a), k
    n, a = best
    near = pts[np.abs((pts - a) @ n) < tol_mm]
    _, _, vt = np.linalg.svd(np.c_[near, np.ones(len(near))], full_matrices=False)
    normal, offset = vt[-1][:3], vt[-1][3]
    scale = np.linalg.norm(normal)
    normal, offset = normal / scale, offset / scale
    if normal[2] > 0:  # +height is toward the camera (smaller depth)
        normal, offset = -normal, -offset
    return normal, offset


def height_map(depth, plane) -> np.ndarray:
    """mm above the table plane; NaN where the camera had no return."""
    normal, offset = plane
    return np.where(depth > 0, points(depth) @ normal + offset, np.nan)


def align(object_mask, heights, scales=np.arange(0.55, 0.86, 0.01), step: int = 2) -> tuple[np.ndarray, float]:
    """Colour -> depth affine (scale, shift) where the colour object mask lies best on the raised depth pixels, and
    that overlap (0..1). Searched on half-size images, then refined by one pixel around the best."""
    import cv2

    raised = ((np.nan_to_num(heights) > RAISED_MM[0]) & (np.nan_to_num(heights) < RAISED_MM[1])).astype(np.uint8)
    raised = cv2.morphologyEx(raised, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    om = (object_mask > 0).astype(np.uint8)
    h, w = raised.shape

    def overlap(m, src, dst, size):
        warped = cv2.warpAffine(src, m, size, flags=cv2.INTER_NEAREST)
        return (warped & dst).sum() / max(1, warped.sum())

    small = (cv2.resize(om, (om.shape[1] // 2, om.shape[0] // 2), interpolation=cv2.INTER_NEAREST),
             cv2.resize(raised, (w // 2, h // 2), interpolation=cv2.INTER_NEAREST))
    best, score = None, -1.0
    for s in scales:  # shifts within 40 px of a centred view (the colour lens sits beside the depth one)
        cx, cy = w * (1 - s) / 4, h * (1 - s) / 4  # half-size
        for tx in range(int(cx) - 20, int(cx) + 21, step):
            for ty in range(int(cy) - 20, int(cy) + 21, step):
                v = overlap(np.float32([[s, 0, tx], [0, s, ty]]), *small, (w // 2, h // 2))
                if v > score:
                    best, score = (s, 2 * tx, 2 * ty), v
    s, tx, ty = best
    for dx in range(-2, 3):
        for dy in range(-2, 3):
            m = np.float32([[s, 0, tx + dx], [0, s, ty + dy]])
            v = overlap(m, om, raised, (w, h))
            if v >= score:
                best, score = (s, tx + dx, ty + dy), v
    s, tx, ty = best
    return np.float32([[s, 0, tx], [0, s, ty]]), float(score)


def height_at(heights, to_depth, px, r: int = 4) -> float:
    """Median height (mm) within `r` depth pixels of where colour pixel `px` lands."""
    x, y = np.round(to_depth @ [px[0], px[1], 1.0]).astype(int)
    patch = heights[max(0, y - r):y + r + 1, max(0, x - r):x + r + 1]
    return float(np.nanmedian(patch)) if np.isfinite(patch).any() else float("nan")


def plate_top(heights, to_depth, base_px, radius_px: float = 45.0, plate_mm=(8.0, 35.0)) -> float | None:
    """The plate an arm stands on, read in a ring around its base (colour pixel): the median of the ring samples
    in the plate's height range. Links and cables crossing the ring read higher and are left out."""
    ring = [height_at(heights, to_depth, (base_px[0] + radius_px * np.cos(t), base_px[1] + radius_px * np.sin(t)), 2)
            for t in np.linspace(0, 2 * np.pi, 36, endpoint=False)]
    on = [v for v in ring if plate_mm[0] <= v <= plate_mm[1]]
    return float(np.median(on)) if len(on) >= 4 else None


def main(argv=None) -> int:
    import cv2

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--depth", required=True, help="raw Z16, 640 x 480, mm")
    ap.add_argument("--colour", required=True)
    ap.add_argument("--px", action="append", default=[], help="x,y colour pixel to report a height for")
    ap.add_argument("--base", action="append", default=[], help="x,y colour pixel of an arm's base (its plate)")
    ap.add_argument("--hsv", default="5,120,120,22,255,255", help="object colour range for the alignment")
    args = ap.parse_args(argv)
    depth = np.fromfile(args.depth, np.uint16).reshape(480, 640)
    colour = cv2.imread(args.colour)
    lo_hi = [int(v) for v in args.hsv.split(",")]
    mask = cv2.inRange(cv2.cvtColor(colour, cv2.COLOR_BGR2HSV), tuple(lo_hi[:3]), tuple(lo_hi[3:]))
    heights = height_map(depth, table_plane(depth))
    m, score = align(mask, heights)
    out = {"align": {"scale": round(float(m[0, 0]), 3), "shift": [float(m[0, 2]), float(m[1, 2])], "overlap": round(score, 2)},
           "heights_mm": {p: round(height_at(heights, m, [float(v) for v in p.split(",")]), 1) for p in args.px},
           "plates_mm": {b: plate_top(heights, m, [float(v) for v in b.split(",")]) for b in args.base}}
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
