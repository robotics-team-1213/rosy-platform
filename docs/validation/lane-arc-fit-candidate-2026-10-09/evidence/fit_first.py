"""Read-only first-image geometry check: python fit_first.py <SIM run> [<SIM run> ...]."""

import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np


repo = Path(__file__).resolve().parents[4]
module = repo / "middleware/core/services/core_features/line_follow/arc/lane_arc_fit.py"
spec = importlib.util.spec_from_file_location("lane_arc_fit", module)
fit_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fit_module)

for argument in sys.argv[1:]:
    run = Path(argument)
    log = [json.loads(line) for line in (run / "log.jsonl").read_text().splitlines()]
    keep = [json.loads(line) for line in (run / "keep.jsonl").read_text().splitlines()]
    frames = np.load(run / "frames.npz")
    stamps, odom = frames["stamp"], frames["odom"]
    arc = next(row for row in log if str(row.get("reason") or "").startswith("lane_arc") and row.get("gt"))
    turn = next(row for row in log if row.get("reason") == "junction_turning" and row.get("gt"))
    yaw0 = turn["odom"][2] + math.radians(turn["junction"]["turn_deg"])
    centre_world = np.asarray(arc["odom"][:2]) + .2514 * np.asarray([-math.sin(yaw0), math.cos(yaw0)])
    for frame in keep:
        stamp = frame.get("stamp")
        if not isinstance(stamp, (int, float)) or not arc["sim_t"] <= stamp <= arc["sim_t"] + 1:
            continue
        idx = int(np.argmin(np.abs(stamps - stamp)))
        if abs(stamps[idx] - stamp) > .07 or abs(odom[idx, 5] - stamp) > .03:
            continue
        ox, oy, theta = odom[idx, :3]
        dx, dy = centre_world - np.asarray([ox, oy])
        centre = (math.cos(theta) * dx + math.sin(theta) * dy,
                  -math.sin(theta) * dx + math.cos(theta) * dy)
        fit = fit_module.fit_circle_candidate(frame.get("paint_points_m", []), centre, .3464,
                                               point_sigma_m=.010, radial_gate_m=.06)
        if fit is not None:
            print(json.dumps({"run": run.name, "stamp": stamp, "used": fit.used_points,
                              "span_deg": round(fit.span_deg, 1), "rms_mm": round(fit.radial_rms_m * 1000, 1),
                              "geometry_u95_deg": round(fit.heading_u95_deg, 1)}))
            break
