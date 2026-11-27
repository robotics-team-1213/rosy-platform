"""Dispatch a reserved prefix to an intermediate waiting place on the original road plan."""
import math
import time
from contextvars import ContextVar

from core_common.protocol.evidence import STALE_POSE_S
from core_common.robot_body import nominal_body_for
from fleet.lane_progress import MIN_GAP_M
from fleet.localization.trust import route_distance
from fleet.site_map import _polyline_polygon_gap
from fleet.traffic.zone_hold import STEP_M, hold_back_m, stop_touches_zone


# Internal to a single awaited route call. Console performs the same check again at the HTTP write.
prefix_guard = ContextVar("road_wait_prefix_guard", default=None)


def downstream_refusal(reply, robot):
    peers = reply.get("waiting_on")
    if not (reply.get("stage") == "pre_dispatch_peer_check" and reply.get("command_robot_id") == robot
            and reply.get("dispatch_attempted") is False and reply.get("queued") is False
            and peers and robot not in peers and reply.get("blocked_by") in peers):
        return False
    if reply.get("reason") in {"ROUTE_CONFLICT", "YIELDING"}:
        return True
    evidence = reply.get("peer_evidence") or {}
    return (reply.get("reason") == "LOCALIZATION_UNTRUSTED" and all(
        (evidence.get(rid) or {}).get("reason") == "keep_out_intersection" for rid in peers))


def reservation_covers(runner, live, index):
    row = live.traffic or {}
    end, front, stamp = (row.get(k) for k in ("authority_end_m", "front_d_m", "pose_stamp"))
    body = nominal_body_for((live.view.get("caps") or {}).get("kind"))
    target = live.segments[0]["s_from"] + live.progress(index, live.segments[index]["s_to"])
    return (body is not None and all(type(v) in (int, float) and math.isfinite(v) for v in (end, front, stamp))
            and 0 <= runner._clock() - stamp < STALE_POSE_S and not runner.traffic.holds(live, index)
            and target + body.rotation_clear_m() <= end
            and runner.traffic.owns_span(live, front, target + body.rotation_clear_m()))


def table_answer(runner, live) -> dict | None:
    """This trip revision's fresh block-table answer (D-1009 road route), or None: then no peer is left to it."""
    row = live.traffic or {}
    stamp, front = row.get("pose_stamp"), row.get("front_d_m")
    if (live.convoy or row.get("route_rev") != live.route_rev or not isinstance(row.get("peers"), dict)
            or not all(type(v) in (int, float) and math.isfinite(v) for v in (stamp, front))
            or not 0 <= runner._clock() - stamp < STALE_POSE_S):
        return None
    return row


def traffic_end_index(runner, live, index: int) -> int | None:
    """Last segment index allowed by the Fleet traffic block table, or ``None`` if held here.

    With a fresh table answer the route also ends at the place before the first unit another robot occupies,
    so a road route is never sent into an occupied block (the standing peers the table counted are left to it)."""
    from fleet.traffic.lane_traffic import PAST_PLACE_M

    answer = table_answer(runner, live)
    occupied = None if answer is None else answer.get("occupied_ahead_m")
    if (live.traffic or {}).get("refused_at_m") is None and occupied is None:
        return len(live.segments) - 1
    allowed: int | None = None
    for k in range(index, len(live.segments)):
        if runner.traffic.holds(live, k) or (
                occupied is not None and occupied < live.progress(k, live.segments[k]["s_to"]) + PAST_PLACE_M):
            break
        allowed = k
    return allowed


def held_at_m(live) -> float:
    """Plan metres where the table holds this trip: its refusal, else the occupied unit that cut the route."""
    row = live.traffic or {}
    at = row.get("refused_at_m") if row.get("refused_at_m") is not None else row.get("occupied_ahead_m")
    return float(at or 0.0)


def road_centerline(live, pos, along, end, end_s=None):
    here = live.view["pose"]
    path = [(here["x"], here["y"])]
    for i in range(pos, end + 1):
        segment, arc = live.segments[i], live.arc(i)
        start = along if i == pos else segment["s_from"]
        finish = segment["s_to"] if end_s is None or i != end else min(end_s, segment["s_to"])
        path.append(arc.point_at(start)[:2])
        path.extend(point for knot, point in zip(arc.knots, arc.polyline) if start < knot < finish)
        path.append(arc.point_at(finish)[:2])
    return path


def reserved_wait(runner, live, active, pos, along, limit):
    """Nearest legal, strictly intermediate stop with its whole footprint inside held route metres."""
    current = runner._store.active()
    parking = live.view["detail"].get("parking_handoff")
    if (not live.open or live.view.get("hold") or runner.road_speed is None
            or (parking and (parking.get("phase") != "approaching" or parking.get("owner") != "core_docking"
                             or live.request.get("to") != parking.get("staging_place_id"))) or live.repeat or live.convoy
            or live.at is None or current is None or current[0] != active[0]):
        return None, "trip_scope_changed"
    rules = runner._store.rules.active_rules()
    body = nominal_body_for((live.view.get("caps") or {}).get("kind"))
    if rules is None or body is None:
        return None, "wait_rules_or_footprint_unknown"
    footprint = body.rotation_clear_m()
    origin = live.progress(pos, along)
    full = live.progress(limit, live.segments[limit]["s_to"])
    here = live.view.get("pose") or {}
    if here.get("state") != "LOCALIZED" or not all(type(here.get(k)) in (int, float) for k in ("x", "y")):
        return None, "mover_pose_unknown"
    for i in range(pos, limit):
        target = live.segments[i]["s_to"]
        distance = live.progress(i, target)
        if min(distance - origin, full - distance) <= runner.config.arrive_free_m:
            continue
        place = live.graph.places.get(live.place(i))
        if (place is None or place.kind != "stop" or place.precision_stop or place.stop_zone
                or hold_back_m(runner.traffic, live.segments[i]) != 0.0
                or math.hypot(place.x - here["x"], place.y - here["y"]) <= runner.config.arrive_free_m
                or {stop.role for stop in rules.stops if stop.place == place.id} != {"wait"}):
            continue
        if any(_polyline_polygon_gap([(place.x, place.y)] * 2, region) <= footprint
               for crossing in active[1].crosswalks for region in (crossing.polygon, *crossing.approach)):
            continue
        path = road_centerline(live, pos, along, i)
        wait = live.view["detail"].get("peer_wait") or {}
        for proof in (wait.get("peer_evidence") or {}).values():
            if proof.get("reason") != "keep_out_intersection":
                continue
            for obstacle in proof.get("observations", []):
                if route_distance(path, (obstacle["x"], obstacle["y"])) <= obstacle["keep_out_m"]:
                    return None, "no_wait_before_peer_clearance"
        if not reservation_covers(runner, live, i):
            return None, "wait_place_outside_authority"
        return i, "reserved_wait_place"
    return None, "no_intermediate_wait_place"


def check_wait_prefix(console, robot_id, points, site_route_of):
    """Additional reservation and localization veto for an intermediate waiting place."""
    from fleet.localization import trust
    from fleet.server.named_stop_map_pose import fresh_native_slam
    from fleet.server.nav2_route_sampling import NAV2_ROUTE_MIN_GAP_M

    prefix = prefix_guard.get()
    if prefix is None:
        return True
    here = console._pose_of(robot_id)
    route = site_route_of([here, *((p["x"], p["y"]) for p in points)]) if here is not None else None
    mover, map_id, original_peers, reserved, expected, centerline = prefix
    peers = set(console._order) - {robot_id}
    # A table cut can name pseudo nodes (a signal, a pose jump): they are no roster robot to wait on.
    original_peers = {rid for rid in original_peers if not rid.startswith("signal:") and rid != "pose_jump"}
    now = time.time()
    if (robot_id != mover or not original_peers <= peers or not reserved() or not route
            or fresh_native_slam(console._seen.get(robot_id), now) is None or route[0] != map_id
            or len(route[1]) != len(expected)
            or any(math.dist(pt, xy) > NAV2_ROUTE_MIN_GAP_M for pt, xy in zip(route[1], expected))):
        return False
    clearance = getattr(console, "_site_keep_out_m", 0.18) + NAV2_ROUTE_MIN_GAP_M
    markers = getattr(console, "_site_marker_clearance", None)
    for rid in peers:
        for corridor in (route, (map_id, centerline)):
            if markers is not None and rid in markers.offline:
                # Its old pin can corroborate current marker observations but cannot replace them.
                independent = console._site_obstacle_pose(rid) if console._site_obstacle_pose else None
                if markers.clear(console, rid, corridor, clearance, independent) is not True:
                    return False
            else:
                pose = console._site_mover_pose(rid) if console._site_mover_pose else None
                if (not pose or pose[0] != map_id or fresh_native_slam(console._seen.get(rid), now) is None
                        or trust.blocks(corridor[1], pose[1:3], keep_out_m=clearance)):
                    return False
    return True


# ---- table-cut hold point (2026-11-27: depart, stop short of the peer, wait, continue) -------------------

def blockers(live) -> list[str]:
    """Who the block table holds this trip for: its refusal's waiting robots, then the owners of the cut unit."""
    row = live.traffic or {}
    named = list(row.get("waiting_for") or [])
    return named + [rid for rid in row.get("occupied_ahead_by") or () if rid not in named]


def _hold_margin(runner, body) -> float:
    """Base-centre metres a hold point keeps before the table's cut: the turn footprint and the road-speed gap."""
    rules = runner._store.rules.active_rules()
    gap = getattr(getattr(rules, "formation", None), "min_gap_m", None) or MIN_GAP_M
    return max(body.rotation_clear_m(), gap)


def hold_covered(runner, live, index, end_s) -> bool:
    """A fresh table answer still covers a stop at arc metre ``end_s`` of segment ``index`` (route metres throughout):
    its turn footprint inside the authority and the held span, and the margin before any refusal or occupied unit.
    Unlike ``reservation_covers``, a refusal later on the same segment beyond the stop does not count against it."""
    row = live.traffic or {}
    end, front, stamp = (row.get(k) for k in ("authority_end_m", "front_d_m", "pose_stamp"))
    body = nominal_body_for((live.view.get("caps") or {}).get("kind"))
    if body is None or not all(type(v) in (int, float) and math.isfinite(v) for v in (end, front, stamp)):
        return False
    base = live.segments[0]["s_from"]  # plan metres + base = route metres (the table's own frame)
    stop = base + live.progress(index, end_s)
    cut = min((base + row[k] for k in ("refused_at_m", "occupied_ahead_m") if row.get(k) is not None), default=math.inf)
    reach = stop + body.rotation_clear_m()
    eps = 1e-9  # the stop was cut from these same bounds
    return (0 <= runner._clock() - stamp < STALE_POSE_S and reach <= end + eps
            and stop + _hold_margin(runner, body) <= cut + eps and runner.traffic.owns_span(live, front, reach - eps))


def _tight_curve(arc, segment, s, reach) -> bool:
    from fleet.server.nav2_route_sampling import NAV2_CURVE_RADIUS_M, _wrap_angle

    lo, hi = max(segment["s_from"], s - reach), min(segment["s_to"], s + reach)
    return hi > lo and abs(_wrap_angle(arc.point_at(hi)[2] - arc.point_at(lo)[2])) * NAV2_CURVE_RADIUS_M > hi - lo


def hold_point(runner, live, active, index, s):
    """``(end_s, why)``: the farthest stop (arc metres) on the current segment before a table cut, else ``(None, why)``.

    The stop's turn footprint stays inside the table's authority, the held span and this segment (no junction pivot),
    keeps ``_hold_margin`` before the cut, and steps back ``STEP_M`` while it touches a zone unit, a crosswalk or
    a curve tighter than the sampler's curve radius. Peer clearance is the console's wire check (``check_wait_prefix``)."""
    row = table_answer(runner, live)
    body = nominal_body_for((live.view.get("caps") or {}).get("kind"))
    if row is None or body is None or live.view.get("hold") is not None:
        return None, "no_table_answer"
    clear = body.rotation_clear_m()
    segment, arc = live.segments[index], live.arc(index)
    base = live.segments[0]["s_from"]
    to_arc = base + live.progress(index, segment["s_from"]) - segment["s_from"]  # route metres -> arc metres
    cut = min((base + row[k] for k in ("refused_at_m", "occupied_ahead_m") if row.get(k) is not None), default=math.inf)
    end = row.get("authority_end_m")
    if type(end) not in (int, float) or not math.isfinite(end):
        return None, "authority_unknown"
    stop = min(end - clear, cut - _hold_margin(runner, body), segment["s_to"] - clear + to_arc) - to_arc
    crossings = [region for crossing in active[1].crosswalks for region in (crossing.polygon, *crossing.approach)]
    while stop - s > runner.config.arrive_free_m:
        x, y, _ = arc.point_at(stop)
        if not (stop_touches_zone(runner.traffic, arc, stop) or _tight_curve(arc, segment, stop, clear)
                or any(_polyline_polygon_gap([(x, y)] * 2, region) <= clear for region in crossings)):
            return (stop, "hold_point") if hold_covered(runner, live, index, stop) else (None, "hold_outside_authority")
        stop -= STEP_M
    return None, "no_room_to_advance"


def traffic_hold(live, names) -> None:
    live.view["detail"]["traffic_hold"] = {"waiting_for": names, "refused_at_m": round(held_at_m(live), 3)}


def held_receipt(index, reason, names) -> dict:
    return {"kind": "hold_point", "segment": index, "state": "held", "reason": reason, "waiting_on": names}


def hold_or_wait(runner, live, active, index, s, nav, state, names):
    """Under a table cut on segment ``index``: the hold point to send now, else None (the trip waits, blocker named)."""
    from fleet.server.handoff_traffic import _fresh_stopped

    traffic_hold(live, names)
    if live.view["hold"] is not None:
        return None
    detail = live.view["detail"]
    receipt = detail.get("wait_prefix") or {}
    stop, why = hold_point(runner, live, active, index, s)
    if stop is None:
        if receipt.get("kind") == "hold_point" and receipt.get("state") == "at_hold_point":
            receipt["waiting_on"] = names
        else:
            detail["wait_prefix"] = held_receipt(index, why, names)
        return None
    if nav in ("NAVIGATING", "PLANNING") or (receipt.get("state") == "reservation_lost" and not _fresh_stopped(state or {})):
        return None  # replace a route only after it stopped
    return stop


def hold_guard(runner, live, active, index, s, stop, site_pts, names):
    """Set the console's wire veto for a hold-point send: clearance of the sent points and of the centreline to it."""
    revision = live.route_rev

    def reserved():
        return (live.route_rev == revision and live.at is not None and live.at[0] == index
                and hold_covered(runner, live, index, stop))
    centerline = road_centerline(live, index, s, index, end_s=stop)
    expected = [centerline[0], *(point[:2] for point in site_pts)]
    return prefix_guard.set((live.view["robot_id"], active[1].map_id, set(names), reserved, expected, centerline))


def hold_receipt(runner, live, index, stop, xy, names) -> None:
    detail = live.view["detail"]
    live.progress_at = runner._clock()
    detail["wait_prefix"] = {"kind": "hold_point", "segment": index, "end_s": round(stop, 4),
                             "target_xy": [round(v, 4) for v in xy], "route_rev": live.route_rev,
                             "waiting_on": names, "state": "dispatched", "at": live.progress_at}
    detail.pop("named_stop_dispatch", None)


async def supervise_wait_prefix(runner, live, nav, state, pose, target_end, cancel) -> bool:
    """A running wait-prefix route (a named wait place or a table-cut hold point); True: this step ends here."""
    from fleet.server.handoff_traffic import _fresh_stopped

    route = live.active_route
    held = route.get("hold_point")
    receipt = live.view["detail"]["wait_prefix"]
    if nav in ("FAILED", "CANCELED"):
        receipt["state"] = "aborted"
        await runner._stop(live, "stopped", "navigation", {"navigation": nav})
        return True
    if held is not None and target_end is not None:  # the cut moved on or cleared: resend from here
        receipt["state"] = "superseded"
        live.active_route = {**route, "superseded": True}
        return False
    if held is not None and not hold_covered(runner, live, held["segment"], held["end_s"]):
        # The table no longer covers the stop: cancel, then a new hold point once stopped (never a trip end).
        receipt["state"] = "reservation_lost"
        await cancel()
        if live.open and live.active_route is not None:  # the cancel was not confirmed
            await runner._stop(live, "stopped", "WAIT_PREFIX_RESERVATION_LOST", {"wait_prefix": receipt})
        return True
    if held is None and not reservation_covers(runner, live, route["end_index"]):
        receipt["state"] = "reservation_lost"
        await runner._stop(live, "stopped", "WAIT_PREFIX_RESERVATION_LOST", {"wait_prefix": receipt})
        return True
    if nav in ("IDLE", "ARRIVED"):
        target = receipt.get("target_xy")
        if target is None:
            place = live.graph.places[receipt["place"]]
            target = (place.x, place.y)
        if not _fresh_stopped(state) or math.dist((pose.x, pose.y), target) > runner.config.arrive_free_m:
            receipt["state"] = "waiting_stop_confirmation"
            return True
        receipt["state"] = "at_hold_point" if held is not None else "at_wait_place"
        live.active_route = None
    return False
