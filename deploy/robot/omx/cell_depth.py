"""Heights in the cell from the top depth camera, in the colour view's pixels: no ruler, no touch.

2026-11-01: a person's ruler, closed-jaw touches and hand-picked depth boxes all failed to give the belt's height.
The touches stopped at the planning floor, and a 16 g container slid away from the jaws without a contact. So the
heights come from the depth image instead:
- the table is the largest plane (RANSAC), and every height is measured from it, so a tilted camera does not matter;
- the depth view (wider field) is put onto the colour view by the scene's edges: the scale and shift where the
  colour image's edges lie closest to the height steps (`align_edges`). The object mask alone (`align`) slides
  along a row of objects standing in one line, as the cell's did on 2026-11-01;
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
    z = depth.astype(float)
    z_f = z / focal
    return np.dstack([(np.arange(w) - w / 2)[None, :] * z_f, (np.arange(h) - h / 2)[:, None] * z_f, z])


def _ransac(pts, tol_mm: float, tries: int, rng):
    """(unit normal, a point on it), inlier count: the plane with the most points within `tol_mm`."""
    normals, points_a = [], []
    for _ in range(tries):
        a, b, c = pts[rng.choice(len(pts), 3, replace=False)]
        u, v = b - a, c - a
        nx = float(u[1] * v[2] - u[2] * v[1])
        ny = float(u[2] * v[0] - u[0] * v[2])
        nz = float(u[0] * v[1] - u[1] * v[0])
        norm = (nx * nx + ny * ny + nz * nz) ** 0.5
        if norm < 1e-9:
            continue
        inv = -1.0 / norm if nz > 0 else 1.0 / norm
        normals.append((nx * inv, ny * inv, nz * inv))
        points_a.append(a)
    if not normals:
        return None, -1
    best, count = None, -1
    n_mat = np.asarray(normals, float)
    a_mat = np.asarray(points_a, float)
    offsets = np.sum(a_mat * n_mat, axis=1)
    for start in range(0, len(n_mat), 32):
        nb = n_mat[start:start + 32]
        ob = offsets[start:start + 32]
        diff = pts @ nb.T
        np.subtract(diff, ob, out=diff)
        np.abs(diff, out=diff)
        counts = (diff < tol_mm).sum(axis=0)
        idx = int(np.argmax(counts))
        if int(counts[idx]) > count:
            count = int(counts[idx])
            best = (nb[idx], a_mat[start + idx])
    return best, count


def table_plane(depth, tol_mm: float = PLANE_MM, tries: int = 400, seed: int = 0, share: float = 0.25):
    """(unit normal toward the camera, offset): the cell's table, refitted on its points. The view also holds a lower
    surface about 60 mm under the table, sometimes larger than it: of the two largest parallel planes the higher one is
    the table when it holds `share` of the larger's points (2026-11-01: the pallet read 75 mm in one frame, 10 in the
    next, as the plane flipped between them)."""
    h, w = depth.shape
    ys, xs = np.nonzero(depth > 0)
    ys, xs = ys[::7], xs[::7]
    z = depth[ys, xs].astype(float)
    pts = np.column_stack(((xs - w / 2) * (z / FOCAL_PX), (ys - h / 2) * (z / FOCAL_PX), z))
    rng = np.random.default_rng(seed)
    (n, a), k = _ransac(pts, tol_mm, tries, rng)
    rest = pts[np.abs(pts @ n - float(a @ n)) >= tol_mm]
    if len(rest) >= 3:
        (n2, a2), k2 = _ransac(rest, tol_mm, tries, rng)
        if k2 >= share * k and (a2 - a) @ n > 5 * tol_mm and abs(n2 @ n) > 0.98:
            n, a = n2, a2
    near = pts[np.abs(pts @ n - float(a @ n)) < tol_mm]
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
    h, w = depth.shape
    ray_dot = ((np.arange(w) - w / 2) * (normal[0] / FOCAL_PX))[None, :] + (
        (np.arange(h) - h / 2) * (normal[1] / FOCAL_PX) + normal[2]
    )[:, None]
    return np.where(depth > 0, depth * ray_dot + offset, np.nan)


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


def align_edges(colour, heights, scales=np.arange(0.55, 0.86, 0.01), reach: int = 40) -> tuple[np.ndarray, float]:
    """Colour -> depth affine (scale, shift) where the colour image's edges lie closest to the height steps, and the
    mean edge distance in depth pixels (lower is better). Every rim, plate and object counts, so objects standing
    in one row cannot leave the alignment loose as they do in `align`. Coarse grid, then one-pixel refinement."""
    import cv2

    hn = np.clip(np.nan_to_num(heights, nan=-100.0) + 100.0, 0, 255).astype(np.uint8)
    depth_edges = cv2.Canny(cv2.GaussianBlur(hn, (5, 5), 0), 10, 30)  # steps of a few mm
    grey = colour if colour.ndim == 2 else cv2.cvtColor(colour, cv2.COLOR_BGR2GRAY)
    ys, xs = np.nonzero(cv2.Canny(cv2.GaussianBlur(grey, (5, 5), 0), 40, 120))
    pts = np.c_[xs, ys].astype(float)[::3]
    dist = np.minimum(cv2.distanceTransform((depth_edges == 0).astype(np.uint8), cv2.DIST_L2, 3), 15.0)
    h, w = heights.shape
    min_ok = int(np.ceil(0.7 * len(pts)))

    def search_scale(s, tx_range, ty_range):
        if not len(pts):
            return (float("inf"), s, tx_range[0], ty_range[0])
        u0, v0 = pts[:, 0] * s, pts[:, 1] * s
        ui0, vi0 = np.floor(u0).astype(int), np.floor(v0).astype(int)
        best_s = (float("inf"), s, tx_range[0], ty_range[0])
        for tx in tx_range:
            ok_u = (u0 >= -tx) & (u0 < w - 1 - tx)
            if int(ok_u.sum()) < min_ok:
                continue
            ui = ui0 + tx
            for ty in ty_range:
                ok = ok_u & (v0 >= -ty) & (v0 < h - 1 - ty)
                k = int(ok.sum())
                if k >= min_ok:
                    c_val = float(dist[vi0[ok] + ty, ui[ok]].sum()) / k
                    if c_val < best_s[0]:
                        best_s = (c_val, s, tx, ty)
        return best_s

    best = min(search_scale(s, range(int(w * (1 - s) / 2) - reach, int(w * (1 - s) / 2) + reach + 1, 3),
                            range(int(h * (1 - s) / 2) - reach, int(h * (1 - s) / 2) + reach + 1, 3))
               for s in scales)
    _, s, tx, ty = best
    c, s, tx, ty = min(search_scale(s2, range(tx - 3, tx + 4), range(ty - 3, ty + 4))
                       for s2 in np.arange(s - 0.01, s + 0.011, 0.002))
    return np.float32([[s, 0, tx], [0, s, ty]]), c


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
    ap.add_argument("--hsv", default="5,120,120,22,255,255", help="object colour range: mask alignment, compared")
    args = ap.parse_args(argv)
    depth = np.fromfile(args.depth, np.uint16).reshape(480, 640)
    colour = cv2.imread(args.colour)
    lo_hi = [int(v) for v in args.hsv.split(",")]
    mask = cv2.inRange(cv2.cvtColor(colour, cv2.COLOR_BGR2HSV), tuple(lo_hi[:3]), tuple(lo_hi[3:]))
    heights = height_map(depth, table_plane(depth))
    m, edge_px = align_edges(colour, heights)
    m_mask, score = align(mask, heights)
    out = {"align": {"scale": round(float(m[0, 0]), 3), "shift": [float(m[0, 2]), float(m[1, 2])],
                     "edge_px": round(edge_px, 2)},
           "mask_align": {"shift": [float(m_mask[0, 2]), float(m_mask[1, 2])], "overlap": round(score, 2)},  # compare
           "heights_mm": {p: round(height_at(heights, m, [float(v) for v in p.split(",")]), 1) for p in args.px},
           "plates_mm": {b: plate_top(heights, m, [float(v) for v in b.split(",")]) for b in args.base}}
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
