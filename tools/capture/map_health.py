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


def walls_world(meta, h, grid):
    """Occupied cells as integer (ix, iy) on the world grid so two maps align by origin."""
    res, (ox, oy) = meta["resolution"], meta["origin"][:2]
    return {(round(ox / res) + c, round(oy / res) + (h - 1 - r))
            for r, row in enumerate(grid) for c, v in enumerate(row) if v == OCC}


def overlap(a, b):
    """Fraction of a's wall cells with a b wall within 1 cell (Chebyshev)."""
    if not a:
        return 0.0
    return sum(1 for x, y in a if any((x + dx, y + dy) in b for dx in (-1, 0, 1) for dy in (-1, 0, 1))) / len(a)


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
        wa, wb = walls_world(meta, h, grid), walls_world(m2, h2, g2)
        rep["compare"] = {"other": a.compare, "overlap_a_in_b": round(overlap(wa, wb), 3),
                          "overlap_b_in_a": round(overlap(wb, wa), 3)}
    print(json.dumps(rep, indent=2))
    return 1 if rep["verdict"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
