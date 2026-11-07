#!/usr/bin/env python3
"""Which way the jaws of this arm really open, measured over a clear spot in free air (2026-11-06).

arm_b's ledger of closing axes had no success on either value and the better-looking one opened the jaws sideways into
a packed ship. A grasp by the ends opens past 90 mm, so it now needs this fact in the config
(`closing_axis_offset_deg`); the ledger still decides grasps that open little.

  cell_jaw_axis.py --config cell.json --site pallet --point 0.068,-0.112 --yaw -80 -40 --commissioning --person-at-switch
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import time

import numpy as np

import cell_params as prm  # noqa: E402


def wrap90(deg: float) -> float:
    return (deg + 90.0) % 180.0 - 90.0


def changed_axis_px(closed, opened, around_px, radius_px: float, params=None) -> float | None:
    """Image angle (deg, mod 180) of the changed pixels near the jaws, or None when too few changed to have an axis."""
    import cell_pivot

    ys, xs = np.nonzero(cell_pivot._changed_mask(closed, opened, prm.get(params, "pivot.diff_px")))
    near = np.hypot(xs - around_px[0], ys - around_px[1]) <= radius_px
    xs, ys = xs[near], ys[near]
    if len(xs) < prm.get(params, "pivot.min_blob"):
        return None
    values, vectors = np.linalg.eigh(np.cov(np.stack([xs, ys]).astype(float)))
    return math.degrees(math.atan2(vectors[1, 1], vectors[0, 1])) if values[1] > 2 * values[0] else None


def to_arm_axis(axis_px_deg: float, around_px, to_arm) -> float:
    """The image direction at the jaws as an arm-frame angle: the map decides, the camera may be mirrored."""
    u = math.radians(axis_px_deg)
    a = to_arm((around_px[0] - 20 * math.cos(u), around_px[1] - 20 * math.sin(u)))
    b = to_arm((around_px[0] + 20 * math.cos(u), around_px[1] + 20 * math.sin(u)))
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))


def agreed_offset(rows: list, max_spread_deg: float = 15.0) -> float | None:
    """The offset (closing axis - tool yaw, mod 180) when at least two yaws measured it and they agree, else None."""
    offsets = [r["offset_deg"] for r in rows if r.get("offset_deg") is not None]
    if len(offsets) < 2:
        return None
    mean = math.degrees(math.atan2(np.mean(np.sin(np.radians(2 * np.array(offsets)))),
                                   np.mean(np.cos(np.radians(2 * np.array(offsets)))))) / 2
    return round(mean, 1) if all(abs(wrap90(o - mean)) <= max_spread_deg for o in offsets) else None


def offer_measured(config: dict, choices, name: str) -> None:
    """The measured axis goes on the ledger too: an outcome on a value never offered raises, after the arm has moved."""
    if config.get("closing_axis_offset_deg") is not None:
        choices.offer(name, config["closing_axis_offset_deg"], "measured in free air (cell_jaw_axis)")


def offset_for(config: dict, entry: dict, ledger_best):
    """(closing offset, None) or (None, why): the measured fact first; only a grasp that opens past the box's length
    refuses to go on the ledger's word."""
    measured = config.get("closing_axis_offset_deg")
    if measured is not None:
        return measured, None
    if entry.get("grasp", {}).get("jaw_axis_deg_from_long", 90) % 180 != 90:
        return None, "held by its ends the jaws open wide: measure closing_axis_offset_deg first (cell_jaw_axis)"
    return ledger_best, None


def measure(cell, config: dict, calibration: dict, site: str, point, yaws, work: Path, sleep=time.sleep, log=print) -> dict:
    import cell_pipeline as cp
    import cell_pivot

    record, params = cell_pivot.map_record(calibration, site), config.get("params")
    if record is None:
        return {"result": f"no map for {site}"}
    z = cell_pivot.pivot_z_view(config, site)
    view = {"x": point[0], "y": point[1], "z": round(z - config["plan"]["approach_m"], 4)}
    closed_to, opened_to = prm.get(params, "pivot.grip_closed"), config["plan"].get("grip_open", prm.get(params, "pivot.grip_open"))
    rows = []
    try:
        for i, yaw in enumerate(yaws):
            try:
                library = cp.write_library(config, dict(view, yaw_deg=yaw), dict(view, yaw_deg=yaw), work / f"jaw-axis-{i}.json")
            except SystemExit as exc:
                rows.append({"yaw": yaw, "skipped": str(exc)[:120]})
                continue
            failed = next((c for c in (f"load {library}", "goto above_pick") if not cell.act(c).get("ok")), None)
            if failed:
                rows.append({"yaw": yaw, "stopped": failed})
                break
            if not cp.grip_to(cell, closed_to):
                rows.append({"yaw": yaw, "stopped": "close"})
                break
            closed = cell_pivot.settled_frame(cell, sleep, params=params)
            if not cp.grip_to(cell, opened_to):
                rows.append({"yaw": yaw, "stopped": "open"})
                break
            opened = cell_pivot.settled_frame(cell, sleep, params=params)
            x, y, jaw_z, fk_yaw = cell_pivot.joints_tcp(cell.act("state").get("state"))
            around = cell_pivot.mark_pixel(record, config, site, (x, y), jaw_z)
            axis = changed_axis_px(closed, opened, around, prm.get(params, "pivot.max_blob"), params)
            row = {"yaw": yaw, "fk_yaw": round(fk_yaw, 1), "z": round(jaw_z, 4), "axis_px_deg": axis, "offset_deg": None}
            if axis is not None:
                to_arm = lambda p: cell_pivot.mark_to_arm(record, config, site, p, jaw_z)  # noqa: E731
                row["offset_deg"] = round(wrap90(to_arm_axis(axis, around, to_arm) - fk_yaw), 1)
            rows.append(row)
            log(row)
    finally:
        cp.fold(cell, sleep)
    return {"result": "measured" if agreed_offset(rows) is not None else "not agreed", "closing_axis_offset_deg": agreed_offset(rows),
            "rows": rows}


def main(argv=None) -> int:
    import cell_calibration as cal
    import cell_pipeline as cp
    import cell_pivot
    from cell_auto_setup import load_config

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--site", required=True)
    ap.add_argument("--point", required=True, help="x,y metres of a clear spot")
    ap.add_argument("--yaw", required=True, nargs="+", type=float)
    ap.add_argument("--commissioning", action="store_true")
    ap.add_argument("--person-at-switch", action="store_true")
    args = ap.parse_args(argv)
    if not (args.commissioning and args.person_at_switch):
        raise SystemExit("this moves the arm: --commissioning --person-at-switch (D-911)")
    config = load_config(args.config)
    calibration = cell_pivot.with_site_maps(config, cal.load(Path(config["calibration_path"]).expanduser()))
    cell = cp.FifoCell(Path(config["io"]).expanduser(), config["cameras"])
    result = measure(cell, config, calibration, args.site, tuple(float(v) for v in args.point.split(",")), args.yaw,
                     Path(config["work_dir"]).expanduser())
    print(json.dumps(result, indent=1, default=str))
    return 0 if result["result"] == "measured" else 1


if __name__ == "__main__":
    sys.exit(main())
