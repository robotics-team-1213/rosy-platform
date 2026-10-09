"""Ceiling robot sticker yaw offset from one straight forward drive (D-587 5).

Runs inside the site Vision container (it has OpenCV and rosy_vision), or on a PC with the
repo's operations/vision, contracts/foundation and operations/apps/games on PYTHONPATH. Needs no sighting,
so it works before any ``marker_yaw_offset_deg`` is installed (a robot without one sends no
sightings, D-587 4):

    docker exec -i [-e ROSY_FLEET_TOKEN] rosy-site-vision-1 python3 - \
        --robot rosy_41 --marker 41 --fleet https://proxy:8443 --insecure \
        [--dev-session --origin https://127.0.0.1:8443] \
        [--source ceiling_north] [--heading-edge 0,1] [--seconds 12] \
        < tools/calibration/ceiling_marker_yaw.py

Drive the robot straight forward for 0.3 m or more while this runs (Fleet manual drive or
the CORE dashboard). The tool reads the raw ceiling frames through a viewer lease, detects
the robot's ArUco marker, projects it with the source's approved D-457 record and the same
parallax step and geometry gate as the Vision sightings (``track.marker_sightings.marker_pose``),
takes the travel direction from the marker positions (main axis, oriented by time) and
compares the raw marker yaw with it. While driving forward the travel direction is the robot
front, so the difference is the sticker offset. The odom heading is not used: it is in the
odom frame, whose turn against the map is unknown.

Prints the ``marker_yaw_offset_deg`` value for site-cameras.yaml and the nearest multiple of
90. It never writes any file or config; the operator installs the line. Refuses (exit 2)
with fewer than 5 samples, under 0.25 m of travel, more than 0.02 m off a straight line or
more than 5 deg of yaw spread.

Token: ``ROSY_FLEET_TOKEN`` (viewer or above), or ``--dev-session`` on a development-mode
site. The token is never printed. ``estimate`` is stdlib only.
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
    """samples: (captured_at, x, y, yaw rad) of one marker over a forward straight drive.

    With the raw marker yaw and current_offset_deg 0 the result is the sticker offset."""
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


#: Browser origin Fleet checks on session requests; --origin sets it (the site's own console URL).
ORIGIN: list[str] = []


def _request(fleet: str, path: str, token: str | None, context, body: dict | None = None,
             *, raw: bool = False):
    headers = {"Origin": ORIGIN[0] if ORIGIN else fleet, "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(fleet + path, headers=headers, method="GET" if body is None else "POST",
                                     data=None if body is None else json.dumps(body).encode("utf-8"))
    with urllib.request.urlopen(request, context=context, timeout=5) as response:
        data = response.read()
        return (data, dict(response.headers)) if raw else json.loads(data)


def collect(fleet: str, *, source: str, marker: int, heading_edge: tuple[int, int], seconds: float,
            token: str | None, context) -> list[tuple]:
    """(captured_at, x, y, raw marker yaw) from the raw frames; needs rosy_vision (Vision container)."""
    from rosy_vision.detect import detect_markers
    from rosy_vision.track.calibration import from_record
    from rosy_vision.track.marker_sightings import marker_pose, solved_camera

    records = _request(fleet, "/api/fleet/calibrations", token, context).get("calibrations", [])
    record = next((r for r in records if r.get("source_id") == source), None)
    if record is None:
        raise EstimateError(f"no approved calibration record for {source}")
    samples: dict[float, tuple] = {}
    lease, lease_at = None, -math.inf
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if time.monotonic() - lease_at > 50:
            lease = _request(fleet, "/api/fleet/vision/lease", token, context, {"source_id": source})
            lease_at = time.monotonic()
        try:
            jpeg, headers = _request(fleet, lease["frame_path"], lease["lease"], context, raw=True)
        except OSError:
            time.sleep(0.25)
            continue
        captured_at = float(headers.get("X-Frame-Captured-At", "nan"))
        size = (int(headers.get("X-Frame-Width", 0)), int(headers.get("X-Frame-Height", 0)))
        quad = detect_markers(jpeg).get(marker)
        calibration = from_record(record, source_id=source, map_id=record["map_id"], frame_size=size,
                                  lens=record.get("lens")) if min(size) > 0 else None
        camera = solved_camera(calibration) if calibration is not None else None
        if quad is not None and camera is not None and math.isfinite(captured_at):
            pose = marker_pose(calibration, quad, heading_edge, camera)
            if pose is not None:
                samples[captured_at] = (captured_at, *pose)
        time.sleep(0.25)
    return list(samples.values())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--robot", required=True, help="robot id for the printed config line")
    parser.add_argument("--marker", type=int, required=True, help="its ArUco id (D-562: robot number)")
    parser.add_argument("--source", default="ceiling_north")
    parser.add_argument("--heading-edge", default="0,1", help="the source's heading_edge corners")
    parser.add_argument("--fleet", default="https://proxy:8443")
    parser.add_argument("--seconds", type=float, default=12.0)
    parser.add_argument("--dev-session", action="store_true", help="ask a development-mode site for a session")
    parser.add_argument("--insecure", action="store_true", help="skip TLS verification (site self-signed cert)")
    parser.add_argument("--origin", help="Origin header for session requests (default: --fleet)")
    args = parser.parse_args(argv)
    fleet = args.fleet.rstrip("/")
    ORIGIN[:] = [args.origin] if args.origin else []
    edge = tuple(int(v) for v in args.heading_edge.split(","))
    context = ssl._create_unverified_context() if args.insecure else None
    token = os.environ.get("ROSY_FLEET_TOKEN")
    if args.dev_session:
        token = _request(fleet, "/api/fleet/auth/development-session", None, context, {})["token"]
    print(f"drive {args.robot} straight forward now; reading marker {args.marker} for {args.seconds:.0f} s",
          flush=True)
    try:
        samples = collect(fleet, source=args.source, marker=args.marker, heading_edge=edge,
                          seconds=args.seconds, token=token, context=context)
        result = estimate(samples, 0.0)
    except EstimateError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result))
    print(f"site-cameras.yaml source: marker_yaw_offset_deg: {{{args.robot}: {result['offset_deg']}}}"
          f"  (nearest 90: {result['nearest_90_deg']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
