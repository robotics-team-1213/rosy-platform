"""Pure route regulation, start alignment, and battery checks for trip admission (D-601, D-763)."""

from __future__ import annotations

import math

from fleet.routing.cost import wrap
from fleet.routing.execute import arc_id
from fleet.site_map import _inside

#: D-763 10 (c): sample step along the route's lanes for the crosswalk test (m).
CROSSWALK_STEP_M = 0.02
#: CORE ``BatteryLevel`` values a start may see; critical, deep and anything unknown refuse.
BATTERY_START_LEVELS = ("ok", "warning")
#: Refusals that may be one missed read, and how many reads a start makes.
BATTERY_TRANSIENT = ("unreadable", "evidence_old", "evidence_stale")  # 5.0 s publish equals CORE's 5.0 s stale limit
BATTERY_TRIES = 3


def crosswalks_on(graph, segments: list, crosswalks) -> list:
    """D-763 10 (c): ids of the site-map crosswalks (D-573 1) a lane segment of this route enters."""
    hit, polygons = set(), [(c.id, [tuple(p) for p in c.polygon]) for c in crosswalks]
    for seg in segments if polygons else ():
        arc = graph.arcs[arc_id(seg)]
        if arc.drive_mode != "lane":
            continue
        s0, s1 = seg.get("s_from", 0.0), seg.get("s_to", arc.length_m)
        points = [arc.point_at(min(s0 + k * CROSSWALK_STEP_M, s1)) for k in range(int((s1 - s0) / CROSSWALK_STEP_M) + 2)]
        hit |= {cid for cid, polygon in polygons if any(_inside((x, y), polygon) for x, y, _ in points)}
    return sorted(hit)


def signals_on(traffic, segments: list) -> list:
    """D-763 10 (c): ids of the D-525 signals whose zone this route crosses (the span walk of
    ``TrafficService.signal_refusal``, kept here so the traffic unit does not grow)."""
    zones = {plan.zone: signal_id for signal_id, plan in traffic._signals.items()}
    layout = traffic._layout_for(traffic._store.active()) if zones and segments else None
    spans = layout.route(traffic._store.active()[2], [arc_id(seg) for seg in segments]) if layout else ()
    return sorted({zones[span.unit] for span in spans if span.unit in zones})


def start_check(graph, segments: list, x: float, y: float, yaw, tol_deg: float) -> dict:
    """D-601 D: the robot against its plan's first lane (``code`` None: it may start). Off the lane is
    the trip loop's own rule (more than half the lane width, ``_locate``); the heading is compared
    with the lane's direction at the robot's projection (one-way or the planned way)."""
    arc = graph.arcs[arc_id(segments[0])] if segments else None
    if arc is None or arc.drive_mode != "lane":
        return {"code": None}
    dist, _s, tangent = arc.project(x, y)
    err = None if yaw is None else round(math.degrees(wrap(yaw - tangent)), 1)
    code = ("TRIP_START_OFF_LANE" if dist > arc.width_m / 2
            else "TRIP_START_HEADING_MISMATCH" if err is None or abs(err) > tol_deg else None)
    return {"code": code, "edge_id": arc.edge_id, "heading_err_deg": err, "tol_deg": tol_deg,
            "off_lane_m": round(max(0.0, dist - arc.width_m / 2), 3)}


def cached_battery(state):
    """Start admission's battery source: the console's ``power_health`` cache (``state.power_health_display``,
    <= 5 s old) and its age; None when there is no display or no good read (fail closed)."""
    async def read(robot_id: str):
        display = getattr(state, "power_health_display", None)  # installed with the console routes
        health = await display.shown(robot_id, wait_s=2.0, await_pending=True) if display is not None else None
        return None if health is None else {"battery": health.get("battery"), "age_s": display.age(robot_id)}
    return read


def battery_refusal(reading):
    """Why a trip may not start on this battery reading, or None. ``reading``: ``{"battery", "age_s"}``, the
    CORE ``power_health`` battery block and the age of Fleet's cached copy. Fresh means what the console's
    ``powerHealthView`` means: evidence ``fresh`` and sample age + cache age within ``stale_after_s`` (cache
    age at most 5 s). ``ok`` and ``warning`` pass; ``critical``, ``deep`` and unknown levels refuse. This
    proves the evidence is fresh, not that the pack is charged (a charger's voltage reads 100 %)."""
    battery = (reading or {}).get("battery")
    age = (reading or {}).get("age_s")
    if not isinstance(battery, dict):
        return "unreadable"
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    sample, stale = battery.get("sample_age_s"), battery.get("stale_after_s")
    if battery.get("evidence") != "fresh":
        return f"evidence_{battery.get('evidence')}"
    if not (num(age) and 0 <= age <= 5 and num(sample) and sample >= 0 and num(stale) and stale > 0
            and sample + age <= stale):
        return "evidence_old"
    percent = battery.get("percent")
    if not (num(percent) and 0 <= percent <= 100):
        return "percent_unreadable"
    if battery.get("level") not in BATTERY_START_LEVELS:
        return f"level_{battery.get('level')}"
    return None
