#!/usr/bin/env python3
"""D-767 7: score Fleet's route preview (P0) against an independent truth.

Predictions are the JSON lines Fleet appends with ``ROSY_ROUTE_PREVIEW_LOG=<file>``
(``operations/fleet/fleet/server/trips/trip_preview.py``). Truth is JSON lines of two kinds, on the
same clock as the predictions' ``pose_stamp`` (``--clock t``: Fleet's own ``t``):

  {"robot_id": "r1", "t": 12.3, "path_m": 4.567}                          true distance driven so far
  {"robot_id": "r1", "t": 15.0, "pass": {"kind": "turn", "id": "J1"}}     the true front passed it
                                                       (optional "leg_id": only that leg's predictions match it)

Gazebo: ``path_m`` and ``pass`` from the simulator's true pose and the world file's places, lines,
crosswalks and arcs. Device: ``path_m`` from odom, ``pass`` from the robot's own camera sightings
(``junction_ahead_m`` added on), crosswalks at CORE's zone near edge. The ceiling camera is not a truth.
``id`` is the event's ``place_id`` (a crosswalk: its ``zone_id``). ``authority_end`` is not scored.

``--offset-s`` is added to every prediction time first (truth clock - prediction clock); a prediction without
a time (no odom stamp) is skipped. For each predicted event: truth ``at_m`` = path at the first pass after the
prediction - path then. The gate is the p95 of the per-event ratio |error| / (a + b * at_m) <= 1, the ADR's
p95 <= a + b * at_m bound (gazebo a 0.03, device a 0.10; b 0.05 = ODOM_DRIFT_PER_M), and
missed (a pass within the preview's horizon, inside its last listed event, not listed) <= 1% and
phantom (listed, never passed although the robot drove that far on the same leg) <= 1%.

  python tools/sim/route_preview_accuracy.py PREDICTIONS.jsonl TRUTH.jsonl [--profile device] [--clock t] [--offset-s S]
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import sys
from collections import defaultdict

PROFILES = {"gazebo": 0.03, "device": 0.10}
DRIFT_PER_M, MAX_RATE = 0.05, 0.01


def key(event: dict) -> tuple:
    return event["kind"], event.get("place_id") or (event.get("params") or {}).get("zone_id")


def _path(series: list, t: float):
    """True distance driven at ``t`` (linear between samples), None outside them."""
    times = [s[0] for s in series]
    i = bisect.bisect_left(times, t)
    if i < len(series) and series[i][0] == t:
        return series[i][1]
    if i == 0 or i == len(series):
        return None
    (t0, p0), (t1, p1) = series[i - 1], series[i]
    return p0 + (p1 - p0) * (t - t0) / (t1 - t0)


def score(predictions: list, truth: list, profile: str = "gazebo", clock: str = "pose_stamp",
          offset_s: float = 0.0) -> dict:
    a = PROFILES[profile]
    paths, passes, legs = defaultdict(list), defaultdict(list), defaultdict(float)
    for row in truth:
        if "path_m" in row:
            paths[row["robot_id"]].append((row["t"], row["path_m"]))
        elif "pass" in row:
            passes[row["robot_id"]].append((row["t"], (row["pass"]["kind"], row["pass"]["id"]), row.get("leg_id")))
    for series in (*paths.values(), *passes.values()):
        series.sort(key=lambda row: row[0])
    predictions = [{**p, "at": p[clock] + offset_s} for p in predictions if p.get(clock) is not None]
    for p in predictions:
        legs[p["robot_id"], p["leg_id"]] = max(legs[p["robot_id"], p["leg_id"]], p["at"])
    ratios, errors, matched, missed, phantom, listed = [], [], 0, 0, 0, 0
    for p in predictions:
        robot, t0 = p["robot_id"], p["at"]
        mine = [(t, k) for t, k, leg in passes[robot] if leg in (None, p["leg_id"])]
        here = _path(paths[robot], t0)
        if here is None:
            continue
        events = [e for e in p["events"] if e["kind"] != "authority_end"]
        listed += len(events)
        for e in events:
            hit = next((t for t, k in mine if t > t0 and k == key(e)), None)
            there = None if hit is None else _path(paths[robot], hit)
            if there is None:
                leg_end = _path(paths[robot], legs[robot, p["leg_id"]])
                phantom += leg_end is not None and leg_end - here >= e["at_m"]  # it drove that far: not there
                continue
            err = e["at_m"] - (there - here)
            errors.append(abs(err))
            ratios.append(abs(err) / (a + DRIFT_PER_M * max(0.0, e["at_m"])))
        reach = max((e["at_m"] for e in p["events"]), default=0.0) if len(p["events"]) >= 8 else p["horizon_m"]
        first, seen = {}, {key(e) for e in p["events"]}
        for t, k in mine:
            if t > t0:
                first.setdefault(k, t)  # the next pass of each event only
        for k, t in first.items():
            ahead = _path(paths[robot], t)
            if ahead is not None and ahead - here <= reach:
                missed, matched = missed + (k not in seen), matched + (k in seen)

    def p95(values):
        return None if not values else sorted(values)[max(0, math.ceil(0.95 * len(values)) - 1)]
    result = {"profile": profile, "scored": len(ratios), "p95_error_m": p95(errors), "p95_ratio": p95(ratios),
              "missed": missed, "missed_rate": missed / max(1, missed + matched),
              "phantom": phantom, "phantom_rate": phantom / max(1, listed)}
    result["pass"] = (bool(ratios) and result["p95_ratio"] <= 1.0 and result["missed_rate"] <= MAX_RATE
                      and result["phantom_rate"] <= MAX_RATE)
    return result


def _lines(path: str) -> list:
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("predictions")
    parser.add_argument("truth")
    parser.add_argument("--profile", choices=sorted(PROFILES), default="gazebo")
    parser.add_argument("--clock", choices=("pose_stamp", "t"), default="pose_stamp")
    parser.add_argument("--offset-s", type=float, default=0.0, help="truth clock minus prediction clock")
    args = parser.parse_args(argv)
    result = score(_lines(args.predictions), _lines(args.truth), args.profile, args.clock, args.offset_s)
    print(json.dumps(result, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
