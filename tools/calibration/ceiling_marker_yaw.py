"""Ceiling robot sticker yaw offset from one straight forward drive (D-587 5).

    python3 ceiling_marker_yaw.py --robot rosy_41 [--fleet https://127.0.0.1:8443]
        [--seconds 10] [--current-offset-deg 0] [--dev-session] [--insecure]

Drive the robot straight forward for 0.3 m or more while this runs (Fleet manual drive or
the CORE dashboard). It reads ``GET /api/fleet/sightings`` for that robot, takes the travel
direction from the positions (main axis, oriented by time) and compares the sighting yaw
with it. While driving forward the travel direction is the robot front, so the difference
is what the sticker offset is missing. The odom heading is not used: it is in the odom
frame, whose turn against the map is unknown.

Prints the new ``marker_yaw_offset_deg`` value for site-cameras.yaml (current + difference)
and the nearest multiple of 90. It never writes any file or config; the operator installs
the line. Refuses (exit 2) with fewer than 5 samples, under 0.25 m of travel, more than
0.02 m off a straight line or more than 5 deg of yaw spread.

Token: ``ROSY_FLEET_TOKEN`` (viewer or above), or ``--dev-session`` on a development-mode
site. The token is never printed. Stdlib only, so it runs with the site PC's python3.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import ssl
import sys
import time
import urllib.request
from typing import Sequence

MIN_SAMPLES = 5
MIN_TRAVEL_M = 0.25
MAX_LINE_RESIDUAL_M = 0.02
MAX_YAW_SPREAD_DEG = 5.0


class EstimateError(ValueError):
    pass


def _wrap(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def estimate(samples: Sequence[tuple[float, float, float, float]], current_offset_deg: float = 0.0) -> dict:
    """samples: (captured_at, x, y, yaw rad) sightings of one forward straight drive."""
    rows = sorted(samples)
    if len(rows) < MIN_SAMPLES:
        raise EstimateError(f"only {len(rows)} sightings; need {MIN_SAMPLES}")
    n = len(rows)
    mx = sum(r[1] for r in rows) / n
    my = sum(r[2] for r in rows) / n
    sxx = sum((r[1] - mx) ** 2 for r in rows)
    syy = sum((r[2] - my) ** 2 for r in rows)
    sxy = sum((r[1] - mx) * (r[2] - my) for r in rows)
    axis = 0.5 * math.atan2(2 * sxy, sxx - syy)
    ux, uy = math.cos(axis), math.sin(axis)
    along = [(r[1] - mx) * ux + (r[2] - my) * uy for r in rows]
    across = [-(r[1] - mx) * uy + (r[2] - my) * ux for r in rows]
    travel_m = max(along) - min(along)
    if travel_m < MIN_TRAVEL_M:
        raise EstimateError(f"travel {travel_m:.3f} m; drive straight for at least {MIN_TRAVEL_M} m")
    residual = max(abs(v) for v in across)
    if residual > MAX_LINE_RESIDUAL_M:
        raise EstimateError(f"path is {residual:.3f} m off a straight line; drive straight")
    mt = sum(r[0] for r in rows) / n
    if sum((r[0] - mt) * a for r, a in zip(rows, along)) < 0:
        axis += math.pi
    travel = _wrap(axis)
    diffs = [_wrap(r[3] - travel) for r in rows]
    delta = math.atan2(sum(math.sin(d) for d in diffs), sum(math.cos(d) for d in diffs))
    spread = max(abs(math.degrees(_wrap(d - delta))) for d in diffs)
    if spread > MAX_YAW_SPREAD_DEG:
        raise EstimateError(f"yaw spread {spread:.1f} deg; the robot turned or the marker is noisy")
    offset = math.degrees(_wrap(math.radians(current_offset_deg) + delta))
    nearest = (round(offset / 90.0) * 90) % 360
    return {"samples": n, "travel_m": round(travel_m, 3), "line_residual_m": round(residual, 4),
            "travel_deg": round(math.degrees(travel), 1), "difference_deg": round(math.degrees(delta), 1),
            "yaw_spread_deg": round(spread, 2), "offset_deg": round(offset, 1),
            "nearest_90_deg": nearest if nearest <= 180 else nearest - 360}


def _request(fleet: str, path: str, token: str | None, context, body: dict | None = None) -> dict:
    headers = {"Origin": fleet, "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(fleet + path, headers=headers, method="GET" if body is None else "POST",
                                     data=None if body is None else json.dumps(body).encode("utf-8"))
    with urllib.request.urlopen(request, context=context, timeout=5) as response:
        return json.loads(response.read())


def collect(fleet: str, robot: str, seconds: float, token: str | None, context) -> list[tuple]:
    seen: dict[float, tuple] = {}
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        for row in _request(fleet, "/api/fleet/sightings", token, context).get("sightings", []):
            if row.get("robot_id") == robot and not row.get("stale"):
                seen[row["captured_at"]] = (row["captured_at"], row["x"], row["y"], row["yaw"])
        time.sleep(0.2)
    return list(seen.values())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--robot", required=True)
    parser.add_argument("--fleet", default="https://127.0.0.1:8443")
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--current-offset-deg", type=float, default=0.0)
    parser.add_argument("--dev-session", action="store_true", help="ask a development-mode site for a session")
    parser.add_argument("--insecure", action="store_true", help="skip TLS verification (site self-signed cert)")
    args = parser.parse_args(argv)
    fleet = args.fleet.rstrip("/")
    context = ssl._create_unverified_context() if args.insecure else None
    token = os.environ.get("ROSY_FLEET_TOKEN")
    if args.dev_session:
        token = _request(fleet, "/api/fleet/auth/development-session", None, context, {})["token"]
    print(f"drive {args.robot} straight forward now; reading sightings for {args.seconds:.0f} s", flush=True)
    samples = collect(fleet, args.robot, args.seconds, token, context)
    try:
        result = estimate(samples, args.current_offset_deg)
    except EstimateError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result))
    print(f"site-cameras.yaml source: marker_yaw_offset_deg: {{{args.robot}: {result['offset_deg']}}}"
          f"  (nearest 90: {result['nearest_90_deg']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
