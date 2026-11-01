#!/usr/bin/env python3
"""Calibrate one arm's wrist view for cell_wrist: hover over a container at a known pose (one the arm just placed)
at a 3x3 grid of offsets, fit [u, v] = A [x, y] + b, save J = A^-1 and the reference for that arm and yaw band.
Arm motion only, no person: every hover is the planner's `above_pick` for the offset pick, then the arm folds home.

  cell_wrist_cal.py --config cell-auto.json --x 0.0376 --y 0.2204 --site pinky --yaw -67.8 [--band 45] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_params as prm  # noqa: E402
import cell_pipeline as cp  # noqa: E402
import cell_wrist as cw  # noqa: E402


def offsets(step_mm: float) -> list:
    return [(dx, dy) for dx in (-step_mm, 0.0, step_mm) for dy in (-step_mm, 0.0, step_mm)]


def calibrate(cell, camera: str, hsv, pick: dict, write_library, params=None) -> dict:
    """Hover at each offset (the gripper moved by +d sees the box at -d); fit and return a band body (no yaw range)."""
    xy, uv, views = [], [], {}
    for dx, dy in offsets(prm.get(params, "wrist.cal_offset_mm")):
        lib = write_library({**pick, "x": round(pick["x"] + dx / 1000, 4), "y": round(pick["y"] + dy / 1000, 4)})
        for command in (f"load {lib}", "goto above_pick"):
            status = cell.act(command)
            if not status.get("ok"):
                cell.act("park")
                raise SystemExit(f"{command.split()[0]} at offset ({dx}, {dy}): {status.get('error')}")
        view = cw.median_view(cell, camera, hsv, params)
        views[(dx, dy)] = view
        if view.get("found") and not view["cut"] and view["blobs"] == 1:
            xy.append((-dx, -dy))  # the box relative to the gripper
            uv.append((view["cx"], view["cy"]))
    cell.act("park")
    if len(xy) < 6:
        raise SystemExit(f"only {len(xy)} of 9 hovers saw the whole container")
    fitted = cw.fit(xy, uv, params)
    zero = views[(0.0, 0.0)]
    if not zero.get("found"):
        raise SystemExit("the centred hover did not see the container")
    return {"J": fitted["J"], "rms_px": fitted["rms_px"], "cond": fitted["cond"], "n": len(xy),
            "ref": {"u": fitted["b"][0], "v": fitted["b"][1], "area": zero["area"], "axis_deg": zero["axis_deg"]}}


def save(path: Path, arm: str, yaw: float, half_band: float, body: dict, camera: str) -> dict:
    data = json.loads(path.read_text()) if path.exists() else {"schema": cw.SCHEMA, "arms": {}}
    entry = data["arms"].setdefault(arm, {"camera": camera, "bands": []})
    band = {"yaw_lo": yaw - half_band, "yaw_hi": yaw + half_band, **body, "measured": time.strftime("%Y-%m-%dT%H:%M:%S")}
    entry["bands"] = [b for b in entry["bands"] if b["yaw_hi"] <= band["yaw_lo"] or b["yaw_lo"] >= band["yaw_hi"]] + [band]
    path.write_text(json.dumps(data, indent=1))
    return band


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--site", required=True)
    ap.add_argument("--x", type=float, required=True)
    ap.add_argument("--y", type=float, required=True)
    ap.add_argument("--yaw", type=float, required=True)
    ap.add_argument("--band", type=float, default=45.0, help="half width of the yaw band this calibration covers")
    args = ap.parse_args(argv)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    config["params"] = prm.load(config.get("params_path"))["values"]
    config["plan"] = json.loads(Path(config["plan_path"]).expanduser().read_text())
    spec, arm = config["wrist"], config.get("arm_id", "arm_s")
    camera = (config.get("arms", {}).get(arm, {}) or {}).get("wrist_camera", spec.get("camera", "wrist"))
    site = config["sites"][args.site]
    pick = {"x": args.x, "y": args.y, "z": site["surface_z"] + prm.get(config["params"], "auto.grasp_depth_m"), "yaw_deg": args.yaw}
    work = Path(config["work_dir"]).expanduser()
    write = lambda p: cp.write_library(config, p, p, work / "wrist-cal.json")  # noqa: E731
    cell = cp.FifoCell(Path(config["io"]).expanduser(), config["cameras"])
    body = calibrate(cell, camera, (spec["hsv_min"], spec["hsv_max"]), pick, write, config["params"])
    band = save(Path(spec["cal_path"]).expanduser(), arm, args.yaw, args.band, body, camera)
    print(json.dumps(band))


if __name__ == "__main__":
    main()
