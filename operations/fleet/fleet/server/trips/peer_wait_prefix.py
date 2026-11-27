"""Dispatch a reserved prefix to an intermediate waiting place on the original road plan."""
import math
import time
from contextvars import ContextVar

from core_common.protocol.evidence import STALE_POSE_S
from core_common.robot_body import nominal_body_for
from fleet.localization.trust import route_distance
from fleet.site_map import _polyline_polygon_gap
from fleet.traffic.config import DEFAULT_SITE_KEEP_OUT_M
from fleet.traffic.zone_hold import hold_back_m


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


def road_centerline(live, pos, along, end):
    here = live.view["pose"]
    path = [(here["x"], here["y"])]
    for i in range(pos, end + 1):
        segment, arc = live.segments[i], live.arc(i)
        start = along if i == pos else segment["s_from"]
        finish = segment["s_to"]
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
    now = time.time()
    if (robot_id != mover or not original_peers <= peers or not reserved() or not route
            or fresh_native_slam(console._seen.get(robot_id), now) is None or route[0] != map_id
            or len(route[1]) != len(expected)
            or any(math.dist(pt, xy) > NAV2_ROUTE_MIN_GAP_M for pt, xy in zip(route[1], expected))):
        return False
    clearance = getattr(console, "_site_keep_out_m", DEFAULT_SITE_KEEP_OUT_M)  # the one keep-out, no extra 0.03
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
