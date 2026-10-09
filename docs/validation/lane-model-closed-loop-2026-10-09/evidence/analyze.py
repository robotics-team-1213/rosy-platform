"""Summarize identical closed-loop trip runs without treating model use as safety proof."""

import argparse
import collections
import json
import math
from pathlib import Path

CENTER = (-0.3357, 0.0011)
RING_RADIUS_M = 0.2514
SIM_BOX_RADIUS_M = 0.08826
SECTORS = (("ring_s", -137.7, -52.5), ("ring_e", -52.5, 52.3), ("ring_n", 52.3, 137.1))


def analyze(root: Path) -> dict:
    result = {}
    for model in ("threshold", "pidnet", "unet", "v11", "v13_drivable"):
        run = root / f"loop_{model}" / "lap_d567_baseline"
        summary = json.loads((run / "summary.json").read_text())
        rows = [json.loads(line) for line in (run / "log.jsonl").read_text().splitlines()]
        keep = [json.loads(line) for line in (run / "rec/keep.jsonl").read_text().splitlines()]
        poses = [r["gt"] for r in rows if r.get("gt") and all(math.isfinite(v) for v in r["gt"])]
        assert rows and keep and poses
        paint = collections.Counter(r.get("paint_source_used", "missing") for r in keep)
        revisions = collections.Counter(r.get("paint_model_revision") for r in keep if r.get("paint_model_revision"))
        reasons = collections.Counter(r.get("reason") or "none" for r in rows)
        arcs = {name: [] for name, _, _ in SECTORS}
        for row in rows:
            if not str(row.get("reason") or "").startswith("lane_arc") or not row.get("gt"):
                continue
            x, y, _ = row["gt"]
            radius = math.hypot(x - CENTER[0], y - CENTER[1])
            angle = math.degrees(math.atan2(y - CENTER[1], x - CENTER[0]))
            for name, low, high in SECTORS:
                if low <= angle < high:
                    clearance = min(radius - 0.155, 0.345 - radius) - SIM_BOX_RADIUS_M
                    arcs[name].append((abs(radius - RING_RADIUS_M), clearance))
                    break
        result[model] = {
            "result": summary["result"],
            "reason": summary.get("reason"),
            "log_rows": len(rows),
            "keep_frames": len(keep),
            "paint_source_used": dict(paint),
            "paint_model_revisions": dict(revisions),
            "reason_counts": dict(reasons),
            "ring_arcs": {name: {"ticks": len(values),
                                 "max_abs_radial_error_m": round(max(v[0] for v in values), 4),
                                 "min_proxy_clearance_m": round(min(v[1] for v in values), 4),
                                 "negative_proxy_ticks": sum(v[1] < 0 for v in values)}
                          for name, values in arcs.items() if values},
            "gt_first": poses[0],
            "gt_last": poses[-1],
            "gt_path_m": round(sum(math.dist(a[:2], b[:2]) for a, b in zip(poses, poses[1:])), 4),
            "final_cmd": summary["core_after_halt"]["cmd"],
        }
        assert model == "threshold" or paint["learned"] > 0
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("root", type=Path)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    report = analyze(args.root)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
