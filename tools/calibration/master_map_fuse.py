#!/usr/bin/env python3
"""Offline consensus fusion of multiple site-aligned yaw=0 Pinky SLAM maps into one master map.

Pure offline tool: takes two or more maps already aligned to the site frame with origin yaw = 0
(e.g. via ``slam_map_align.py``), verifies pairwise static-wall overlap >= ``--min-overlap``,
keeps multi-view consensus static walls (with 1-cell dilation tolerance) plus single-view blind
spots, drops transient dynamic obstacles (e.g. peer robots or boxes seen in only one pass while
other passes observe free space), enforces health gates, and optionally seals via ``map_bundle.py``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import tempfile
from pathlib import Path

import numpy as np
import yaml

import slam_map_align as sma

DEFAULT_MIN_OVERLAP = 0.70
DEFAULT_MIN_SUPPORT = 2
DEFAULT_MAX_SPECKLE_RATIO = 0.30
DEFAULT_MIN_FREE_M2 = 1.0


def load_aligned_map(yaml_path: Path) -> tuple[sma.Grid, dict, str]:
    """Load an already site-aligned yaw=0 Nav2 map, refusing missing files or non-zero origin yaw."""
    try:
        meta = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        if not isinstance(meta, dict) or "origin" not in meta or "image" not in meta:
            raise ValueError("invalid Nav2 map yaml")
        origin = meta["origin"]
        if not isinstance(origin, (list, tuple)) or len(origin) != 3:
            raise ValueError("origin must have 3 elements")
        yaw = float(origin[2])
        if not math.isfinite(yaw) or abs(yaw) > 1e-6:
            raise sma.AlignError(f"{yaml_path}: non-zero origin yaw ({yaw}); align via slam_map_align.py first")
        grid = sma.load_map(yaml_path)
        pgm_sha = hashlib.sha256((yaml_path.parent / meta["image"]).read_bytes()).hexdigest()
    except sma.AlignError:
        raise
    except (OSError, yaml.YAMLError, ValueError, TypeError, IndexError, KeyError) as exc:
        raise sma.AlignError(f"{yaml_path}: cannot load aligned map: {exc}") from exc
    return grid, meta, pgm_sha


def dilate_occupied(occ: np.ndarray) -> np.ndarray:
    """3x3 binary dilation using padded slices (no SciPy dependency)."""
    h, w = occ.shape
    padded = np.pad(occ.astype(bool), 1, constant_values=False)
    out = np.zeros((h, w), dtype=bool)
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            out |= padded[1 + dr:1 + dr + h, 1 + dc:1 + dc + w]
    return out


def wall_overlap(cells_a: np.ndarray, cells_b: np.ndarray) -> float:
    """Symmetric minimum of 1-cell-dilated occupied-wall recall between two aligned canvases."""
    occ_a = cells_a == 1
    occ_b = cells_b == 1
    cnt_a, cnt_b = int(occ_a.sum()), int(occ_b.sum())
    if cnt_a == 0 or cnt_b == 0:
        return 0.0
    rec_ab = float((occ_a & dilate_occupied(occ_b)).sum()) / float(cnt_a)
    rec_ba = float((occ_b & dilate_occupied(occ_a)).sum()) / float(cnt_b)
    return min(rec_ab, rec_ba)


def resample_to_canvas(grid: sma.Grid, origin: tuple[float, float], width: int, height: int) -> np.ndarray:
    """Sample `grid.cells` onto `(origin, width, height)` in world coordinates (out of bounds = -1)."""
    r = grid.resolution
    h, w = grid.cells.shape
    qx = origin[0] + (np.arange(width) + 0.5) * r
    qy = origin[1] + (np.arange(height) + 0.5) * r
    gx, gy = np.meshgrid(qx, qy)
    ci = np.floor((gx - grid.origin[0]) / r).astype(int)
    cj = np.floor((gy - grid.origin[1]) / r).astype(int)
    inside = (ci >= 0) & (ci < w) & (cj >= 0) & (cj < h)
    out = np.full((height, width), -1, np.int8)
    out[inside] = grid.cells[cj[inside], ci[inside]]
    return out


def _speckle_count(occ: np.ndarray) -> int:
    h, w = occ.shape
    padded = np.pad(occ.astype(bool), 1, constant_values=False)
    nbrs = np.zeros((h, w), dtype=np.int32)
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if (dr, dc) != (0, 0):
                nbrs += padded[1 + dr:1 + dr + h, 1 + dc:1 + dc + w]
    return int((occ & (nbrs == 0)).sum())


def fuse_aligned_grids(
    grids: list[sma.Grid],
    *,
    min_overlap: float = DEFAULT_MIN_OVERLAP,
    min_support: int = DEFAULT_MIN_SUPPORT,
    max_speckle_ratio: float = DEFAULT_MAX_SPECKLE_RATIO,
    min_free_m2: float = DEFAULT_MIN_FREE_M2,
) -> tuple[sma.Grid, dict]:
    """Consensus-fuse 2+ site-aligned yaw=0 grids into one verified master occupancy grid."""
    if len(grids) < 2:
        raise sma.AlignError(f"need at least 2 aligned maps to fuse, got {len(grids)}")
    req_support = int(min_support)
    if not 1 <= req_support <= len(grids):
        raise sma.AlignError(f"min_support {req_support} must be in 1..{len(grids)}")
    res = float(grids[0].resolution)
    for idx, g in enumerate(grids):
        if abs(float(g.resolution) - res) > 1e-9:
            raise sma.AlignError(f"map {idx} resolution {g.resolution} != {res}")
        if int((g.cells == 1).sum()) == 0 or int((g.cells == 0).sum()) == 0:
            raise sma.AlignError(f"map {idx} lacks occupied or free cells")
    x0 = min(g.origin[0] for g in grids)
    y0 = min(g.origin[1] for g in grids)
    x1 = max(g.origin[0] + g.cells.shape[1] * res for g in grids)
    y1 = max(g.origin[1] + g.cells.shape[0] * res for g in grids)
    nw = max(1, math.ceil((x1 - x0) / res - 1e-9))
    nh = max(1, math.ceil((y1 - y0) / res - 1e-9))
    canvases = [resample_to_canvas(g, (x0, y0), nw, nh) for g in grids]

    overlaps = []
    for i in range(len(canvases)):
        for j in range(i + 1, len(canvases)):
            ov = wall_overlap(canvases[i], canvases[j])
            overlaps.append({"pair": [i, j], "overlap": round(ov, 4)})
    min_ov = min(row["overlap"] for row in overlaps)
    if min_ov < min_overlap:
        raise sma.AlignError(f"pairwise wall overlap {min_ov:.3f} below gate {min_overlap:.3f}")

    occ_masks = [c == 1 for c in canvases]
    free_masks = [c == 0 for c in canvases]
    n_occ = sum(m.astype(np.int32) for m in occ_masks)
    n_free = sum(m.astype(np.int32) for m in free_masks)
    n_obs = n_occ + n_free
    support = sum(dilate_occupied(m).astype(np.int32) for m in occ_masks)
    needed = np.minimum(req_support, n_obs)

    keep_wall = (n_occ >= 1) & (support >= needed)
    transient_removed = int(((n_obs >= 2) & (n_occ >= 1) & (support < needed)).sum())
    blind_filled = int(((n_obs == 1) & (n_occ == 1)).sum())
    fused = np.full((nh, nw), -1, np.int8)
    fused[n_obs >= 1] = 0
    fused[keep_wall] = 1

    occ_fused = fused == 1
    occupied_cells = int(occ_fused.sum())
    free_cells = int((fused == 0).sum())
    if occupied_cells == 0:
        raise sma.AlignError("fused grid has no occupied walls")
    free_area = free_cells * res * res
    if free_area < min_free_m2:
        raise sma.AlignError(f"fused free area {free_area:.3f} m^2 below gate {min_free_m2:.3f} m^2")
    speckle = _speckle_count(occ_fused)
    speckle_ratio = speckle / float(occupied_cells)
    if speckle_ratio > max_speckle_ratio:
        raise sma.AlignError(f"fused speckle ratio {speckle_ratio:.3f} exceeds gate {max_speckle_ratio:.3f}")
    stats = {
        "input_count": len(grids),
        "req_support": req_support,
        "min_pairwise_overlap": round(min_ov, 4),
        "pairwise_overlaps": overlaps,
        "blind_spot_cells_filled": blind_filled,
        "transient_obstacles_removed": transient_removed,
        "occupied_cells": occupied_cells,
        "free_cells": free_cells,
        "speckle_ratio": round(speckle_ratio, 4),
        "boundary_symmetry": round(sma.boundary_symmetry(fused), 4),
    }
    return sma.Grid(fused, res, (x0, y0)), stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("map_yamls", nargs="+", type=Path, help="two or more aligned yaw=0 Nav2 map yamls")
    ap.add_argument("--min-overlap", type=float, default=DEFAULT_MIN_OVERLAP)
    ap.add_argument("--min-support", type=int, default=DEFAULT_MIN_SUPPORT)
    ap.add_argument("--max-speckle-ratio", type=float, default=DEFAULT_MAX_SPECKLE_RATIO)
    ap.add_argument("--min-free-m2", type=float, default=DEFAULT_MIN_FREE_M2)
    ap.add_argument("--write", type=Path, metavar="OUT.yaml", help="write fused master map yaml (+ PGM)")
    ap.add_argument("--seal-bundle", type=Path, metavar="DEST_DIR", help="seal master map into closed bundle")
    ap.add_argument("--name", default="", help="map name inside --seal-bundle")
    ap.add_argument("--site-map-id", default=None, help="site_map_id recorded in manifest.json")
    ap.add_argument("--margin-m", type=float, default=0.20, help="occupied margin around sealed map (m)")
    ap.add_argument("--source", default="", help="provenance string written to manifest.json")
    args = ap.parse_args(argv)
    try:
        if len(args.map_yamls) < 2:
            raise sma.AlignError(f"need at least 2 aligned maps to fuse, got {len(args.map_yamls)}")
        if len({p.resolve() for p in args.map_yamls}) != len(args.map_yamls):
            raise sma.AlignError("duplicate input map paths supplied")
        if args.seal_bundle and not args.name:
            raise sma.AlignError("--seal-bundle requires --name")
        loaded = [load_aligned_map(p) for p in args.map_yamls]
        src_paths = set()
        for path, (_, meta, _) in zip(args.map_yamls, loaded):
            src_paths.add(path.resolve())
            src_paths.add((path.parent / meta["image"]).resolve())
        if args.write:
            if args.write.resolve() in src_paths or args.write.with_suffix(".pgm").resolve() in src_paths:
                raise sma.AlignError("--write would overwrite an input map")
            if args.write.exists() or args.write.with_suffix(".pgm").exists():
                raise sma.AlignError(f"{args.write} (or its PGM) exists; refusing to overwrite")
        if args.seal_bundle:
            maps_dir = args.seal_bundle / "maps"
            if (maps_dir / f"{args.name}.yaml").exists() or (maps_dir / f"{args.name}.pgm").exists() or (maps_dir / "manifest.json").exists():
                raise sma.AlignError(f"{maps_dir} already contains sealed map or manifest; refusing to overwrite")
        fused, stats = fuse_aligned_grids(
            [g for g, _, _ in loaded],
            min_overlap=args.min_overlap,
            min_support=args.min_support,
            max_speckle_ratio=args.max_speckle_ratio,
            min_free_m2=args.min_free_m2,
        )
        print(f"fused {stats['input_count']} maps: overlap min {stats['min_pairwise_overlap']:.3f}, "
              f"occupied {stats['occupied_cells']}, blind-filled {stats['blind_spot_cells_filled']}, "
              f"transient-removed {stats['transient_obstacles_removed']}, speckle {stats['speckle_ratio']:.3f}")
        provenance = {
            "tool": "master_map_fuse",
            "source_pgm_sha256s": [sha for _, _, sha in loaded],
            **stats,
        }
        written_yaml = (
            sma.write_zero_yaw_grid(fused, args.write, loaded[0][1], comment="master_map_fuse.py: site frame")
            if args.write else None
        )
        if args.seal_bundle:
            mb = sma.load_map_bundle_module()
            try:
                if written_yaml is not None:
                    sealed = mb.import_saved(
                        written_yaml, args.seal_bundle, args.name, margin_m=args.margin_m, source=args.source,
                        site_map_id=args.site_map_id, alignment=provenance, require_zero_yaw=True,
                    )
                else:
                    with tempfile.TemporaryDirectory() as tmp:
                        tmp_yaml = sma.write_zero_yaw_grid(
                            fused,
                            Path(tmp) / f"{args.name}.yaml",
                            loaded[0][1],
                            comment="master_map_fuse.py: site frame",
                        )
                        sealed = mb.import_saved(
                            tmp_yaml, args.seal_bundle, args.name, margin_m=args.margin_m, source=args.source,
                            site_map_id=args.site_map_id, alignment=provenance, require_zero_yaw=True,
                        )
            except ValueError as exc:
                raise sma.AlignError(str(exc)) from exc
            manifest = json.loads((sealed.parent / "manifest.json").read_text(encoding="utf-8"))
            print(f"sealed {sealed} (grid_id={manifest['grid_id']}, site_map_id={args.site_map_id})")
        elif written_yaml is not None:
            print(f"wrote {written_yaml} ({fused.cells.shape[1]}x{fused.cells.shape[0]} cells, yaw 0)")
    except sma.AlignError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return sma.REFUSED
    return 0


if __name__ == "__main__":
    sys.exit(main())
