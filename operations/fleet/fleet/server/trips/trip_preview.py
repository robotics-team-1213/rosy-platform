"""D-767 P0: the route preview, events up to 2 m ahead of each trip robot; shown on /traffic, never sent.
From the pose the step already read (D-760 8 shared read) in the table's route metres (``at_m = s_m -
front_d_m``) with the instruction code's geometry. ``preview_mismatch``: a place sent this period off its
event's ``s_m`` by > MISMATCH_TOL_M. ``ROSY_ROUTE_PREVIEW_LOG=<file>``: JSON lines for the D-767 7 runs."""
from __future__ import annotations

import json
import logging
import os
import time

from core_common.robot_body import PINKY_PRO
from fleet.routing.cost import LEFT, RIGHT, STOP
from fleet.routing.execute import exit_segment, lane_action, turn_target
from fleet.server.trip_ports import MAX_EXPECT_IN_M, bend_geometry, line_past, next_bend
from fleet.site_map import CROSSWALK_MAX_SPAN_M, crosswalk_spans
from fleet.traffic.trip_advice import FLEET_EPOCH
from fleet.traffic.zone_hold import hold_back_m

_LOG = logging.getLogger(__name__)
MAX_EVENTS, LEASE_S, TTL_S, MISMATCH_TOL_M, CHANGE_M, START_QUIET_S = 8, 8.0, 2.0, 0.005, 0.01, 5.0
LOG_ENV, _STARTED = "ROSY_ROUTE_PREVIEW_LOG", time.monotonic()


def build(live, active, approaches: dict, traffic, routing, config):
    """This period's preview, or None: no located front, ``link_wait``, a pose jump, another map version."""
    table, view, segs, graph = live.traffic or {}, live.view, live.segments, live.graph
    front, reach = table.get("front_d_m"), table.get("authority_end_m")  # R: 0 under hold_back
    if (live.at is None or front is None or view["state"] == "link_wait" or active is None
            or active[0] != view["map_version"] or "pose_jump" in (table.get("waiting_for") or ())):
        return None
    (index, s), events, reach = live.at, [], reach if view.get("traffic_authority") == "core" else None
    route = [(segs[0]["s_from"] + live.progress(i, g["s_from"]), live.arc(i), g["s_from"]) for i, g in enumerate(segs)]
    here, end = route[index][0] + s - segs[index]["s_from"], route[-1][0] + segs[-1]["s_to"] - segs[-1]["s_from"]
    speed = (view.get("caps") or {}).get("max_speed") or 0.0
    room = max(0.0, (front if reach is None else reach) - front) + PINKY_PRO.stop_gap_m(speed)
    horizon = max(0.0, min(MAX_EXPECT_IN_M, end - front, max(room, speed * LEASE_S)))
    for k in range(index, len(segs)):
        (base, arc, lo), hi, place, last = route[k], segs[k]["s_to"], live.place(k), k == len(segs) - 1
        at, held = base + hi - lo, view["hold"] is not None and k == index
        if base > front + horizon:
            break
        if place is not None and (held or last and not live.repeat):
            back = hold_back_m(traffic, segs[k]) or 0.0
            events.append((at - back, "stop", place, {"reason": "hold" if held else "trip_end", "hold_back_m": back}))
        if arc.drive_mode != "lane":
            continue
        for place_id, bend in graph.places.items():
            g = None if (k, place_id) in live.bends_done else bend_geometry(bend, arc)
            if g is not None and lo <= g[0] < hi:
                events.append((base + g[0] - lo, "bend", place_id, {"turn_deg": round(g[2], 1), "radius_m": g[3]}))
        if place is not None and arc.id in approaches:
            events.append((at, "signal", place, {"signal_id": approaches[arc.id], "approach": arc.id}))
        if place is None or last or held:
            continue
        action = lane_action(graph, segs, k, routing)
        past = line_past(graph, *arc.point_at(hi)) if action != STOP else None
        params = {"action": action, "line_before_m": -past if past else 0.0,
                  "turn_deg": round(turn_target(graph, segs, k), 1) if action in (LEFT, RIGHT) else None}
        stop = (hold_back_m(traffic, segs[k]) or 0.0) if action == STOP else 0.0  # a hand-over stop, as sent
        events.append((at - stop, "turn", place, params))
        ex = action != STOP and exit_segment(graph, segs, k, fit_tol_m=config.arc_fit_tol_m,
                                             outer_line_offset_m=config.arc_outer_line_offset_m)
        if ex:
            events.append((at, "arc", place, {"curvature_1pm": ex["curvature_1pm"], "length_m": ex["length_m"]}))
    for walk in active[1].crosswalks:  # CORE's near edge (D-491), before the D-573 s_wait
        for near, far in crosswalk_spans(route, here, min(end, front + horizon + CROSSWALK_MAX_SPAN_M), walk.polygon):
            length = None if far is None else round(far - near, 3)
            events.append((near, "crosswalk", None, {"zone_id": walk.id, "length_m": length}))
    if reach is not None:
        events.append((reach, "authority_end", None, {"authority_id": (live.authority or {}).get("authority_id")}))
    rows = sorted((e for e in events if here <= e[0] <= front + horizon), key=lambda e: e[0])[:MAX_EVENTS]
    return {"leg_id": f"{view['trip_id']}:{live.route_rev}:{FLEET_EPOCH}", "pose_stamp": table.get("pose_stamp"),
            "map_version": view["map_version"], "horizon_m": round(horizon, 3), "front_d_m": front,
            "events": [{"s_m": round(d, 3), "at_m": round(d - front, 3), "kind": kind, "place_id": place_id,
                        "params": params} for d, kind, place_id, params in rows]}


def observe(lives, inflight, traffic, store, routing, config, now: float) -> None:
    """After the table: build each settled robot's preview, count changes ("changed": another leg, event set or
    params, or an ``s_m`` moved > CHANGE_M) and mismatches, put a fresh one (≤ TTL_S) on its /traffic row."""
    active, rows = store.active(), {row["robot_id"]: row for row in traffic.view().get("robots") or ()}
    approaches = {a["approach"]: g["signal_id"] for g in traffic.view().get("signals") or () for a in g["approaches"]}
    for live in [live for live in lives if live.open and live.view["robot_id"] not in inflight]:
        old, quiet = getattr(live, "preview", None), time.monotonic() - _STARTED < START_QUIET_S
        new = None if quiet else build(live, active, approaches, traffic, routing, config)
        if new is not None:
            key = lambda p: (p["leg_id"], [(e["kind"], e["place_id"], e["params"]) for e in p["events"]])  # noqa: E731
            changed = old is not None and (key(old) != key(new) or any(
                abs(a["s_m"] - b["s_m"]) > CHANGE_M for a, b in zip(old["events"], new["events"])))
            live.preview_changes = getattr(live, "preview_changes", 0) + changed
            new.update(seq=0 if old is None or old["leg_id"] != new["leg_id"] else old["seq"] + changed, built_at=now)
            live.preview = new
            if os.environ.get(LOG_ENV):
                with open(os.environ[LOG_ENV], "a", encoding="utf-8") as out:
                    out.write(json.dumps({"robot_id": live.view["robot_id"], "t": now, **new}) + "\n")
        sent, seen, live.preview_sent = live.sent, getattr(live, "preview_sent", None), live.sent
        if new is None or sent is None or sent is seen or sent["index"] != live.at[0]:
            continue
        # the instruction's place from the pose it was made from, before any lead (a bend: ``next_bend``)
        (index, s), kind = live.at, {"bend": "bend", STOP: "stop"}.get(sent["action"], "turn")
        seg, d = live.segments[index], live.segments[0]["s_from"] + live.progress(index, s)
        point = d + max(round(seg["s_to"] - s, 3) - ((hold_back_m(traffic, seg) or 0.0) if kind == "stop" else 0), 0.0)
        if kind == "bend":
            bend = next_bend(live, index, s)
            point = None if bend is None or bend["place_id"] != sent["place"] else d + bend["s_start"] - s
        hit = [e["s_m"] for e in new["events"] if e["place_id"] == sent["place"] and e["kind"] in (kind, "turn")]
        if point is not None and (not hit or abs(hit[0] - point) > MISMATCH_TOL_M):
            counts = live.preview_mismatch = getattr(live, "preview_mismatch", {})
            counts[kind] = counts.get(kind, 0) + 1
            _LOG.warning("preview_mismatch %s %s %s: %s, %.3f", live.view["robot_id"], kind, sent["place"], hit, point)
    for live in lives:
        preview, row = getattr(live, "preview", None), rows.get(live.view["robot_id"])
        if live.open and preview is not None and row is not None and now - preview["built_at"] <= TTL_S:
            row["preview"] = {**preview, "age_s": round(now - preview["built_at"], 1),
                              "changes": live.preview_changes, "mismatch": dict(getattr(live, "preview_mismatch", {}))}
