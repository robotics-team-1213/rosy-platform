"""The arm's planned path against the top view: anything in its way is refused before the arm moves.

Outside visitors test at this cell (2026-11-01): a hand, a box left on the table or the other arm stopped half way
can sit where a planned path goes. The planned frames (`Planner.leg`: travel, pick, travel, place, travel home) go
through FK and are drawn into the top view as a corridor as wide as the gripper plus a margin:
- where the TCP goes below `clear_z` (the descents at the pick and the place), any foreground blob is in the way;
- above it (travel, 138 mm on 2026-11-01) catalogue objects pass underneath, but an unknown blob (a hand, the
  other arm) may be tall and is in the way too.
The pick object's own blob is the work. The place slot must be empty unless a stack is declared (`--stack`). The
disc around the arm's own base, where the folded arm itself shows, is left out.

    python cell_corridor.py --config cell.json --library auto-....json --site belt --roi x0 y0 x1 y1   # read only
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_params as prm  # noqa: E402

HALF_WIDTH_MM = 30.0  # gripper half width (jaws open ~50 mm) plus a margin
CLEAR_Z_M = 0.10  # above this the TCP passes over the container (30 mm) and the two-layer stack (65 mm)
BASE_M = 0.10  # the folded arm itself shows within this radius of its base
MIN_PX = 40  # smaller blobs are noise or a shadow edge


def runs(tcp, clear_z: float = CLEAR_Z_M, base_m: float = BASE_M) -> tuple[list, list]:
    """(low, high): runs of consecutive TCP points (x, y) below / above `clear_z`, outside the base disc."""
    out, run, level = {True: [], False: []}, [], None
    for x, y, z in tcp:
        low = z < clear_z
        if np.hypot(x, y) < base_m or low != level:
            if run:
                out[level].append(run)
            run, level = [], low
        if np.hypot(x, y) >= base_m:
            run.append((x, y))
    if run:
        out[level].append(run)
    return out[True], out[False]


def corridor(paths, to_px, shape, roi, half_mm: float = HALF_WIDTH_MM) -> np.ndarray:
    """A 0/1 mask of the ROI under the paths, `half_mm` either side (the scale taken at each path's start)."""
    import cv2

    out = np.zeros(shape[:2], np.uint8)
    for run in paths:
        pixels = [to_px(p) for p in run]
        if any(p is None for p in pixels):
            continue  # off the map: no view to check against; check() counts it
        a, b = np.asarray(pixels[0], float), np.asarray(to_px((run[0][0] + 0.01, run[0][1])), float)
        width = max(1, int(round(2 * half_mm * np.linalg.norm(b - a) / 10.0)))
        line = np.round(np.asarray(pixels, float) - [roi[0], roi[1]]).astype(np.int32)
        cv2.polylines(out, [line], False, 1, width)
        for p in line:  # a straight descent is one point and still has its footprint
            cv2.circle(out, (int(p[0]), int(p[1])), width // 2, 1, -1)
    return out


def without_blobs(mask, roi, pixels):
    """The mask without the connected blobs under these image pixels (the pick object; a declared stack)."""
    import cv2

    n, labels = cv2.connectedComponents((mask > 0).astype(np.uint8))
    out = mask.copy()
    for px in pixels:
        col, row = int(round(px[0])) - roi[0], int(round(px[1])) - roi[1]
        if 0 <= row < mask.shape[0] and 0 <= col < mask.shape[1] and labels[row, col]:
            out[labels == labels[row, col]] = 0
    return out


def hits(inside, roi=(0, 0), min_px: int = MIN_PX) -> list[dict]:
    """Blobs of a 0/1 mask at least `min_px` large, in image pixels."""
    import cv2

    n, _, stats, centres = cv2.connectedComponentsWithStats(inside.astype(np.uint8))
    return [{"centre_px": [round(float(centres[k][0]) + roi[0], 1), round(float(centres[k][1]) + roi[1], 1)],
             "area_px": int(stats[k][cv2.CC_STAT_AREA])}
            for k in range(1, n) if stats[k][cv2.CC_STAT_AREA] >= min_px]


def check(tcp, mask, roi, to_px, pick_xy=None, known=None, stack_xy=None, params=None) -> dict:
    """The verdict for one planned leg (TCP points in metres): {"clear", "low", "high", "off_map"}.
    `known`: 0/1 mask of catalogue objects, which may pass under high travel."""
    get = lambda k, d: prm.get(params, k, d)  # noqa: E731
    low, high = runs(tcp, get("corridor.clear_z_m", CLEAR_Z_M), get("corridor.base_m", BASE_M))
    off_map = sum(to_px(p) is None for run in low + high for p in run)
    work = [to_px(p) for p in (pick_xy, stack_xy) if p is not None and to_px(p) is not None]
    mask = without_blobs(mask, roi, work) > 0
    half, min_px = get("corridor.half_width_mm", HALF_WIDTH_MM), get("corridor.min_px", MIN_PX)
    unknown = mask & ~(known > 0) if known is not None else mask
    found_low = hits(mask & (corridor(low, to_px, mask.shape, roi, half) > 0), roi, min_px)
    found_high = hits(unknown & (corridor(high, to_px, mask.shape, roi, half) > 0), roi, min_px)
    return {"clear": not (found_low or found_high or off_map), "low": found_low, "high": found_high, "off_map": off_map}


def known_mask(objects, shape, roi) -> np.ndarray:
    """0/1 mask of the catalogue-matched objects' own outlines (`cell_objects.detect`)."""
    import cv2

    out = np.zeros(shape[:2], np.uint8)
    for o in objects:
        if o.get("matched") and o.get("hull_px"):
            cv2.fillPoly(out, [np.asarray(o["hull_px"], np.int32) - [roi[0], roi[1]]], 1)
    return out


def main(argv=None) -> int:
    import cell_objects
    import cell_pipeline as cp
    import cell_pivot
    from cell_observe import predicted_pixel
    from grasp_planner import Planner

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--library", type=Path, required=True, help="a chunk library written by the planner")
    ap.add_argument("--site", required=True, help="the surface whose map and mask the corridor is checked on")
    ap.add_argument("--roi", nargs=4, type=int, required=True)
    ap.add_argument("--catalog", type=Path, help="known objects may pass under high travel; without it none do")
    ap.add_argument("--stack", action="store_true", help="the place goes onto an object already in the slot")
    args = ap.parse_args(argv)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    params = config["params"] = prm.load(config.get("params_path"))["values"]
    plan = json.loads(Path(config["plan_path"]).expanduser().read_text())
    calibration = json.loads(Path(config["calibration_path"]).expanduser().read_text())
    library = json.loads(args.library.read_text())
    source, site = library["source"], config["sites"][args.site]
    frames = Planner(dict(plan, pick=source["pick"], place=source["place"])).leg(library)
    img = cp.FifoCell(Path(config["io"]).expanduser(), config["cameras"]).frame("top")
    mask = cell_objects.foreground(img, args.roi, params=params, surface_px=site.get("surface_px"),
                                   surface_lab=site.get("surface_lab"))
    known = None
    if args.catalog:
        objects = cell_objects.detect(img, args.roi, cell_pivot.map_record(calibration, args.site), config["cameras"]["top"],
                                      cell_objects.load_catalog(args.catalog), site["surface_z"], params,
                                      site.get("surface_px"), site.get("surface_lab"))
        known = known_mask(objects, mask.shape, args.roi)
    # shortcut: one site's map and mask for the whole leg (belt and pallet heights differ by ~35 mm); per-run sites
    # once the cycle plans both ends
    to_px = lambda p: predicted_pixel(config, calibration, args.site, p)  # noqa: E731
    pick, place = source["pick"], source["place"]
    out = check([cell_pivot.joints_tcp(f)[:3] for f in frames], mask, args.roi, to_px, (pick["x"], pick["y"]), known,
                (place["x"], place["y"]) if args.stack else None, params)
    print(json.dumps(out))
    return 0 if out["clear"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
