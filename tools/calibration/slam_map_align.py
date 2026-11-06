#!/usr/bin/env python3
"""Fit a robot SLAM occupancy map (nav2 map yaml + PGM) to the Fleet site map frame.

Offline. Reads known correspondences ``SITE=SLAM`` (a place name/id from ``--site-map`` or ``x,y`` in the
site frame, paired with ``x,y`` in the SLAM map frame), fits a 2D rigid transform (rotation + translation,
no scale) ``site = R * slam + t`` by least squares, and refuses (exit 3) when the worst residual passes
``--max-residual`` (default 0.05 m, a third of the 0.15 m ``max_jump_m`` sighting gate in
``rosy.world.state.projections.map_pose``).

Rigid fits from few points can hide a 180 degree flip or a mirror image, so it also reports the best fit with
the yaw turned 180 degrees (refused as ambiguous when that fits the gate too), a mirror check, and how much
of the occupied boundary lands on itself under a 180 degree turn (a rectangular arena does).

``--write OUT.yaml`` writes a new map in the site frame and never touches the input. Nav2 does not honour a
non-zero origin yaw (see ``write_aligned``), so a rotated map is resampled into a new PGM with yaw 0.

    python tools/calibration/slam_map_align.py MAP.yaml --site-map site.json \
        --pair S1=0.42,0.31 --pair C1=1.10,0.28 --pair 1.2,0.6=0.95,1.40 [--write OUT.yaml]
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

DEFAULT_MAX_RESIDUAL_M = 0.05
MIN_SPREAD_M = 0.05  # rms distance of the points from their best line; below this they are collinear
AMBIGUOUS_SCORE = 0.9  # boundary share that lands on itself after a 180 degree turn
REFUSED = 3


class AlignError(Exception):
    """Input or fit the tool refuses (exit 3)."""


@dataclass
class Fit:
    yaw: float
    tx: float
    ty: float
    residuals: list[float]

    @property
    def max(self) -> float:
        return max(self.residuals)

    @property
    def rms(self) -> float:
        return math.sqrt(sum(r * r for r in self.residuals) / len(self.residuals))

    def apply(self, p):
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        return (c * p[0] - s * p[1] + self.tx, s * p[0] + c * p[1] + self.ty)


def _spread(pts: np.ndarray) -> float:
    centred = pts - pts.mean(axis=0)
    return float(math.sqrt(np.linalg.eigvalsh(centred.T @ centred / len(pts))[0]))


def _residuals(slam, site, yaw):
    c, s = math.cos(yaw), math.sin(yaw)
    rot = np.array([[c, -s], [s, c]])
    src = slam
    t = site.mean(axis=0) - rot @ src.mean(axis=0)
    return Fit(yaw, float(t[0]), float(t[1]), list(np.linalg.norm(src @ rot.T + t - site, axis=1)))


def fit_rigid(slam, site) -> Fit:
    """Least-squares site = R*slam + t (Kabsch in 2D). Refuses fewer than 3 or collinear points."""
    slam, site = np.asarray(slam, float), np.asarray(site, float)
    if len(slam) < 3:
        raise AlignError(f"need at least 3 correspondences, got {len(slam)}")
    for name, pts in (("SLAM", slam), ("site", site)):
        if _spread(pts) < MIN_SPREAD_M:
            raise AlignError(f"{name} points are collinear (rms off-line spread < {MIN_SPREAD_M} m): "
                             "rotation about the line is under-determined, add a point off the line")
    a, b = slam - slam.mean(axis=0), site - site.mean(axis=0)
    yaw = math.atan2(float(np.sum(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0])),
                     float(np.sum(a[:, 0] * b[:, 0] + a[:, 1] * b[:, 1])))
    return _residuals(slam, site, yaw)


def flipped_fit(slam, site, fit: Fit) -> Fit:
    """Best translation for the yaw turned 180 degrees: if this fits too, the points cannot tell the two apart."""
    return _residuals(np.asarray(slam, float), np.asarray(site, float), fit.yaw + math.pi)


def mirror_fit(slam, site) -> Fit:
    """Best fit if the SLAM y axis were flipped (a proper-rotation fit of the mirrored points)."""
    return fit_rigid(np.asarray(slam, float) * np.array([1.0, -1.0]), site)


# ---------------------------------------------------------------- map files

@dataclass
class Grid:
    cells: np.ndarray  # [row_from_bottom, col]: 0 free, 1 occupied, -1 unknown
    resolution: float
    origin: tuple[float, float]

    def occupied_points(self) -> np.ndarray:
        j, i = np.nonzero(self.cells == 1)
        return np.stack([self.origin[0] + (i + 0.5) * self.resolution,
                         self.origin[1] + (j + 0.5) * self.resolution], axis=1)


def _read_pgm(path: Path) -> np.ndarray:
    data = path.read_bytes()
    tokens, pos = [], 0
    while len(tokens) < 4:
        m = re.compile(rb"\s*(#[^\n]*\n\s*)*(\S+)").match(data, pos)
        tokens.append(m.group(2))
        pos = m.end()
    magic, w, h, maxval = tokens[0], int(tokens[1]), int(tokens[2]), int(tokens[3])
    if magic != b"P5" or maxval > 255:
        raise AlignError(f"{path}: only 8-bit binary PGM (P5) is supported")
    return np.frombuffer(data[pos + 1:pos + 1 + w * h], np.uint8).reshape(h, w)


def load_map(yaml_path: Path) -> Grid:
    meta = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    pix = _read_pgm(yaml_path.parent / meta["image"]).astype(float)
    occ = pix / 255.0 if meta.get("negate", 0) else (255.0 - pix) / 255.0
    cells = np.full(occ.shape, -1, np.int8)
    cells[occ < meta.get("free_thresh", 0.25)] = 0
    cells[occ > meta.get("occupied_thresh", 0.65)] = 1
    if meta.get("mode", "trinary") != "trinary":
        raise AlignError("only mode: trinary maps are supported")
    return Grid(cells[::-1].copy(), float(meta["resolution"]), (float(meta["origin"][0]), float(meta["origin"][1])))


def boundary_symmetry(cells: np.ndarray) -> float:
    """Share of occupied cells that land on an occupied cell (3x3 tolerance, best +-2 cell shift) after a
    180 degree turn about the occupied bounding box. 1.0 means the boundary alone cannot tell 180 degrees apart."""
    j, i = np.nonzero(cells == 1)
    if len(j) == 0:
        return 0.0
    occ = (cells == 1)[j.min():j.max() + 1, i.min():i.max() + 1]
    turned = np.pad(occ[::-1, ::-1], 3)
    best = 0.0
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            hit = np.zeros_like(occ)
            for ey in (-1, 0, 1):
                for ex in (-1, 0, 1):
                    y0, x0 = 3 + dy + ey, 3 + dx + ex
                    hit |= turned[y0:y0 + occ.shape[0], x0:x0 + occ.shape[1]]
            best = max(best, float((occ & hit).sum()) / float(occ.sum()))
    return best


def write_aligned(grid: Grid, fit: Fit, out_yaml: Path, source: dict) -> str:
    """Write the grid in the site frame. Evidence for rotating the grid rather than putting yaw in the origin
    (navigation2 jazzy, the installed 1.3.13): ``nav2_map_server`` map_io.cpp does publish origin[2] as the
    OccupancyGrid orientation, but ``nav2_costmap_2d`` static_layer.cpp only reads ``origin.position.x/y``
    (grep for yaw/orientation finds nothing) and ``nav2_amcl`` map conversion only reads position, so a yaw
    in the yaml shifts nothing in the planner or localiser. The cells are resampled (nearest) into a new PGM."""
    out_pgm = out_yaml.with_suffix(".pgm")
    h, w = grid.cells.shape
    r = grid.resolution
    c, s = math.cos(fit.yaw), math.sin(fit.yaw)
    corners = [fit.apply((grid.origin[0] + a * w * r, grid.origin[1] + b * h * r)) for a in (0, 1) for b in (0, 1)]
    x0, y0 = min(p[0] for p in corners), min(p[1] for p in corners)
    nw, nh = math.ceil((max(p[0] for p in corners) - x0) / r), math.ceil((max(p[1] for p in corners) - y0) / r)
    qx = x0 + (np.arange(nw) + 0.5) * r - fit.tx
    qy = y0 + (np.arange(nh) + 0.5) * r - fit.ty
    gx, gy = np.meshgrid(qx, qy)
    px, py = c * gx + s * gy, -s * gx + c * gy  # R^T (q - t)
    ci = np.floor((px - grid.origin[0]) / r).astype(int)
    cj = np.floor((py - grid.origin[1]) / r).astype(int)
    inside = (ci >= 0) & (ci < w) & (cj >= 0) & (cj < h)
    new = np.full((nh, nw), -1, np.int8)
    new[inside] = grid.cells[cj[inside], ci[inside]]
    pix = np.select([new == 1, new == 0], [0, 254], 205).astype(np.uint8)[::-1]
    out_pgm.write_bytes(b"P5\n# slam_map_align.py: site frame\n" + f"{nw} {nh}\n255\n".encode() + pix.tobytes())
    out_yaml.write_text(
        f"image: {out_pgm.name}\nmode: trinary\nresolution: {r}\n"
        f"origin: [{x0:.4f}, {y0:.4f}, 0.0]\nnegate: 0\noccupied_thresh: {source.get('occupied_thresh', 0.65)}\n"
        f"free_thresh: {source.get('free_thresh', 0.196)}\n", encoding="utf-8")
    return f"{out_yaml} ({nw}x{nh} cells, origin {x0:.3f},{y0:.3f}, yaw 0)"


# ---------------------------------------------------------------- correspondences

def _xy(text: str):
    parts = text.split(",")
    if len(parts) != 2:
        raise AlignError(f"expected x,y, got {text!r}")
    try:
        return float(parts[0]), float(parts[1])
    except ValueError as exc:
        raise AlignError(f"expected numbers in {text!r}") from exc


def parse_pairs(pairs: list[str], places: dict[str, tuple[float, float]]):
    slam, site = [], []
    for pair in pairs:
        left, sep, right = pair.partition("=")
        if not sep:
            raise AlignError(f"pair {pair!r} needs SITE=SLAM")
        if left in places:
            site.append(places[left])
        elif re.match(r"^-?[\d.]+,", left):
            site.append(_xy(left))
        else:
            raise AlignError(f"unknown place {left!r} (known: {', '.join(sorted(places)) or 'none, pass --site-map'})")
        slam.append(_xy(right))
    return slam, site


def load_places(path: Path | None) -> dict[str, tuple[float, float]]:
    if path is None:
        return {}
    body = json.loads(path.read_text(encoding="utf-8"))
    body = body.get("map", body) if isinstance(body, dict) else body
    places = {}
    for p in body["places"]:
        places[p["id"]] = places[p.get("name", p["id"])] = (float(p["x"]), float(p["y"]))
    return places


def align(slam, site, max_residual: float, symmetry: float | None = None, allow_ambiguous: bool = False):
    """Fit and judge. Returns (fit, warnings). Raises AlignError on any refusal."""
    fit, notes = fit_rigid(slam, site), []
    if fit.max > max_residual:
        mirror = mirror_fit(slam, site)
        hint = (f" The mirror image fits ({mirror.max:.3f} m max): these correspondences look mirrored "
                "(an axis flipped, or the points listed in a different order).") if mirror.max <= max_residual else ""
        raise AlignError(f"max residual {fit.max:.3f} m exceeds {max_residual} m.{hint}")
    flip = flipped_fit(slam, site, fit)
    if flip.max <= max_residual:
        msg = (f"AMBIGUOUS: the 180-degree-rotated alternative also fits (max {flip.max:.3f} m, rms {flip.rms:.3f} m "
               f"vs {fit.max:.3f}/{fit.rms:.3f}); add points far from the arena centre or off the symmetry")
        if not allow_ambiguous:
            raise AlignError(msg + " (--allow-ambiguous to accept)")
        notes.append(msg)
    elif flip.rms < 2 * fit.rms + 0.02:
        notes.append(f"warning: the 180-degree alternative is close (rms {flip.rms:.3f} vs {fit.rms:.3f} m)")
    if symmetry is not None and symmetry >= AMBIGUOUS_SCORE:
        notes.append(f"warning: the occupied boundary is {symmetry:.0%} self-similar under 180 degrees; "
                     "only the correspondences fix the heading")
    return fit, notes, flip


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("map_yaml", type=Path, help="nav2 map yaml of the SLAM map (any path)")
    ap.add_argument("--pair", action="append", default=[], metavar="SITE=SLAM",
                    help="SITE is a place name/id (needs --site-map) or x,y; SLAM is x,y. Repeat, 3+ not collinear")
    ap.add_argument("--site-map", type=Path, help="site map JSON with a places list (id, name, x, y)")
    ap.add_argument("--max-residual", type=float, default=DEFAULT_MAX_RESIDUAL_M)
    ap.add_argument("--allow-ambiguous", action="store_true")
    ap.add_argument("--write", type=Path, metavar="OUT.yaml", help="new aligned map yaml (+ PGM beside it)")
    args = ap.parse_args(argv)
    try:
        slam, site = parse_pairs(args.pair, load_places(args.site_map))
        grid = load_map(args.map_yaml)
        sym = boundary_symmetry(grid.cells)
        fit, notes, flip = align(slam, site, args.max_residual, sym, args.allow_ambiguous)
        print(f"site = R(yaw) * slam + t: yaw {math.degrees(fit.yaw):.3f} deg, t = ({fit.tx:.4f}, {fit.ty:.4f}) m")
        for (sx, sy), (px, py), res in zip(site, slam, fit.residuals):
            print(f"  site ({sx:.3f},{sy:.3f}) <- slam ({px:.3f},{py:.3f}): residual {res:.4f} m")
        print(f"max {fit.max:.4f} m, rms {fit.rms:.4f} m (gate {args.max_residual} m)")
        print(f"180-degree alternative: max {flip.max:.4f} m, rms {flip.rms:.4f} m")
        print(f"boundary 180-degree self-similarity: {sym:.2f}")
        for n in notes:
            print(n)
        if args.write:
            src = {Path(args.map_yaml).resolve(), Path(args.map_yaml).with_name(
                yaml.safe_load(args.map_yaml.read_text(encoding="utf-8"))["image"]).resolve()}
            if args.write.resolve() in src or args.write.with_suffix(".pgm").resolve() in src:
                raise AlignError("--write would overwrite the input map")
            if args.write.exists() or args.write.with_suffix(".pgm").exists():
                raise AlignError(f"{args.write} (or its PGM) exists; refusing to overwrite")
            print("wrote", write_aligned(grid, fit, args.write, yaml.safe_load(args.map_yaml.read_text(encoding="utf-8"))))
    except AlignError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return REFUSED
    return 0


if __name__ == "__main__":
    sys.exit(main())
