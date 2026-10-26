#!/usr/bin/env python3
"""Daily landing numbers from tools/land.py's event log (``land_events.py``).

  python tools/land_stats.py [--days 7] [--json]

Per day (local time): landings and stops, queue wait p50/p90 (minutes from entering the queue to the turn),
turn p50/p90 (minutes from the turn to landed or stop), and per judged invocation the share that were new
failures, load-flaky, or gave no usable verdict (lost host, interrupted). The batch-landing decision waits
for the new-failure share to stay at or under 10 %. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import land_events  # noqa: E402


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def daily(rows: list[dict]) -> dict[str, dict]:
    days: dict[str, dict] = defaultdict(lambda: {"landed": 0, "stopped": 0, "waits": [], "turns": [],
                                                 "tests": defaultdict(int), "prepares": []})
    turn_at: dict[int, float] = {}
    for row in rows:
        day = days[time.strftime("%Y-%m-%d", time.localtime(row["t"]))]
        event, pid = row["event"], row.get("pid")
        if event == "turn":
            turn_at[pid] = row["t"]
            day["waits"].append(row.get("waited_s", 0) / 60)
        elif event in ("landed", "stop"):
            day["landed" if event == "landed" else "stopped"] += 1
            if pid in turn_at:
                day["turns"].append((row["t"] - turn_at.pop(pid)) / 60)
        elif event == "prepared":
            day["prepares"].append(row.get("seconds", 0) / 60)
        elif event == "tests":
            day["tests"][row.get("verdict", "?")] += 1
    out = {}
    for name, day in sorted(days.items()):
        judged = sum(day["tests"].values())
        share = (lambda key: round(day["tests"][key] / judged, 3) if judged else None)
        out[name] = {"landed": day["landed"], "stopped": day["stopped"],
                     "wait_p50_min": percentile(day["waits"], .5), "wait_p90_min": percentile(day["waits"], .9),
                     "turn_p50_min": percentile(day["turns"], .5), "turn_p90_min": percentile(day["turns"], .9),
                     "prepare_p50_min": percentile(day["prepares"], .5),
                     "prepare_p90_min": percentile(day["prepares"], .9),
                     "invocations": judged, "new_share": share("new"), "flaky_share": share("flaky"),
                     "unusable_share": share("unusable")}
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            capture_output=True, text=True, check=True).stdout.strip()
    since = time.time() - args.days * 86400
    stats = daily([r for r in land_events.read(Path(common) / land_events.EVENTS) if r["t"] >= since])
    if args.json:
        print(json.dumps(stats, indent=1))
        return 0
    fmt = lambda v: "-" if v is None else f"{v:.0f}" if isinstance(v, float) and v >= 10 else str(v)  # noqa: E731
    print("day         landed stopped  wait p50/p90 min  turn p50/p90 min  inv  new   flaky unusable")
    for name, d in stats.items():
        print(f"{name}  {d['landed']:6} {d['stopped']:7}  {fmt(d['wait_p50_min']):>6}/{fmt(d['wait_p90_min']):<8}"
              f"  {fmt(d['turn_p50_min']):>6}/{fmt(d['turn_p90_min']):<8}  {d['invocations']:3}  {fmt(d['new_share']):5}"
              f" {fmt(d['flaky_share']):5} {fmt(d['unusable_share'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
