"""D-494/D-507 junction and bend geometry of the trip loop, moved out of ``trip_ports`` unchanged (D-798).

Pure functions over a ``LiveTrip`` and the site graph; the read-to-send clock stays ``trip_ports._monotonic``.
"""

from __future__ import annotations

import logging
import math
from dataclasses import fields
from typing import Optional

from rosy.world.state.projections.map_pose import MapPose
from fleet.routing.cost import LEFT, RIGHT, STRAIGHT, wrap
from fleet.routing.execute import ends_at_place
from fleet.server import trip_ports as _ports
from fleet.server.trip_ports import MAX_EXPECT_IN_M, MAX_EXPECT_TOL_M, MAX_PIVOT_PAST_LINE_M, TripConfig
from fleet.site_map import ENDPOINT_TOL_M

_LOG = logging.getLogger("fleet.server.trip_ports")  # the logger these lines used before the D-798 split

#: Along-track odom drift per metre of odom travel (wheel slip on carpet): the map pose's
#: dead-reckoned distance and, since CORE measures the window in odom path length (2026-10-08),
#: the distance driven from the send to the place.
ODOM_DRIFT_PER_M = 0.05
#: ponytail: a fixed allowance for the send's HTTP time and CORE taking the instruction after the
#: send starts; measure it on the site network and make it site config if it is off.
SEND_ALLOWANCE_S = 0.2
#: D-507 B9 diagnostic: a lane heading change this large is a bend (``bend_candidate`` only).
MAX_WINDOW_BEND_DEG = 15.0
#: The lane heading is checked this often ahead of the robot.
WINDOW_BEND_STEP_M = 0.02
#: CORE's lane_turn_deg range (lap SIM 2).
MAX_LANE_TURN_DEG = 360.0
# D-507 B9 diagnostic only: inspect the current edge, never authorize motion from this.
BEND_PREVIEW_M = 0.40
BEND_MAX_ANGLE_DEG = 80.0  # keeper's non-square bend limit
#: The cross line search steps this far, then halves the last step to 1 mm.
LINE_STEP_M = 0.01


def bend_candidate(arc, s: float, pose: dict, *, end_s: float | None = None) -> Optional[dict]:
    """A nearby turn in this lane edge, using only a fresh, aligned map pose. No motion grant."""
    if arc.drive_mode != "lane" or not isinstance(pose, dict):
        return None
    keys = ("x", "y", "yaw", "age_s", "dead_reckon_m")
    if any(isinstance(pose.get(key), bool) or not isinstance(pose.get(key), (int, float))
           or not math.isfinite(pose[key]) for key in keys):
        return None
    if not 0 <= pose["age_s"] <= 0.30 or not 0 <= pose["dead_reckon_m"] <= ENDPOINT_TOL_M:
        return None
    offset, projected_s, heading = arc.project(pose["x"], pose["y"])
    if (offset > 0.04 or abs(projected_s - s) > ENDPOINT_TOL_M
            or abs(math.degrees(wrap(pose["yaw"] - heading))) > MAX_WINDOW_BEND_DEG):
        return None
    limit = min(arc.length_m if end_s is None else end_s, s + BEND_PREVIEW_M)
    if not math.isfinite(limit) or limit <= s:
        return None
    first, change = None, 0.0
    steps = math.ceil((limit - s) / WINDOW_BEND_STEP_M)
    for index in range(1, steps + 1):
        ahead = (limit - s) * index / steps
        _, _, future = arc.point_at(s + ahead)
        change = math.degrees(wrap(future - heading))
        if abs(change) > BEND_MAX_ANGLE_DEG:
            return None
        if first is None and abs(change) >= MAX_WINDOW_BEND_DEG:
            first = ahead
    if first is None:
        return None
    return {"arc_id": arc.id, "bend_in_m": round(first, 3),
            "heading_change_deg": round(change, 1), "map_offset_m": round(offset, 3)}


def record_bend_candidate(live: "LiveTrip", pose: MapPose, active, index: int, s: float) -> None:
    """Put a map-bound, read-only bend hint in the current trip view when its evidence holds."""
    if (live.view["hold"] is not None or active is None or active[0] != live.view["map_version"]
            or pose.map_id not in (None, active[1].map_id)):
        return
    cue = bend_candidate(live.arc(index), s, vars(pose), end_s=live.segments[index]["s_to"])
    if cue is not None:
        live.view["detail"]["bend_candidate"] = {
            **cue, "map_id": active[1].map_id, "map_version": active[0]}


def junction_fields(live: "LiveTrip", index: int, action: str, remaining: float, active,
                    config: TripConfig) -> Optional[dict]:
    """D-507 2 fields for a ``junction_pivot`` robot: ``map_id``, ``pivot_past_line_m`` (not for
    ``stop``; the place minus the first painted line ``line_past`` finds along the lane heading at
    the place, or the outgoing half-width and no window when it finds none) and the window pair:
    ``expect_in_m`` = ``remaining``, the distance along the lane from the robot's snapped position
    to the place, which CORE compares with its odom path length (2026-10-08 user decision, curves
    included), when it is in (0, 2]; none on another map version
    (logged, ``detail.junction_fields_dropped``). ``arm_distance_m`` should be at least the
    keeper's 0.45 m + pivot + tol so the instruction comes first; SIM checks the default 0.6.
    The trip loop never sends a ``left``/``right`` without the window (``junction_no_window``).
    """
    view = live.view
    caps, pose = view.get("caps") or {}, view.get("pose") or {}
    if caps.get("junction_pivot") is not True:
        return None
    if active is None or active[0] != view["map_version"]:
        if view["detail"].get("junction_fields_dropped") != "map_version":
            _LOG.warning("trip %s: active map is not the plan's version %s; junction fields not sent",
                         view.get("trip_id"), view["map_version"])
        view["detail"]["junction_fields_dropped"] = "map_version"
        return None
    fields = {"map_id": active[1].map_id}
    expect_in = round(remaining, 3)
    window = 0.0 < expect_in <= MAX_EXPECT_IN_M
    if action in (STRAIGHT, LEFT, RIGHT):
        # 2026-10-08: the first painted line past the place along the lane's heading there (on a
        # curved approach the robot's heading is not the line's).
        x, y, heading = live.arc(index).point_at(live.segments[index]["s_to"])
        past = line_past(live.graph, x, y, heading)
        if past is None:  # no line near the place: the old near-edge half-width, and no window
            width = live.arc(index + 1).width_m
            fields["pivot_past_line_m"] = round(min(width / 2, MAX_PIVOT_PAST_LINE_M), 3)
            return fields
        if window:
            fields["pivot_past_line_m"] = -past
        # No negative pivot without a window: map-backed CORE holds any unplaced sighting.
    if not window:
        return fields  # no window: map-backed CORE holds a junction sighting here
    tol = _pose_tol(live, config, expect_in,
                    _curve_offset_m(live.arc(index), live.segments[index]["s_to"], remaining, pose))
    fields.update(expect_in_m=expect_in, expect_tol_m=tol, **({"pose_stamp": live.at_stamp} if caps.get("lane_instruction_stamp") and live.at_stamp else {}))
    if action == STRAIGHT:  # lap SIM 2: CORE follows a keeper corner the way this lane turns
        turn = math.degrees(_lane_turn(live.arc(index), live.segments[index]["s_to"], remaining))
        fields["lane_turn_deg"] = round(max(-MAX_LANE_TURN_DEG, min(turn, MAX_LANE_TURN_DEG)), 1)
    return fields


def _pose_tol(live: "LiveTrip", config: TripConfig, travel: float = 0.0, extra: float = 0.0) -> float:
    """How well the map pose places the robot along its lane, at most ``MAX_EXPECT_TOL_M``:
    ``travel`` is the odom path CORE measures to the place, ``extra`` widens a known pose."""
    caps, pose = live.view.get("caps") or {}, live.view.get("pose") or {}
    speed, age, reckoned = caps.get("max_speed") or 0.0, pose.get("age_s"), pose.get("dead_reckon_m")
    if age is None or reckoned is None or live.pose_read_at is None:
        return MAX_EXPECT_TOL_M  # an unknown pose error is the widest window, never none
    # ponytail: no along-path error estimate in the map pose: odom drift over the dead-reckoned
    # distance and the path CORE measures, plus trip speed x (pose age + read-to-send + SEND_ALLOWANCE_S;
    # D-767 A: pose age only where CORE measures from pose_stamp), floored by ``expect_tol_min_m``.
    stamped = caps.get("lane_instruction_stamp") and live.at_stamp
    latency = age + (0.0 if stamped else (_ports._monotonic() - live.pose_read_at) + SEND_ALLOWANCE_S)
    tol = max(config.expect_tol_min_m,
              ODOM_DRIFT_PER_M * (reckoned + travel) + speed * latency + ENDPOINT_TOL_M)
    return round(min(tol + extra, MAX_EXPECT_TOL_M), 3)

def bend_geometry(place, arc) -> Optional[tuple[float, float, float, float]]:
    """``(s of the arc start, s of its end, signed turn deg, radius)`` of a ``bend`` place on this
    lane arc in its direction of travel, or None. Both tangent points must lie on the arc and the
    lane must run the bend's entering way at the start (either drawn direction of the place)."""
    if getattr(place, "kind", None) != "bend" or arc.drive_mode != "lane":
        return None
    turn = wrap(place.exit_yaw - place.yaw)
    for entry, delta in ((place.yaw, turn), (wrap(place.exit_yaw + math.pi), -turn)):
        t = place.radius_m * math.tan(abs(delta) / 2)
        off_a, s_a, heading = arc.project(place.x - t * math.cos(entry), place.y - t * math.sin(entry))
        off_e, s_e, _ = arc.project(place.x + t * math.cos(entry + delta), place.y + t * math.sin(entry + delta))
        if (max(off_a, off_e) <= ENDPOINT_TOL_M and s_e > s_a
                and abs(math.degrees(wrap(heading - entry))) <= MAX_WINDOW_BEND_DEG):
            return s_a, s_e, math.degrees(delta), place.radius_m
    return None


def next_bend(live: "LiveTrip", index: int, s: float) -> Optional[dict]:
    """The first bend on this segment the robot has not passed and Fleet has not finished."""
    found = []
    for place_id, place in live.graph.places.items():
        geometry = None if (index, place_id) in live.bends_done else bend_geometry(place, live.arc(index))
        if geometry is not None and s < geometry[1] and geometry[0] < live.segments[index]["s_to"]:
            found.append((geometry[0], place_id, geometry))
    if not found:
        return None
    s_start, place_id, (_, s_end, turn, radius) = min(found)
    return {"place_id": place_id, "s_start": s_start, "s_end": s_end, "turn_deg": turn, "radius_m": radius}


def straight_approach(arc, s: float, s_start: float) -> bool:
    """The lane runs within ``MAX_WINDOW_BEND_DEG`` of its heading at ``s_start`` from ``s`` on:
    CORE measures ``bend_in_m`` as odom travel, and through a corner the robot cuts the lane short
    (SIM 2026-10-08: sent inside the W->S corner, the arc started late, 5 cm outside)."""
    heading = arc.point_at(s_start)[2]
    steps = max(1, math.ceil((s_start - s) / WINDOW_BEND_STEP_M))
    return all(abs(math.degrees(wrap(arc.point_at(s + (s_start - s) * k / steps)[2] - heading)))
               <= MAX_WINDOW_BEND_DEG for k in range(steps + 1))


def bend_fields(live: "LiveTrip", bend: dict, s: float, active, config: TripConfig, located=None) -> Optional[dict]:
    """D-507 bend fields (D-754 next line, D-759 map entry); None outside a straight same-map approach in (0, 2] m."""
    # Lead: top speed x (pose age + read-to-send + site bend_send_s); unled 2 cm late (10-13), +0.2 s 2 cm early (m16/17).
    caps, pose = live.view.get("caps") or {}, live.view.get("pose") or {}
    age, lead, stamp = pose.get("age_s"), 0.0, live.at_stamp if caps.get("lane_instruction_stamp") else None
    if age is not None and live.pose_read_at is not None and not stamp:  # D-767 A: CORE counts from the stamp
        lead = (caps.get("max_speed") or 0.0) * (age + (_ports._monotonic() - live.pose_read_at) + config.bend_send_s)
    ahead = bend["s_start"] - s
    bend_in = round(max(min(ahead, 0.001), ahead - lead), 3)  # an arc start still ahead stays ahead
    index, segs = live.view["segment_index"], live.segments
    if (active is None or active[0] != live.view["map_version"] or not 0.0 < bend_in <= MAX_EXPECT_IN_M
            or not straight_approach(live.arc(index), s, bend["s_start"])):
        return None
    fields = dict(map_id=active[1].map_id, bend_in_m=bend_in, bend_tol_m=_pose_tol(live, config), bend_radius_m=bend["radius_m"],
                  **({"pose_stamp": stamp} if stamp else {}))
    if caps.get("lane_bend_map_entry") and getattr(located, "odom_stamp", None) is not None:  # D-759 2: lane heading there
        fields["map_entry"] = {"yaw_rad": round(live.arc(live.view["segment_index"]).point_at(bend["s_start"])[2], 4),
                               "pose_yaw_rad": located.yaw, "odom_stamp_s": located.odom_stamp}
    k = next((k for k in range(index, len(segs)) if ends_at_place(live.graph, segs[k])), None)
    past = line_past(live.graph, *live.arc(k).point_at(segs[k]["s_to"])) if caps.get("lane_bend_next_line") and k is not None else None
    if past is not None:  # D-754: vertex -> arc end -> that place -> its painted line; no known line, no field
        line = bend["radius_m"] * math.tan(math.radians(abs(bend["turn_deg"])) / 2) - live.progress(index, bend["s_end"])
        fields["next_line_in_m"] = round(max(0.0, min(line + live.progress(k, segs[k]["s_to"]) + past, MAX_EXPECT_IN_M)), 3)
    return fields


def line_past(graph, x: float, y: float, heading: float) -> Optional[float]:
    """How far along ``heading`` from ``(x, y)`` the first painted cross line is, or None when
    ``(x, y)`` is off the lanes or the lanes run on past ``MAX_PIVOT_PAST_LINE_M``. Only
    ``lane`` arcs are painted (a ``free`` arc is no tape).

    D-507 2 (2026-10-08): the painted lines are the edge of the lanes' union, each lane a band of
    ``width_m`` around its centre line. A lane mouth breaks a line (the roundabout's outer line at
    a spoke); an island keeps one (its inner line, the far edge the keeper measures at the 260919
    SW spoke: 0.404 m here against 0.402 m in SIM).
    """
    cos, sin = math.cos(heading), math.sin(heading)
    near = [arc for arc in graph.arcs.values()
            if arc.drive_mode == "lane" and arc.project(x, y)[0] <= MAX_PIVOT_PAST_LINE_M + arc.width_m]

    def off(t: float) -> bool:
        return all(arc.project(x + t * cos, y + t * sin)[0] > arc.width_m / 2 for arc in near)

    if off(0.0):
        return None
    t, step = 0.0, LINE_STEP_M
    while t <= MAX_PIVOT_PAST_LINE_M and not off(t + step):
        t += step
    while step > 0.001:
        step /= 2
        if not off(t + step):
            t += step
    past = round(t + step, 3)
    return past if past <= MAX_PIVOT_PAST_LINE_M else None


def _lane_steps(arc, s_to: float, remaining: float) -> list:
    """Heading changes (rad, left +) along the rest of the lane, WINDOW_BEND_STEP_M apart."""
    steps = max(1, math.ceil(remaining / WINDOW_BEND_STEP_M))
    headings = [arc.point_at(s_to - remaining * (1 - k / steps))[2] for k in range(steps + 1)]
    return [wrap(b - a) for a, b in zip(headings, headings[1:])]


def _lane_turn(arc, s_to: float, remaining: float) -> float:
    """The signed heading change (rad, left +) along the rest of the lane to the place."""
    return sum(_lane_steps(arc, s_to, remaining))


def _curve_offset_m(arc, s_to: float, remaining: float, pose: dict) -> float:
    """A robot this far beside the lane drives a curve this much longer or shorter than its
    centre line: the offset times the heading change (rad) along the rest of the lane. Safety
    review 2026-10-08: the window compares travelled distance, so this widens it."""
    if pose.get("x") is None or pose.get("y") is None:
        return 0.0
    offset = arc.project(pose["x"], pose["y"])[0]
    return offset * sum(abs(step) for step in _lane_steps(arc, s_to, remaining))


def arc_newer(seq, base: Optional[int]) -> bool:
    """D-520 2: CORE opened arc ``seq`` after the one numbered ``base`` (None: none seen)."""
    return isinstance(seq, int) and not isinstance(seq, bool) and (base is None or seq > base)


def pose_view(pose: Optional[MapPose]) -> Optional[dict]:
    if pose is None:
        return None

    def rounded(value, digits):
        return None if value is None else round(value, digits)

    return {"x": rounded(pose.x, 3), "y": rounded(pose.y, 3), "yaw": rounded(pose.yaw, 3), "state": pose.state,
            "source": pose.source, "dead_reckon_m": rounded(pose.dead_reckon_m, 3),
            "age_s": rounded(pose.age_s, 2), "anchor_age_s": getattr(pose, "anchor_age_s", None)}
