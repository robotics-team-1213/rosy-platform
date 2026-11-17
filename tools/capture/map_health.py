#!/usr/bin/env python3
"""Health check for a REAL SLAM map (slam_toolbox save_map pgm + yaml), stdlib only.

The sim-map rule "border cells not occupied" (map_bundle check) fails on real maps, so this judges
what a real map must show: walls exist, little speckle, a usable free region, resolution as expected.
  python map_health.py MAP.yaml [--compare OTHER.yaml] [--allow-resolution R]
Exit 0 ok/warn, 1 fail. Pure functions; no robot, no ROS."""
import argparse
import json
import sys
from collections import deque
from pathlib import Path

OCC, FREE, UNK = 2, 0, 1


def parse_pgm(data):
    """P5 bytes -> (w, h, rows of ints). Comments (#) allowed in the header."""
    toks, i = [], 0
    while len(toks) < 4:
        while data[i:i + 1].isspace():
            i += 1
        if data[i:i + 1] == b"#":
            while data[i:i + 1] not in (b"\n", b""):
                i += 1
            continue
        j = i
        while j < len(data) and not data[j:j + 1].isspace():
            j += 1
        toks.append(data[i:j])
        i = j
    if toks[0] != b"P5" or int(toks[3]) > 255:
        raise ValueError("not an 8-bit P5 pgm")
    w, h = int(toks[1]), int(toks[2])
    px = data[i + 1:i + 1 + w * h]
    if len(px) != w * h:
        raise ValueError("pgm pixel data truncated")
    return w, h, [list(px[r * w:(r + 1) * w]) for r in range(h)]


def parse_yaml(text):
    """The few flat keys map_server writes; origin is a [x, y, yaw] flow list."""
    out = {}
    for line in text.splitlines():
        if ":" in line and not line.lstrip().startswith("#"):
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return {"image": out["image"], "resolution": float(out["resolution"]),
            "origin": [float(x) for x in out["origin"].strip("[]").split(",")],
            "negate": int(out.get("negate", 0)),
            "occ": float(out.get("occupied_thresh", 0.65)), "free": float(out.get("free_thresh", 0.196))}


def load(yaml_path):
    yp = Path(yaml_path)
    meta = parse_yaml(yp.read_text(encoding="utf-8"))
    w, h, rows = parse_pgm((yp.parent / meta["image"]).read_bytes())
    grid = []
    for row in rows:
        g = []
        for v in row:
            p = v / 255 if meta["negate"] else (255 - v) / 255
            g.append(OCC if p > meta["occ"] else FREE if p < meta["free"] else UNK)
        grid.append(g)
    return meta, w, h, grid


def _flood(grid, w, h, seeds, passable):
    seen = set(seeds)
    q = deque(seeds)
    while q:
        r, c = q.popleft()
        for rr, cc in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
            if 0 <= rr < h and 0 <= cc < w and (rr, cc) not in seen and grid[rr][cc] in passable:
                seen.add((rr, cc))
                q.append((rr, cc))
    return seen


def analyze(meta, w, h, grid):
    cells = [(r, c) for r in range(h) for c in range(w)]
    occ = [(r, c) for r, c in cells if grid[r][c] == OCC]
    free = [(r, c) for r, c in cells if grid[r][c] == FREE]
    speckle = sum(1 for r, c in occ if not any(
        0 <= r + dr < h and 0 <= c + dc < w and grid[r + dr][c + dc] == OCC
        for dr in (-1, 0, 1) for dc in (-1, 0, 1) if (dr, dc) != (0, 0)))
    largest, left = 0, set(free)
    while left:
        comp = _flood(grid, w, h, [next(iter(left))], (FREE,))
        left -= comp
        if len(comp) > len(largest if isinstance(largest, set) else ()):
            largest = comp
    largest = largest if isinstance(largest, set) else set()
    # openings: border cells the largest free region reaches through free/unknown (a closed wall ring reaches none)
    reach = _flood(grid, w, h, list(largest)[:1], (FREE, UNK)) if largest else set()
    openings = sum(1 for r, c in reach if r in (0, h - 1) or c in (0, w - 1))
    return {"cells": len(cells), "occupied": len(occ), "free": len(free), "unknown": len(cells) - len(occ) - len(free),
            "wall_cells": len(occ), "free_ratio": round(len(free) / len(cells), 3) if cells else 0.0,
            "largest_free_region_cells": len(largest), "enclosed": openings == 0, "openings": openings,
            "speckle": speckle, "resolution": meta["resolution"], "origin": meta["origin"]}


def verdict(rep, allow_resolution=None):
    res, fail, warn = rep["resolution"], [], []
    want = allow_resolution or 0.05
    if rep["occupied"] == 0:
        fail.append("no occupied cells")
    if abs(res - want) > 0.01:
        fail.append(f"resolution {res} not {want}+-0.01")
    if rep["largest_free_region_cells"] * res * res < 1.0:
        fail.append("largest free region under 1 m^2")
    if rep["occupied"] and rep["speckle"] / rep["occupied"] > 0.30:
        fail.append(f"speckle {rep['speckle']}/{rep['occupied']} occupied cells isolated (>30%)")
    if rep["openings"]:
        warn.append(f"{rep['openings']} border cells reachable from the free region (opening)")
    if rep["cells"] and rep["unknown"] / rep["cells"] > 0.60:
        warn.append("unknown above 60%")
    return {"verdict": "fail" if fail else "warn" if warn else "ok", "reasons": fail + warn}


def wall_points(meta, h, grid):
    """Occupied cell centres in world metres (map origin is the bottom-left corner, pgm row 0 is the top)."""
    res, (ox, oy) = meta["resolution"], meta["origin"][:2]
    return [(ox + (c + .5) * res, oy + (h - 1 - r + .5) * res) for r, row in enumerate(grid) for c, v in enumerate(row) if v == OCC]


def _dilated(pts, res):
    """Cell indices within 1 cell of any wall point, so a match is one set lookup."""
    return {(int(x // res) + i, int(y // res) + j) for x, y in pts for i in (-1, 0, 1) for j in (-1, 0, 1)}


def _score(pts, tab, res, deg, tx, ty):
    import math
    ca, sa = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return sum(1 for x, y in pts if (int((ca * x - sa * y + tx) // res), int((sa * x + ca * y + ty) // res)) in tab) / len(pts)


def align(a, b, res, max_deg=30, max_t=0.3):
    """Rigid search of a's walls into b's frame (rotation about the world origin, then shift): coarse grid, then refine.
    Returns (overlap, rotation_deg, tx_m, ty_m, origin_only_overlap). Wall cells are matched within 1 cell."""
    if not a or not b:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    tab = _dilated(b, res)
    frange = lambda c, half, st: [c + k * st for k in range(-round(half / st), round(half / st) + 1)]
    best = max((_score(a, tab, res, d, tx, ty), -abs(d) - abs(tx) - abs(ty), d, tx, ty)
               for d in frange(0, max_deg, 2) for tx in frange(0, max_t, .1) for ty in frange(0, max_t, .1))
    _, _, d0, x0, y0 = best
    best = max((_score(a, tab, res, d, tx, ty), -abs(d - d0) - abs(tx - x0) - abs(ty - y0), d, tx, ty)
               for d in frange(d0, 2, .5) for tx in frange(x0, .1, .025) for ty in frange(y0, .1, .025))
    return (round(best[0], 3), round(best[2], 2), round(best[3], 3), round(best[4], 3),
            round(_score(a, tab, res, 0, 0, 0), 3))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("yaml")
    ap.add_argument("--compare")
    ap.add_argument("--allow-resolution", type=float)
    a = ap.parse_args(argv)
    meta, w, h, grid = load(a.yaml)
    rep = analyze(meta, w, h, grid)
    rep.update(verdict(rep, a.allow_resolution))
    if a.compare:
        m2, _, h2, g2 = load(a.compare)
        ov, rot, tx, ty, ov0 = align(wall_points(meta, h, grid), wall_points(m2, h2, g2), meta["resolution"])
        rep["compare"] = {"other": a.compare, "overlap": ov, "rotation_deg": rot, "tx_m": tx, "ty_m": ty,
                          "origin_only_overlap": ov0}
    print(json.dumps(rep, indent=2))
    return 1 if rep["verdict"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
