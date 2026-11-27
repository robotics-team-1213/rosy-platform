"""Road-following Nav2 route sampling and per-period dispatch for ``TripRunner``."""

from __future__ import annotations

import asyncio
import time
import math
from uuid import uuid4

from core_common.protocol.evidence import STALE_POSE_S
from core_common.robot_body import nominal_body_for
from fleet.routing.execute import arc_id, plan_again, route_key
from fleet.server.charge_goal_gate import ready_free_goal
from fleet.server.held_lidar_observation import inspect_held_route
from fleet.server.named_stop_confirm import record_stop_dispatch, record_stop_operation
from fleet.server.named_stop_map_pose import precision_map_pose
from fleet.server.nav2_route_sampling import NAV2_SPLIT_WALL_CLEAR_M, _wrap_angle, sample_nav2_route
from fleet.server.peer_wait_prefix import downstream_refusal, prefix_guard, reserved_wait, road_centerline
from fleet.server.peer_wait_prefix import blockers as _blockers, fence, fenced, footprint_end, held_receipt, hold_guard
from fleet.server.peer_wait_prefix import hold_or_wait, hold_receipt, supervise_wait_prefix, traffic_hold
from fleet.server.peer_wait_prefix import held_at_m as _held_at_m, table_answer as _table_answer, traffic_end_index as _traffic_end_index
from fleet.server.trip_geometry import SiteFrameMismatch, _wall_clearance, robot_frame_goal  # noqa: F401
from fleet.server.trip_geometry import convert_route_points as _convert_points
from fleet.server.trip_halts import _cancel_ack
from fleet.server.trip_lane_realign import observe as observe_lane_departure
from fleet.server.road_route_lease import RoadSpeedRefused
from fleet.server.trip_live import LiveTrip
from fleet.server.transient_loc_hold import (hold_transient_localization, loc_diag_from_state,
                                              recheck_binding)
from fleet.server.trip_ports import TripError
from fleet.server.trip_start_checks import crosswalks_on, signals_on, start_check
from fleet.swarm.dispatch_guard import dispatch_guard
from fleet.swarm.transport import RobotApiError
from rosy.world.state.projections.map_pose_samples import parse_utc

NAV2_RETRY_S = 5.0
NAV2_TRANSIENT_RETRY_S = 2.0
NAV2_RETRIES = 2
NAV2_MAX_REPLANS = 2
_NAV_RUNNING = ("NAVIGATING", "PLANNING")
_NAV_ABORTED = ("FAILED", "CANCELED")
_IMMEDIATE_HOLD_REASONS = ("fleet_hold", "nav2_problem")
_TRANSIENT_GOAL_REFUSALS = ("ROUTE_CONFLICT", "YIELDING")


def _immediate_hold(live: LiveTrip) -> bool:
    hold = live.view["hold"] or {}
    return hold.get("reason") in _IMMEDIATE_HOLD_REASONS or hold.get("source") == "nav2_problem"


async def _cancel_active_route(runner, live: LiveTrip, robot_id: str, nav: str | None) -> None:
    if live.active_route is None:
        return
    if nav not in ("ARRIVED", "IDLE") and runner._cancel_goal is not None:
        receipt = await runner._call(runner._cancel_goal(robot_id))
        if not _cancel_ack(receipt):
            return
    if not live.open:
        return
    live.view["detail"].pop("named_stop_operation", None)
    live.active_route = None
    runner._fence(robot_id)


def camera_finish_segment(live: LiveTrip, index: int, active, along: float) -> str | None:
    """One reviewed, straight, final painted section ending at a non-precision stop."""
    if (not live.nav2 or live.request.get("camera_lane_fallback") is not True or live.repeat
            or index != len(live.segments) - 1 or live.view.get("hold") is not None
            or live.request.get("arrive_yaw") is not None
            or not live.view["detail"].get("nav2_binding_id")
            or active is None or active[0] != live.view["map_version"]):
        return None
    arc, segment = live.arc(index), live.segments[index]
    place = live.graph.places.get(arc.end_place)
    if (arc.drive_mode != "lane" or live.request.get("to") != arc.end_place
            or place is None or place.kind != "stop" or not place.pinned
            or place.precision_stop is not None or place.stop_zone is not None
            or not segment["s_from"] < along < segment["s_to"]
            or abs(segment["s_to"] - arc.length_m) > 1e-4):
        return None
    site = active[1]
    edge = next((item for item in site.edges if item.id == arc.edge_id), None)
    evidence = edge.evidence if edge is not None else None
    if (site.survey is None or not site.survey.reviewed or evidence is None
            or evidence.status != "reviewed" or evidence.source != "camera"
            or evidence.reference_revision != site.survey.revision):
        return None
    (x0, y0), (x1, y1) = arc.polyline[0], arc.polyline[-1]
    # Distance to the chord must be within the map's millimetre precision and no doubles back.
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    if length <= 0.0 or arc.length_m - length > .001:
        return None
    if any(abs(dx * (y - y0) - dy * (x - x0)) / length > .001 for x, y in arc.polyline):
        return None
    yaw = getattr(place, "yaw", None)
    if yaw is not None and abs(_wrap_angle(yaw - math.atan2(dy, dx))) > math.radians(1):
        return None
    return arc.end_place


def camera_body_inside(live, index: int, pose) -> bool:
    arc = live.arc(index)
    body = nominal_body_for((live.view.get("caps") or {}).get("kind"))
    if body is None:
        return False
    lateral, _, _ = arc.project(pose.x, pose.y)
    return lateral + body.rotation_radius_m + body.sweep_pad_m <= arc.width_m / 2


async def _camera_stationary(runner, live, after: float) -> float | None:
    """Require two distinct fresh zero samples, returning the conservative trip lease deadline."""
    previous = None
    robot_id = live.view["robot_id"]
    lease_id = (live.view.get("lease") or {}).get("lease_id")
    if lease_id is None:
        return None
    for _ in range(4):
        if not live.open or live.view["hold"] is not None:
            return None
        read_started = runner._clock()
        state = await runner._call(runner.named_stop_state(robot_id))
        evidence = (state.get("evidence") or {}).get("velocity") or {}
        vel, line = state.get("velocity") or {}, state.get("line_follow") or {}
        lease = state.get("trip_lease") or {}
        expires_in = lease.get("expires_in_s")
        deadline = read_started + expires_in if type(expires_in) in (int, float) and math.isfinite(expires_in) else -math.inf
        stamp = parse_utc(evidence.get("sampled_at"))
        if (evidence.get("evidence") == "fresh" and stamp is not None
                and stamp > after and 0 <= runner._clock() - stamp < STALE_POSE_S
                and state.get("mode") in {"IDLE", "NAVIGATION"}
                and lease.get("lease_id") == lease_id and deadline > runner._clock()
                and state.get("navigation") in {"IDLE", "CANCELED", "FAILED", "ARRIVED"}
                and (state.get("safety") or {}).get("estop") is False and line.get("mode") == "OFF"
                and all(type(vel.get(axis)) in (float, int) and vel[axis] == 0.0 for axis in ("linear", "angular"))):
            if previous is not None and stamp > previous:
                return deadline
            previous = stamp
        else:
            previous = None
        await asyncio.sleep(runner.config.period_s)
    return None


async def _start_camera_finish(runner, live, index: int, along: float, active) -> bool:
    place = camera_finish_segment(live, index, active, along)
    if (place is None or runner.named_stop_state is None or runner._cancel_goal is None or not runner.lease.required
            or runner.traffic.holds(live, index) or live.segments[index]["s_to"] - along > runner.config.arm_distance_m):
        return False
    robot_id, segment = live.view["robot_id"], live.segments[index]
    caps = await runner._caps_checks(robot_id, live.graph, [segment], False, place)
    if (runner.authority.mode(caps) != "core" or not caps.line_follow_authority_required
            or crosswalks_on(live.graph, [segment], active[1].crosswalks)
            or signals_on(runner.traffic, [segment])):
        return False
    if not _cancel_ack(await runner._call(runner._cancel_goal(robot_id))):
        raise TripError(409, "TRIP_CAMERA_FALLBACK_STOP_UNCONFIRMED")
    lease_deadline = await _camera_stationary(runner, live, runner._clock())
    if lease_deadline is None:
        raise TripError(409, "TRIP_CAMERA_FALLBACK_STOP_UNCONFIRMED")
    live.active_route = None
    scope = live.view["map_version"], live.view["detail"]["nav2_binding_id"]
    camera = await runner._call(runner._junction.front_camera(robot_id)) or {}
    age_ms, observed = camera.get("age_ms"), runner._clock()
    if (camera.get("available") is not True or camera.get("stale") is not False
            or type(age_ms) not in (int, float) or not 0 <= age_ms < 1000):
        raise TripError(409, "TRIP_LANE_CAMERA_UNAVAILABLE")
    pose = await precision_map_pose(runner, robot_id, scope)
    if (pose is None or not camera_body_inside(live, index, pose)
            or start_check(live.graph, [segment], pose.x, pose.y, pose.yaw,
                           runner.config.start_heading_tol_deg)["code"]):
        raise TripError(409, "TRIP_CAMERA_FALLBACK_POSE_UNTRUSTED")
    _, fresh_along, _ = live.arc(index).project(pose.x, pose.y)
    if (camera_finish_segment(live, index, active, fresh_along) is None
            or segment["s_to"] - fresh_along > runner.config.arm_distance_m):
        raise TripError(409, "TRIP_CAMERA_FALLBACK_POSE_UNTRUSTED")
    pose_stamp = runner._clock() - pose.age_s

    def check():
        runner._check_human_hold()
        now = runner._clock()
        current = runner._store.active()
        binding = runner._store.map_bindings.active(robot_id) or {}
        if (not live.open or live.view["hold"] is not None or runner.traffic.holds(live, index)
                or now >= lease_deadline or current is None or current[0] != scope[0]
                or binding.get("binding_id") != scope[1]
                or not 0 <= now - pose_stamp < STALE_POSE_S or not 0 <= now - pose.odom_stamp < STALE_POSE_S
                or not 0. <= now - observed < 1. - age_ms / 1000):
            raise TripError(409, "TRIP_CAMERA_FALLBACK_ADMISSION_CHANGED")

    # Persist ambiguous ownership before the PUT. Restart/cancel stops both controllers.
    phase = {"phase": "starting", "index": index, "started_at": runner._clock(),
             "authority_end_m": live.segments[0]["s_from"] + live.progress(index, segment["s_to"])}
    live.view["detail"].update(camera_lane_fallback=phase, line_follow_started=False)
    runner._save(live)
    with dispatch_guard(check, paths={"/api/v1/line-follow/mode"}):
        check()
        await runner._start_line(live)
    if live.open:
        phase["phase"] = "running"
        live.view["traffic_authority"] = "core"
        runner._save(live)
    return True


async def finish_camera_line(runner, live) -> None:
    """End the replacement owner and prove stationary before reporting arrival."""
    rid = live.view["robot_id"]
    live.view["detail"]["line_follow_started"] = False
    runner._save(live)
    result = await runner._call(runner._junction.hold(rid))
    if (not isinstance(result, dict) or result.get("mode") != "OFF"
            or await _camera_stationary(runner, live, runner._clock()) is None):
        raise TripError(409, "TRIP_CAMERA_FALLBACK_STOP_UNCONFIRMED")
    fallback = live.view["detail"]["camera_lane_fallback"]
    scope = live.view["map_version"], live.view["detail"]["nav2_binding_id"]
    pose = await precision_map_pose(runner, rid, scope)
    if pose is None or not runner._arrived(live, fallback["index"], 0.0, True, pose):
        raise TripError(409, "TRIP_CAMERA_FALLBACK_POSE_UNTRUSTED")
    live.view["traffic_authority"] = "hold_back"
    fallback["phase"] = "completed"


async def _handle_nav2_failure(runner, live: LiveTrip, index: int, _s: float, pose, active) -> None:
    """Ask Fleet for an alternate path, retry transiently, or hold cleanly for Fleet resume."""
    robot_id = live.view["robot_id"]
    live.active_route = None
    runner._fence(robot_id)
    now = runner._clock()
    if live.nav2_replans < NAV2_MAX_REPLANS:
        candidates = []
        if index + 1 < len(live.segments):
            candidates.append(live.nav2_blocked | {live.segments[index + 1]["edge_id"]})
        candidates.append(live.nav2_blocked | {live.segments[index]["edge_id"]})
        passed = {live.place(i) for i in range(index) if live.place(i) is not None}
        for closed in candidates:
            if closed == live.nav2_blocked:
                continue
            body, _hold = plan_again(
                active, (pose.x, pose.y, pose.yaw), live.request, live.view.get("caps") or {},
                frozenset(runner._blocked()) | closed, passed, runner._routing, runner.config.max_turn_deg,
                nav2_off_lane_margin_m=runner.config.nav2_off_lane_margin_m,
            )
            if body is None or route_key(body["segments"]) == route_key(live.segments[index:]):
                continue
            live.view["hold"] = {
                "reason": "replan", "map_version": body["map_version"],
                "plan": {k: body[k] for k in ("segments", "places", "actions")},
                "length_m": body["length_m"], "eta_s": body["eta_s"],
                "source": "nav2_problem", "blocked_edges": sorted(closed),
            }
            confirmed = await runner._ai_confirm(live, "fleet-rule")
            if confirmed:
                live.nav2_replans += 1
                live.nav2_blocked.update(closed)
                live.nav2_retries = 0
                live.nav2_retry_at = -math.inf
                live.progress_at = now
                live.view["detail"]["nav2_problem"] = {
                    "state": "rerouted", "blocked_edges": sorted(closed), "replans": live.nav2_replans, "at": now,
                }
                return
            if live.view["hold"] is not None:
                live.view["detail"]["nav2_problem"] = {
                    "state": "held", "code": live.view["detail"].get("ai_replan_refused") or "NAV2_FAILED",
                    "blocked_edges": sorted(closed), "at": now,
                }
                return
    if live.nav2_retries < NAV2_RETRIES:
        live.nav2_retries += 1
        live.nav2_retry_at = now + NAV2_RETRY_S
        # Bound retry cooldown without tripping stall_s during Fleet recovery.
        live.progress_at = now
        live.view["detail"]["nav2_problem"] = {
            "state": "retry_wait", "attempt": live.nav2_retries, "max_retries": NAV2_RETRIES,
            "retry_at": live.nav2_retry_at, "edge_id": live.segments[index]["edge_id"], "at": now,
        }
        return
    edge_id = live.segments[index]["edge_id"]
    live.view["hold"] = {
        "reason": "nav2_problem", "code": "NAV2_FAILED", "plan": None,
        "edge_id": edge_id, "attempts": live.nav2_retries, "at": now,
    }
    live.view["detail"]["nav2_problem"] = {
        "state": "held", "code": "NAV2_FAILED", "edge_id": edge_id, "attempts": live.nav2_retries, "at": now,
    }


def _route_finished(runner, live: LiveTrip, index: int, s: float, nav: str | None,
                    target_end: int | None = None, pose=None) -> str:
    """Return ``'busy'``, ``'aborted'``, or ``'ready'`` for sending the next route."""
    if nav == "CANCELED" and (live.active_route or {}).get("superseded"):
        return "ready"  # our own cancel of a replaced route (its ack lost): resend, never an abort
    if nav in _NAV_ABORTED:
        return "aborted"
    if nav in _NAV_RUNNING:
        return "busy"
    active = live.active_route
    if active is None:
        return "ready"
    if active.get("superseded"):
        return "ready"
    end_idx = active["end_index"]
    limit = len(live.segments) - 1 if target_end is None else target_end
    more = end_idx < limit and live.view["hold"] is None
    if nav in ("ARRIVED", "IDLE"):
        rem_to_end = (live.segments[end_idx]["s_to"] - s) if index == end_idx else math.inf
        at_end = index > end_idx
        if not at_end and index == end_idx and rem_to_end <= runner.config.arrive_free_m:
            if pose is None:
                at_end = True
            else:
                gx, gy, _ = live.arc(end_idx).point_at(live.segments[end_idx]["s_to"])
                at_end = math.hypot(pose.x - gx, pose.y - gy) <= runner.config.arrive_free_m
        done_here = at_end or live.view["hold"] is not None
        return "ready" if (more or not done_here) else "busy"
    # Fake tests without a navigation field advance once past end_idx (or near its end when more laps exist).
    past_end = index > end_idx or (
        more and index == end_idx and live.segments[end_idx]["s_to"] - s <= runner.config.advance_free_m
    )
    return "ready" if past_end else "busy"


async def step_nav2_route(runner, live: LiveTrip, index: int, s: float, pose) -> None:
    """Dispatch and supervise D-1009 road-following Nav2 routes across laps."""
    from fleet.server.trip_steps import _GoalRefused

    robot_id = live.view["robot_id"]
    active = runner._store.active()
    if active is None or active[0] != live.view["map_version"]:
        await runner._stop(live, "stopped", "map_version", {
            "map_version": live.view["map_version"], "active_version": None if active is None else active[0],
        })
        return
    state = await runner._call(runner._robot_state(robot_id)) if runner._robot_state is not None else None
    nav = state.get("navigation") if isinstance(state, dict) else None
    if _immediate_hold(live):
        await _cancel_active_route(runner, live, robot_id, nav)
        return
    traffic_end = _traffic_end_index(runner, live, index)
    target_end = None if traffic_end is None else (min(index, traffic_end) if live.view["hold"] is not None else traffic_end)
    # A segment end whose stop footprint reaches the cut is no whole-segment target: a hold point on it instead.
    target_end, cut_seg = footprint_end(runner, live, index, target_end)
    names = _blockers(live)
    if live.active_route is not None:
        if (live.active_route.get("wait_prefix") and not live.active_route.get("superseded")
                and await supervise_wait_prefix(runner, live, active, nav, state, pose, cut_seg,
                                                lambda: _cancel_active_route(runner, live, robot_id, nav))):
            return
        if (runner.config.map_binding_required or live.nav2_binding_scope is not None
                or (live.view["detail"].get("goal_frame") or {}).get("binding_id") is not None):
            await recheck_binding(runner, live, active)
            if not live.open or live.view["detail"].get("localization_wait"):
                return
        if nav is not None and live.active_route is not None:
            live.active_route["nav_state"] = nav
        if live.active_route is not None and await observe_lane_departure(runner, live, index, pose, state, nav):
            live.active_route = {**live.active_route, "superseded": True}  # D-1080: cancel, ack, resend from here
        verdict = _route_finished(runner, live, index, s, nav, target_end=target_end, pose=pose)
        if verdict == "aborted":
            if nav == "FAILED" and await _start_camera_finish(runner, live, index, s, active):
                return
            if nav == "FAILED" and robot_id in runner.autonomous_robots:
                await _handle_nav2_failure(runner, live, index, s, pose, active)
                return
            await runner._stop(live, "stopped", "navigation", {"navigation": nav})
            return
        if live.active_route and (live.active_route.get("superseded") or (
                not live.active_route.get("hold_point")  # a covered hold point runs on under the cut
                and (target_end is None or live.active_route["end_index"] > target_end))):
            was_hold = bool(live.active_route.get("hold_point"))
            await _cancel_active_route(runner, live, robot_id, nav)
            if not live.open:
                return
            if was_hold or target_end is None:  # never a replacement in the cancel's own period
                fence(live, index if cut_seg is None else cut_seg, names)
                if cut_seg is not None:
                    traffic_hold(live, names)
                return
        elif verdict == "busy":
            if live.active_route.get("road_speed_owner") and nav in _NAV_RUNNING:
                await runner.road_speed.renew(runner, live, active, index, s, pose)
            return
    hold_s = None
    if cut_seg is not None:
        traffic_hold(live, names)
        if live.view["hold"] is None:
            hold_s = hold_or_wait(runner, live, active, index, s, cut_seg, names)
        if hold_s is None and target_end is None:
            return
    if hold_s is None:
        live.view["detail"].pop("traffic_hold", None)
    if fenced(live, state, nav):
        return
    now = runner._clock()
    if now < live.nav2_retry_at:
        demand = getattr(runner, "road_vision_demand", None)
        observed = demand.new_peer_observations(live, active[1].map_id, now) if demand and live.active_route is None else None
        if not observed:
            return
        (live.view["detail"].get("peer_wait") or {})["observation_retry"] = observed  # a hold point retries without one
    if (target_end == index and target_end < len(live.segments) - 1
            and live.segments[index]["s_to"] - s <= runner.config.arrive_free_m and live.view["hold"] is None):
        traffic_hold(live, names)
        return
    if not await ready_free_goal(runner, live) or not live.open:
        return
    end_index = target_end
    detail = live.view["detail"]
    wait = detail.get("peer_wait") or {}
    prefix = None
    if hold_s is not None:
        end_index = cut_seg
    elif wait.pop("try_wait_place", False):
        prefix, why = reserved_wait(runner, live, active, index, s, target_end)
        if prefix is None:
            detail["wait_prefix"] = {"state": "held", "reason": why, "waiting_on": wait["waiting_on"]}
    if prefix is not None:
        end_index = prefix
    site_pts = sample_nav2_route(live.graph, live.segments, index, s, end_index, walls=getattr(active[1], "walls", ()),
                                 here=(pose.x, pose.y), end_s=hold_s)
    robot_pts, frame_err = _convert_points(runner, live, active, site_pts, pose, state)
    if robot_pts is None:
        if (frame_err or {}).get("binding") == "ROBOT_NOT_LOCALIZED":
            diag = loc_diag_from_state(state, runner._store.map_bindings.active(robot_id))
            if await hold_transient_localization(runner, live, robot_id, diag):
                return
        await runner._stop(live, "stopped", "map_frame", frame_err)
        return
    payload = [
        {"x": round(rx, 4), "y": round(ry, 4), "kind": kind, **({"yaw": round(ryaw, 4)} if kind == "stop" else {})}
        for rx, ry, ryaw, kind in robot_pts
    ]
    options = {}
    if (answer := _table_answer(runner, live)) is not None:
        options["table_peers"] = answer["peers"]
    controlled = getattr(runner, "road_speed", None) is not None and (
        prefix is not None or hold_s is not None or live.nav2_binding_scope is not None or runner.config.map_binding_required
        or runner._store.rules.active_rules() is not None)
    if controlled:
        if runner._route is None:
            raise _GoalRefused("ROAD_SPEED_AUTHORITY_UNAVAILABLE")
        options["road_speed_controlled"] = True
    if live.nav2_binding_scope is not None:
        if runner._route is None:
            raise _GoalRefused("BOUND_NAV2_ROUTE_UNAVAILABLE")
        frame = live.view["detail"]["goal_frame"]
        options["route_binding"] = {"site_map_id": frame["map_id"], "site_map_version": frame["map_version"],
                                    "map_grid_id": frame["map_grid_id"], "binding_id": frame["binding_id"]}
        if hold_s is None and runner._strict_named_stop(live, end_index) is not None:  # a hold point is no named stop
            options["attempt_id"] = str(uuid4())
            record_stop_dispatch(runner, live, active, options["attempt_id"], site_pts[-1][:3], robot_pts[-1][:3])
    scope = None
    if prefix is not None:
        revision = live.route_rev
        def reserved():
            return (live.route_rev == revision and live.at is not None
                    and reserved_wait(runner, live, active, *live.at, target_end)[0] == prefix)
        centerline = road_centerline(live, index, s, prefix)
        expected = [centerline[0], *(point[:2] for point in site_pts)]
        scope = prefix_guard.set((robot_id, active[1].map_id, set(wait["waiting_on"]), reserved, expected, centerline))
    elif hold_s is not None:
        scope = hold_guard(runner, live, active, index, s, cut_seg, hold_s, site_pts, names)
    try:
        if runner._route is not None:
            reply = await runner._call(runner._route(robot_id, payload, **options)) or {}
        else:
            fx, fy, fyaw, _ = robot_pts[-1]
            reply = await runner._call(runner._goal(robot_id, fx, fy, fyaw)) or {}
    except RoadSpeedRefused as exc:
        raise TripError(409, exc.code) from exc
    except RobotApiError as exc:
        if exc.code == "NAVIGATION_ACTIVE":
            live.view["detail"]["goal_wait"] = exc.message
            return
        raise
    finally:
        if scope is not None:
            prefix_guard.reset(scope)
    await runner._after_send(live)
    if not live.open:
        return
    if reply.get("accepted") is False or reply.get("queued"):
        reason = reply.get("reason") or ""
        if prefix is not None and reason == "WAIT_PREFIX_UNVERIFIED":
            detail["wait_prefix"] = {"place": live.place(prefix), "state": "held", "reason": reason}
            live.nav2_retry_at = runner._clock() + NAV2_TRANSIENT_RETRY_S
            return
        if hold_s is not None and reason == "WAIT_PREFIX_UNVERIFIED":
            detail["wait_prefix"] = held_receipt(cut_seg, reason, names)
            live.nav2_retry_at = runner._clock() + NAV2_TRANSIENT_RETRY_S
            return
        peer_wait = (reply.get("blocked_by") not in (None, robot_id)
                       and reply.get("queued") is False
                       and (reply.get("dispatch_attempted") is False or reply.get("cancel_confirmed") is True)
                       and reason in ("LOCALIZATION_UNTRUSTED", "ROUTE_CONFLICT", "YIELDING", "MAP_FRAME_MISMATCH"))
        if peer_wait or (robot_id in runner.autonomous_robots and reason in _TRANSIENT_GOAL_REFUSALS):
            if peer_wait:
                detail = live.view["detail"]
                proof = _GoalRefused(reason, reply).detail["goal_admission"]
                prior = detail.get("peer_wait") or {}
                detail["peer_wait"] = {**proof, "since": prior.get("since", runner._clock()),
                                       "checked_at": runner._clock(), "reason": reason}
                if prior.get("observation_retry"):
                    detail["last_peer_observation_retry"] = prior["observation_retry"]
                if prefix is None and hold_s is None and downstream_refusal(reply, robot_id):
                    detail["peer_wait"]["try_wait_place"] = True
                elif prefix is not None:
                    detail["wait_prefix"] = {"place": live.place(prefix), "state": "held", "reason": reason}
                elif hold_s is not None:
                    detail["wait_prefix"] = held_receipt(cut_seg, reason, names)
            live.active_route = None
            live.nav2_retry_at = runner._clock() + NAV2_TRANSIENT_RETRY_S
            live.view["detail"]["goal_wait"] = reason
            runner._fence(robot_id)
            if peer_wait and reply.get("stage") == "pre_dispatch_peer_check" and reply.get("dispatch_attempted") is False:
                await inspect_held_route(runner, live, state, payload)
            return
        raise _GoalRefused(reason, reply)
    if wait := detail.pop("peer_wait", None):
        live.progress_at = runner._clock()
        if prefix is not None:
            detail["wait_prefix"] = {"place": live.place(prefix), "end_index": prefix, "state": "dispatched",
                                     "waiting_on": wait.get("waiting_on"), "at": live.progress_at}
            detail.pop("named_stop_dispatch", None)
        else:
            detail["last_peer_wait"] = {**wait, "cleared_at": live.progress_at}
    if hold_s is not None:  # the receipt of every accepted hold-point send
        hold_receipt(runner, live, cut_seg, hold_s, site_pts[-1][:2], names)
    if "attempt_id" in options:
        record_stop_operation(live, options["attempt_id"], reply)
    live.command_ack_mono = time.monotonic()
    live.active_route = {"end_index": end_index, "points": len(payload),
                         **({"nav_state": "NAVIGATING"} if state is not None else {})}
    if prefix is not None or hold_s is not None:
        live.active_route["wait_prefix"] = True
        if hold_s is not None:
            live.active_route["hold_point"] = {"segment": cut_seg, "end_s": hold_s}
    elif detail.get("wait_prefix"):
        detail["wait_prefix"]["state"] = "superseded"
    if "attempt_id" in options:
        live.active_route["attempt_id"] = options["attempt_id"]
    if controlled:
        owner = reply.get("road_speed_owner")
        if not owner:
            await runner._stop(live, "stopped", "ROAD_SPEED_OWNER_MISSING")
            return
        live.active_route["road_speed_owner"] = owner
        await runner.road_speed.renew(runner, live, active, index, s, pose)
    live.nav2_retry_at = -math.inf
    live.view["detail"].pop("goal_wait", None)
    live.view["detail"]["nav2_route"] = {"points": len(payload), "end_index": end_index, "lap": live.view.get("lap")}
    runner._fence(robot_id)  # Ensure the next tick reads post-dispatch robot state, never pre-POST ARRIVED.

