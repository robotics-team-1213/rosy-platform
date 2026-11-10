"""Does the site map match where the robots actually drove? Report, plus one rigid correction.

Pure: standard library only, no I/O, no clock, no robot. The server passes the D-594 path
history in the site ``map`` frame (Fleet recorded those points itself) and the map it wants
judged; this module says which lanes were driven, how far off they sit, which zones were
entered, and — when the whole map sits off the driven track — one rigid ``yaw + translation``
that brings the map onto the drive. Applying it is the operator's call, to the draft only
(``docs/plans/2026-11-10-map-reality-check.md``).

A lane is *matched* when driven points lie on it within ``TOLERANCE_M``; the same 0.15 m is
the D-455 ``max_jump_m`` sighting gate, so "on the lane" means the same thing here as it does
for a camera sighting. A point further than ``PAIR_GATE_M`` from any lane sample is not paired
for the fit: a robot that drove a lane the map does not have must not drag the whole map.
"""

from __future__ import annotations

import math
from typing import Iterable, Optional, Sequence

from fleet.routing.graph import polyline_length

SCHEMA = "rosy.site_map_reality/1"

TOLERANCE_M = 0.15          # a driven point this close to a lane centre line is on that lane
SAMPLE_M = 0.25             # lane samples taken along each edge centre line
TRACK_STEP_M = 0.10         # driven points closer than this are one point for this report
PAIR_GATE_M = 0.50          # a lane sample further than this from a drive is not a pair
OFF_LANE_M = 0.50           # a driven point this far from every lane is "off the map"
MIN_PAIRS = 20              # fewer correspondences than this fit nothing
MIN_PAIR_SHARE = 0.30       # and the pairs must cover at least this share of lane samples
ITERATIONS = 6
MAX_YAW_RAD = math.radians(30.0)
MAX_SHIFT_M = 5.0
MIN_SHIFT_M = 0.05
MIN_YAW_RAD = math.radians(0.3)
MIN_GAIN = 0.5              # an accepted correction halves the median distance to the drive
CELL_M = 0.25

Point = tuple[float, float]
Fit = tuple[float, float, float]   # yaw, tx, ty: ``map' = R(yaw) * map + t``


class _Grid:
    """Uniform cell index over points: the nearest one within ``max_r`` (no points -> ``inf``)."""

    def __init__(self, points: Iterable[Point]) -> None:
        self.cells: dict[tuple[int, int], list[Point]] = {}
        for x, y in points:
            self.cells.setdefault((math.floor(x / CELL_M), math.floor(y / CELL_M)), []).append((x, y))

    def nearest(self, x: float, y: float, max_r: float) -> tuple[float, Optional[Point]]:
        i0, j0 = math.floor(x / CELL_M), math.floor(y / CELL_M)
        best, found = max_r * max_r, None
        ring = 0
        while ring * CELL_M <= max_r:
            for i in range(i0 - ring, i0 + ring + 1):
                for j in range(j0 - ring, j0 + ring + 1):
                    if max(abs(i - i0), abs(j - j0)) != ring:
                        continue
                    for px, py in self.cells.get((i, j), ()):
                        gap = (px - x) ** 2 + (py - y) ** 2
                        if gap <= best:
                            best, found = gap, (px, py)
            ring += 1
        return (math.sqrt(best), found) if found is not None else (max_r, None)


def _resample(points: Sequence[Point], step: float) -> list[Point]:
    """The polyline's points plus interior points every ``step`` along it."""
    out = [tuple(points[0])]
    for a, b in zip(points, points[1:]):
        span = math.dist(a, b)
        if span <= 0.0:
            continue
        count = max(1, math.ceil(span / step))
        out.extend((a[0] + (b[0] - a[0]) * k / count, a[1] + (b[1] - a[1]) * k / count)
                   for k in range(1, count + 1))
    return [(float(x), float(y)) for x, y in out]


def _dedupe(points: Iterable[Point], step: float) -> list[Point]:
    out: list[Point] = []
    for point in points:
        if not out or math.dist(point, out[-1]) >= step:
            out.append((float(point[0]), float(point[1])))
    return out


def _inside(point: Point, polygon: Sequence[Point]) -> bool:
    x, y = point
    hit = False
    for (ax, ay), (bx, by) in zip(polygon, list(polygon[1:]) + [polygon[0]]):
        if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
            hit = not hit
    return hit


def _apply(fit: Fit, point: Point) -> Point:
    yaw, tx, ty = fit
    c, s = math.cos(yaw), math.sin(yaw)
    return (c * point[0] - s * point[1] + tx, s * point[0] + c * point[1] + ty)


def _compose(outer: Fit, inner: Fit) -> Fit:
    """``outer(inner(p))``."""
    yaw, tx, ty = outer
    c, s = math.cos(yaw), math.sin(yaw)
    return (yaw + inner[0], c * inner[1] - s * inner[2] + tx, s * inner[1] + c * inner[2] + ty)


def _rigid(pairs: Sequence[tuple[Point, Point]]) -> Fit:
    """Least-squares ``yaw + t`` mapping each ``a`` onto its ``b`` (2D Kabsch, no scale)."""
    n = len(pairs)
    ax = sum(a[0] for a, _ in pairs) / n
    ay = sum(a[1] for a, _ in pairs) / n
    bx = sum(b[0] for _, b in pairs) / n
    by = sum(b[1] for _, b in pairs) / n
    dot = cross = 0.0
    for (px, py), (qx, qy) in pairs:
        x, y = px - ax, py - ay
        u, v = qx - bx, qy - by
        dot += x * u + y * v
        cross += x * v - y * u
    yaw = math.atan2(cross, dot)
    c, s = math.cos(yaw), math.sin(yaw)
    return (yaw, bx - (c * ax - s * ay), by - (s * ax + c * ay))


def _median(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def _fit(samples: Sequence[Point], drive: _Grid) -> tuple[Optional[Fit], int]:
    """Iterative closest point: the rigid transform that puts the lanes onto the drive."""
    fit: Fit = (0.0, 0.0, 0.0)
    matched = 0
    for _ in range(ITERATIONS):
        pairs = []
        for point in samples:
            moved = _apply(fit, point)
            gap, near = drive.nearest(*moved, max_r=PAIR_GATE_M)
            if near is not None:
                pairs.append((moved, near))
        matched = len(pairs)
        if matched < MIN_PAIRS:
            return None, matched
        delta = _rigid(pairs)
        fit = _compose(delta, fit)
        if abs(delta[0]) < 1e-4 and math.hypot(delta[1], delta[2]) < 1e-4:
            break
    return fit, matched


def _round(values: Iterable[Optional[float]]) -> list[Optional[float]]:
    return [None if value is None else round(value, 4) for value in values]


def compare(site_map, tracks: Sequence[Sequence[Point]], *, tolerance_m: float = TOLERANCE_M) -> dict:
    """Judge ``site_map`` against driven ``tracks`` (each an ordered polyline in the map frame)."""
    driven = [tuple(float(v) for v in point) for track in tracks for point in track]
    points = _dedupe(driven, TRACK_STEP_M)
    if len(points) < 2:
        return {"schema": SCHEMA, "evidence": {"tracks": len(tracks), "points": len(points)},
                "verdict": "no_evidence", "lanes": [], "zones": [], "off_lane": None, "fit": None,
                "notes": ["no robot drive was recorded for this window"]}

    drive = _Grid(points)
    lane_samples: list[Point] = []
    lanes = []
    for edge in site_map.edges:
        samples = _resample(edge.polyline, SAMPLE_M)
        lane_samples.extend(samples)
        gaps = [drive.nearest(x, y, OFF_LANE_M)[0] for x, y in samples]
        covered = [gap for gap in gaps if gap <= OFF_LANE_M]
        coverage = sum(1 for gap in gaps if gap <= tolerance_m) / len(gaps)
        offset = _median(covered)
        state = ("uncovered" if coverage < 0.5 else
                 "offset" if offset is not None and offset > tolerance_m else "matched")
        lanes.append({"id": edge.id, "name": edge.name or edge.id,
                      "length_m": round(polyline_length(edge.polyline), 3),
                      "coverage": round(coverage, 3),
                      "median_offset_m": None if offset is None else round(offset, 4),
                      "max_offset_m": None if not covered else round(max(covered), 4),
                      "state": state})

    zones = []
    for facility in site_map.facilities:
        geometry = [tuple(point) for point in facility.geometry]
        if facility.kind == "exclusion" and len(geometry) >= 3:  # fewer points is not an area
            inside = sum(1 for point in points if _inside(point, geometry))
            zones.append({"id": facility.id, "name": facility.name, "kind": facility.kind,
                          "points": inside, "state": "entered" if inside else "clear"})
    for crosswalk in site_map.crosswalks:
        inside = sum(1 for point in points if _inside(point, [tuple(p) for p in crosswalk.polygon]))
        zones.append({"id": crosswalk.id, "name": crosswalk.id, "kind": "crosswalk",
                      "points": inside, "state": "used" if inside else "unused"})

    lane_grid = _Grid(lane_samples)
    off = sum(1 for point in points if lane_grid.nearest(*point, max_r=OFF_LANE_M)[1] is None)

    before = _median([drive.nearest(x, y, OFF_LANE_M)[0] for x, y in lane_samples])
    fit, matched = _fit(lane_samples, drive)
    correction, reason = None, ""
    after = before
    if fit is None:
        reason = f"fewer than {MIN_PAIRS} lane samples lie within {PAIR_GATE_M} m of the drive"
    else:
        after = _median([drive.nearest(*_apply(fit, point), max_r=OFF_LANE_M)[0] for point in lane_samples])
        yaw, tx, ty = fit
        shift = math.hypot(tx, ty)
        if matched < MIN_PAIR_SHARE * len(lane_samples):
            reason = (f"only {matched} of {len(lane_samples)} lane samples pair with the drive; "
                      "the map and the drive are not the same lanes")
        elif before is None or before <= tolerance_m:
            reason = "the driven points already lie on the mapped lanes"
        elif after is None or after > before * MIN_GAIN:
            reason = "no rigid transform brings the lanes closer to the drive"
        elif shift < MIN_SHIFT_M and abs(yaw) < MIN_YAW_RAD:
            reason = "the fitted change is smaller than this report's resolution"
        elif abs(yaw) > MAX_YAW_RAD or shift > MAX_SHIFT_M:
            reason = f"the fitted change ({math.degrees(yaw):.1f} deg, {shift:.2f} m) is too large for one site frame"
        else:
            correction = (yaw, tx, ty)

    worst = [lane["id"] for lane in lanes if lane["state"] == "uncovered"]
    entered = [zone["id"] for zone in zones if zone["state"] == "entered"]
    verdict = ("mismatch" if entered else
               "offset" if correction is not None else   # the lanes are there, the frame is off
               "unmapped" if len(worst) > max(1, len(lanes) // 2) else
               "match" if lanes and all(lane["state"] == "matched" for lane in lanes) else "partial")
    notes = []
    if entered:
        notes.append("a robot drove through an exclusion area: the area or the drive is wrong")
    if worst:
        notes.append("lanes no robot drove: " + ", ".join(worst[:8]))
    if off:
        notes.append(f"{off} driven points ({off / len(points):.0%}) lie off every mapped lane")

    return {"schema": SCHEMA,
            "evidence": {"tracks": len(tracks), "points": len(points)},
            "tolerance_m": tolerance_m,
            "verdict": verdict,
            "lanes": lanes,
            "zones": zones,
            "off_lane": {"points": off, "share": round(off / len(points), 3)},
            "fit": {"accepted": correction is not None,
                    "yaw_deg": None if correction is None else round(math.degrees(correction[0]), 3),
                    "tx_m": None if correction is None else round(correction[1], 4),
                    "ty_m": None if correction is None else round(correction[2], 4),
                    "before_median_m": _round([before])[0],
                    "after_median_m": _round([after])[0],
                    "pairs": matched,
                    "reason": reason},
            "notes": notes}


def transform_map(body: dict, fit: dict) -> dict:
    """``body`` (``SiteMap.body()``) moved by an accepted ``fit``; the caller re-validates.

    Rigid, so distances and headings hold: only the frame moves. The survey reference moves
    with it (its origin and heading are map-frame values) and keeps its revision, which the
    evidence rows are bound to.
    """
    yaw = math.radians(float(fit["yaw_deg"]))
    move: Fit = (yaw, float(fit["tx_m"]), float(fit["ty_m"]))

    def points(rows):
        return [[round(v, 4) for v in _apply(move, (row[0], row[1]))] for row in rows]

    def heading(value):
        return None if value is None else round(math.remainder(value + yaw, math.tau), 6)

    out = dict(body)
    out["places"] = []
    for place in body["places"]:
        x, y = _apply(move, (place["x"], place["y"]))
        out["places"].append(dict(place, x=round(x, 4), y=round(y, 4),
                                  **{key: heading(place[key]) for key in ("yaw", "exit_yaw") if key in place}))
    out["edges"] = [dict(edge, polyline=points(edge["polyline"])) for edge in body["edges"]]
    if body.get("crosswalks"):
        out["crosswalks"] = [dict(row, polygon=points(row["polygon"]),
                                  **({"approach": [points(band) for band in row["approach"]]}
                                     if row.get("approach") else {}))
                             for row in body["crosswalks"]]
    for key in ("walls", "facilities"):
        if body.get(key):
            out[key] = [dict(row, **({"face": points(row["face"])} if key == "walls"
                                     else {"geometry": points(row["geometry"])}))
                        for row in body[key]]
    if body.get("survey"):
        survey = dict(body["survey"], origin=points([body["survey"]["origin"]])[0],
                      heading_rad=heading(body["survey"]["heading_rad"]))
        out["survey"] = survey
    return out
