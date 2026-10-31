"""The arm's planned path against the top view: anything in its way is refused before the arm moves.

Outside visitors test at this cell (2026-11-01): a hand, a box left on the table or the other arm stopped half way
can sit where a planned path goes low. The planned frames (`Planner.leg`: travel, pick, travel, place, travel home)
are taken through FK; the TCP points that go below `clear_z` are drawn into the top view as a corridor as wide as
the gripper plus a margin, and foreground blobs inside it are hits. The pick object and the place slot are the
work itself and are left out; so is the disc around the arm's own base, where the folded arm itself shows.

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
EXEMPT_MM = 45.0  # around the pick object and the place slot: the work, not an obstacle
MIN_PX = 40  # smaller blobs are noise or a shadow edge


def low_points(tcp, clear_z: float = CLEAR_Z_M, base_m: float = BASE_M) -> list[list]:
    """Runs of consecutive TCP points (x, y, z metres) below `clear_z` and outside the base disc."""
    runs, run = [], []
    for x, y, z in tcp:
        if z < clear_z and np.hypot(x, y) >= base_m:
            run.append((x, y))
        elif run:
            runs.append(run)
            run = []
    return runs + ([run] if run else [])


def corridor(runs, to_px, shape, roi, half_mm: float = HALF_WIDTH_MM) -> np.ndarray:
    """A 0/1 mask of the ROI under the runs, `half_mm` either side of the path (the scale taken at each run)."""
    import cv2

    out = np.zeros(shape[:2], np.uint8)
    for run in runs:
        pixels = [to_px(p) for p in run]
        if any(p is None for p in pixels):
            continue  # off the map: no view to check against; the caller reports it
        a, b = np.asarray(to_px(run[0]), float), np.asarray(to_px((run[0][0] + 0.01, run[0][1])), float)
        width = max(1, int(round(2 * half_mm * np.linalg.norm(b - a) / 10.0)))
        line = np.round(np.asarray(pixels, float) - [roi[0], roi[1]]).astype(np.int32)
        cv2.polylines(out, [line], False, 1, width)
        for p in line:  # a single point (a straight descent) still has its footprint
            cv2.circle(out, (int(p[0]), int(p[1])), width // 2, 1, -1)
    return out


def hits(mask, lane, exempt_px=(), exempt_r_px: float = 0.0, min_px: int = MIN_PX, roi=(0, 0)) -> list[dict]:
    """Foreground blobs inside the corridor, after the exempt discs (image pixels) are cleared."""
    import cv2

    inside = ((mask > 0) & (lane > 0)).astype(np.uint8)
    for c in exempt_px:
        cv2.circle(inside, (int(round(c[0] - roi[0])), int(round(c[1] - roi[1]))), int(round(exempt_r_px)), 0, -1)
    n, _, stats, centres = cv2.connectedComponentsWithStats(inside)
    return [{"centre_px": [round(float(centres[k][0]) + roi[0], 1), round(float(centres[k][1]) + roi[1], 1)],
             "area_px": int(stats[k][cv2.CC_STAT_AREA])}
            for k in range(1, n) if stats[k][cv2.CC_STAT_AREA] >= min_px]


def check(frames, mask, roi, to_px, pick_xy, place_xy, params=None) -> dict:
    """The verdict for one planned leg: {"clear": bool, "hits": [...], "off_map": n}."""
    import cell_pivot

    get = lambda k, d: prm.get(params, k, d)  # noqa: E731
    tcp = [cell_pivot.joints_tcp(f)[:3] for f in frames]
    runs = low_points(tcp, get("corridor.clear_z_m", CLEAR_Z_M), get("corridor.base_m", BASE_M))
    off_map = sum(to_px(p) is None for run in runs for p in run)
    lane = corridor(runs, to_px, mask.shape, roi, get("corridor.half_width_mm", HALF_WIDTH_MM))
    exempt = [to_px(p) for p in (pick_xy, place_xy) if p is not None and to_px(p) is not None]
    scale = (np.linalg.norm(np.subtract(to_px((pick_xy[0] + 0.01, pick_xy[1])), to_px(pick_xy))) / 10.0
             if exempt else 1.0)
    found = hits(mask, lane, exempt, get("corridor.exempt_mm", EXEMPT_MM) * scale,
                 get("corridor.min_px", MIN_PX), roi)
    return {"clear": not found and not off_map, "hits": found, "off_map": off_map, "corridor_px": int(lane.sum())}


def main(argv=None) -> int:
    import cell_objects
    import cell_pipeline as cp
    from cell_observe import predicted_pixel
    from grasp_planner import Planner

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--library", type=Path, required=True, help="a chunk library written by the planner")
    ap.add_argument("--site", required=True, help="the surface the corridor is checked on")
    ap.add_argument("--roi", nargs=4, type=int, required=True)
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
    to_px = lambda p: predicted_pixel(config, calibration, args.site, p)  # noqa: E731
    out = check(frames, mask, args.roi, to_px, (source["pick"]["x"], source["pick"]["y"]),
                (source["place"]["x"], source["place"]["y"]), params)
    print(json.dumps(out))
    return 0 if out["clear"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
