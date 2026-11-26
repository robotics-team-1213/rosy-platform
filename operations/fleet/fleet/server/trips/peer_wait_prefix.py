"""Dispatch a reserved prefix to an intermediate waiting place on the original road plan."""
import math
from contextvars import ContextVar

from core_common.protocol.evidence import STALE_POSE_S
from core_common.robot_body import nominal_body_for
from fleet.localization.trust import route_distance
from fleet.site_map import _polyline_polygon_gap
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
