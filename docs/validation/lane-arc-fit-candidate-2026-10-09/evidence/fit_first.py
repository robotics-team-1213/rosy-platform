"""Read-only first-0.10 m geometry replay: python fit_first.py <SIM run> [<SIM run> ...]."""

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

def summarize_hits(hits):
    longest = streak = transitions = 0
    for index, hit in enumerate(hits):
        transitions += int(index > 0 and hit != hits[index - 1])
        streak = 0 if hit else streak + 1
        longest = max(longest, streak)
    return {"frames": len(hits), "candidate_frames": sum(hits), "transitions": transitions,
            "longest_consecutive_miss": longest,
            "first_candidate_index": next((i for i, hit in enumerate(hits) if hit), None)}


def replay(run):
    log = [json.loads(line) for line in (run / "log.jsonl").read_text().splitlines()]
    keep = [json.loads(line) for line in (run / "keep.jsonl").read_text().splitlines()]
    frames = np.load(run / "frames.npz")
    stamps, odom = frames["stamp"], frames["odom"]
    arc = next(row for row in log if str(row.get("reason") or "").startswith("lane_arc") and row.get("odom"))
    turn = next(row for row in log if row.get("reason") == "junction_turning" and row.get("odom"))
    yaw0 = turn["odom"][2] + math.radians(turn["junction"]["turn_deg"])
    centre_world = np.asarray(arc["odom"][:2]) + .2514 * np.asarray([-math.sin(yaw0), math.cos(yaw0)])
    start = int(np.searchsorted(stamps, arc["sim_t"]))
    if start >= len(stamps):
        raise ValueError("no odom after arc start")
    step = np.diff(odom[start:, :2], axis=0)
    heading = odom[start:-1, 2]
    first_dx, first_dy = odom[start, :2] - np.asarray(arc["odom"][:2])
    initial = first_dx * math.cos(arc["odom"][2]) + first_dy * math.sin(arc["odom"][2])
    progress = initial + np.r_[0., np.cumsum(step[:, 0] * np.cos(heading) + step[:, 1] * np.sin(heading))]
    hits, distances, line_preferred, seen = [], [], 0, set()
    first_fit = None
    for frame in keep:
        stamp = frame.get("stamp")
        if not isinstance(stamp, (int, float)) or stamp < arc["sim_t"]:
            continue
        idx = int(np.argmin(np.abs(stamps - stamp)))
        if idx < start or idx in seen or abs(stamps[idx] - stamp) > .07 or abs(odom[idx, 5] - stamp) > .03:
            continue
        distance = float(progress[idx - start])
        if distance > .10:
            break
        if distance < 0:
            continue
        seen.add(idx)
        ox, oy, theta = odom[idx, :3]
        dx, dy = centre_world - np.asarray([ox, oy])
        centre = (math.cos(theta) * dx + math.sin(theta) * dy,
                  -math.sin(theta) * dx + math.cos(theta) * dy)
        fit = fit_module.fit_circle_candidate(frame.get("paint_points_m", []), centre, .3464,
                                               point_sigma_m=.010, radial_gate_m=.06)
        if fit is not None and first_fit is None:
            first_fit = {"stamp": stamp, "used": fit.used_points, "span_deg": round(fit.span_deg, 1),
                         "rms_mm": round(fit.radial_rms_m * 1000, 1),
                         "line_rms_mm": round(fit.line_rms_m * 1000, 1),
                         "geometry_u95_deg": round(fit.heading_u95_deg, 1)}
        candidate = (fit is not None and fit.used_points >= 8 and fit.span_deg >= 15
                     and fit.radial_rms_m <= .010 and fit.line_rms_m > fit.radial_rms_m)
        line_preferred += int(fit is not None and fit.line_rms_m <= fit.radial_rms_m)
        hits.append(candidate)
        distances.append(distance)
    summary = summarize_hits(hits)
    first = summary["first_candidate_index"]
    summary.update(run=run.name, first_fit=first_fit, line_preferred_frames=line_preferred,
                   first_candidate_m=None if first is None else round(distances[first], 4),
                   observed_m=None if not distances else round(max(distances), 4))
    return summary


if __name__ == "__main__":
    for argument in sys.argv[1:]:
        print(json.dumps(replay(Path(argument))))
