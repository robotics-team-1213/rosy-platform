"""D-511 rev 6: driving context along the site's lap route, for the keep as a prior (never a command).

The lap is an ordered list of arc ids from the site YAML (``fleet.lane_compliance.lap_arcs``, map v5:
the figure eight). It is sampled every ``STEP_M`` once per map version. Features on it, in lap order:
``ring_entry`` (an arc into the roundabout from outside it), ``junction`` (an arc end with a choice of
next arcs), ``crosswalk`` (a site-map crosswalk polygon), ``turn_spot`` (a configured D-607 spot) and
``corner`` (the lap heading turns more than ``CORNER_DEG`` within ``CORNER_WINDOW_M``). The action is the
map direction at that feature: ``left`` / ``right`` / ``straight`` from the lap heading change (keep
right is already in the one-way map), ``stop_look`` at a crosswalk, ``turn_spot`` at a spot. Pure.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

STEP_M = 0.01
#: A corner: the lap heading turns more than this within CORNER_WINDOW_M (deg, m).
CORNER_DEG = 25.0
CORNER_WINDOW_M = 0.10
#: A junction or ring entry turning less than this is ``straight`` (deg).
STRAIGHT_DEG = 20.0
#: The expected heading is also given this far ahead (m).
AHEAD_M = 0.25
#: A turn spot counts on the lap when the lap passes within this of it (m).
SPOT_ON_LAP_M = 0.05


def _wrap(a: float) -> float:
    return (a + math.pi) % (2.0 * math.pi) - math.pi


def _turn(delta: float) -> str:
    return "straight" if abs(math.degrees(delta)) < STRAIGHT_DEG else ("left" if delta > 0 else "right")


@dataclass(frozen=True)
class Lap:
    samples: tuple       # (s, x, y, heading) every STEP_M
    length_m: float
    starts: dict         # arc id -> lap s of its start (first pass)
    features: tuple      # (s, kind, action, ref), sorted by s

    def heading_at(self, s: float) -> float:
        return self.samples[int((s % self.length_m) / STEP_M) % len(self.samples)][3]


def build_lap(graph, lap_arcs, crosswalks=(), turn_spots=()) -> Optional[Lap]:
    """None when the lap is empty or names an arc the map does not have."""
    from fleet.site_map import _inside
    if graph is None or not lap_arcs or any(a not in graph.arcs for a in lap_arcs):
        return None
    samples, starts, features, s0 = [], {}, [], 0.0
    for i, arc_id in enumerate(lap_arcs):
        arc = graph.arcs[arc_id]
        starts.setdefault(arc_id, s0)
        n = max(1, int(arc.length_m / STEP_M))
        for k in range(n):
            x, y, h = arc.point_at(k * STEP_M)
            samples.append((s0 + k * STEP_M, x, y, h))
        nxt = graph.arcs[lap_arcs[(i + 1) % len(lap_arcs)]]
        end_h, next_h = arc.point_at(arc.length_m)[2], nxt.point_at(0.0)[2]
        if nxt.edge_id.startswith("ring") and not arc.edge_id.startswith("ring"):   # ponytail: ring by name
            features.append((s0 + arc.length_m, "ring_entry", _turn(_wrap(next_h - end_h)), arc.end_place))
        elif len(graph.out_of.get(arc.end_place, ())) > 1:
            features.append((s0 + arc.length_m, "junction", _turn(_wrap(next_h - end_h)), arc.end_place))
        s0 += n * STEP_M
    length = s0
    inside_prev = {}
    for s, x, y, _ in samples:
        for cid, polygon in crosswalks:
            inside = _inside((x, y), list(polygon))
            if inside and not inside_prev.get(cid):
                features.append((s, "crosswalk", "stop_look", cid))
            inside_prev[cid] = inside
    for k, (sx, sy) in enumerate(turn_spots):
        s, d = min(((s, math.hypot(x - sx, y - sy)) for s, x, y, _ in samples), key=lambda t: t[1])
        if d <= SPOT_ON_LAP_M:
            features.append((s, "turn_spot", "turn_spot", f"spot{k}"))
    window, last_corner = int(CORNER_WINDOW_M / STEP_M), -1.0
    for i, (s, _, _, h) in enumerate(samples):
        delta = _wrap(samples[(i + window) % len(samples)][3] - h)
        if abs(math.degrees(delta)) > CORNER_DEG and (last_corner < 0 or s - last_corner > CORNER_WINDOW_M):
            features.append((s, "corner", "left" if delta > 0 else "right", None))
            last_corner = s
    # A corner that is the turn at a junction or ring entry is that feature, not a second one.
    turns = [f[0] for f in features if f[1] in ("junction", "ring_entry")]
    features = [f for f in features if f[1] != "corner"
                or not any(0.0 <= (t - f[0]) % length <= CORNER_WINDOW_M + STEP_M for t in turns)]
    return Lap(tuple(samples), length, starts, tuple(sorted(features, key=lambda f: f[0])))


def context(lap: Optional[Lap], arc_id: Optional[str], s_on_arc: Optional[float], offset_m: Optional[float],
            pose_age_s: Optional[float], anchor_age_s: Optional[float]) -> Optional[dict]:
    """The context at a lap position, or None when the robot is not on the lap."""
    if lap is None or arc_id not in lap.starts or s_on_arc is None:
        return None
    s = lap.starts[arc_id] + s_on_arc
    ahead = [(((f[0] - s) % lap.length_m), f) for f in lap.features]
    ds, (_, kind, action, ref) = min(ahead, key=lambda t: t[0]) if ahead else (None, (None, None, None, None))
    return {"route": "lap", "segment_id": arc_id, "s_m": round(s, 3), "lap_m": round(lap.length_m, 3),
            "heading_deg": round(math.degrees(lap.heading_at(s)), 1), "ahead_m": AHEAD_M,
            "heading_ahead_deg": round(math.degrees(lap.heading_at(s + AHEAD_M)), 1),
            "offset_m": offset_m,
            "next": None if kind is None else {"kind": kind, "ds_m": round(ds, 3), "action": action, "ref": ref},
            "pose_age_s": None if pose_age_s is None else round(pose_age_s, 3),
            "anchor_age_s": None if anchor_age_s is None else round(anchor_age_s, 3)}
