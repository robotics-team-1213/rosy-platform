"""First logged radial-error crossing on a recorded ring arc; evaluation only.

Usage: python thresholds.py --centre -0.3357 0.0011 --radius 0.2514 RUN_DIR...
The distance is the sum of recorded odom chords, not a safe blind-distance grant.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path


THRESHOLDS_M = (0.025, 0.05)


def summarize(run_dir, centre, radius):
    log_path = run_dir / "log.jsonl"
    rows = [json.loads(line) for line in log_path.open(encoding="utf-8")]
    start = next(i for i, row in enumerate(rows)
                 if row.get("reason") in ("lane_arc", "lane_arc_correcting")
                 and row.get("gt") and row.get("odom"))
    travelled = peak = 0.0
    previous_odom = None
    ticks = 0
    crossings = {threshold: None for threshold in THRESHOLDS_M}
    for row in rows[start:]:
        if row.get("reason") not in ("lane_arc", "lane_arc_correcting"):
            break
        if not row.get("gt") or not row.get("odom"):
            raise ValueError(f"missing pose in arc tick: {run_dir}")
        odom = row["odom"]
        if previous_odom is not None:
            travelled += math.dist(odom[:2], previous_odom[:2])
        previous_odom = odom
        error = abs(math.dist(row["gt"][:2], centre) - radius)
        peak = max(peak, error)
        ticks += 1
        for threshold in crossings:
            if crossings[threshold] is None and error >= threshold:
                crossings[threshold] = round(travelled, 4)
    return {
        "group": run_dir.parent.name,
        "run": run_dir.name,
        "log_sha256": hashlib.sha256(log_path.read_bytes()).hexdigest(),
        "ticks": ticks,
        "travelled_m": round(travelled, 4),
        "peak_abs_radial_error_m": round(peak, 4),
        "first_25mm_m": crossings[0.025],
        "first_50mm_m": crossings[0.05],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--centre", type=float, nargs=2, required=True)
    parser.add_argument("--radius", type=float, required=True)
    parser.add_argument("run_dir", type=Path, nargs="+")
    args = parser.parse_args()
    if args.radius <= 0 or not math.isfinite(args.radius) or any(not math.isfinite(v) for v in args.centre):
        parser.error("finite centre and positive finite radius required")
    for run_dir in args.run_dir:
        print(json.dumps(summarize(run_dir, args.centre, args.radius), sort_keys=True))


if __name__ == "__main__":
    main()
