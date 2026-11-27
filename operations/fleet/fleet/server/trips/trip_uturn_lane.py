"""U-turn Nav2-to-camera-lane handoff, stationary verification, and step hold helpers."""

from __future__ import annotations

import asyncio
from contextlib import nullcontext
import math
import time

import httpx

from core_common.protocol.evidence import STALE_POSE_S
from core_common.robot_body import nominal_body_for
from fleet.hub.hub import HubError
from fleet.routing.execute import uturn_lane_index
from fleet.server.named_stop_confirm import GoalRefused
from fleet.server.named_stop_map_pose import precision_line_fence, precision_map_pose
from fleet.server.trip_halts import error_code as _code
from fleet.server.trip_live import LiveTrip
from fleet.server.trip_ports import TripError
from fleet.server.trip_runner_helpers import _ROBOT_ERRORS, _caps_view
from fleet.server.trip_start_checks import start_check
from fleet.swarm.dispatch_guard import dispatch_guard
from fleet.swarm.transport import RobotApiError
from rosy.world.state.projections.map_pose_samples import parse_utc


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


async def start_camera_line(runner, live: LiveTrip) -> None:
    """D-601 A: turn CORE's camera line on; a refusal ends the trip failed unless in uturn handoff."""
    robot_id = live.view["robot_id"]
    fence = nullcontext()
    if live.view["detail"].get("precision_binding_id"):
        pose = await runner._progress_pose(live, robot_id)
        if pose is None:
            detail = {"reason": "APPROVED_SLAM_POSE_REQUIRED"}
            if not live.view["detail"].get("uturn_handoff"):
                await runner._stop(live, "failed", "TRIP_POSE_UNTRUSTED", detail)
            raise TripError(409, "TRIP_POSE_UNTRUSTED", detail)
        geometry = start_check(live.graph, live.segments[live.view["segment_index"]:], pose.x, pose.y, pose.yaw,
                               runner.config.start_heading_tol_deg)
        if geometry["code"]:
            if not live.view["detail"].get("uturn_handoff"):
                await runner._stop(live, "failed", geometry["code"], geometry)
            raise TripError(409, geometry["code"], geometry)
        check = precision_line_fence(runner, live, pose)
        fence = dispatch_guard(check, paths={"/api/v1/line-follow/mode"})
    try:
        with fence:
            if live.view["detail"].get("precision_binding_id"):
                check()
            await runner._call(runner._junction.start_camera_line(robot_id))
    except _ROBOT_ERRORS as exc:
        detail = {"error": _code(exc), "status": getattr(exc, "status", None)}
        if not live.view["detail"].get("uturn_handoff"):
            await runner._stop(live, "failed", "TRIP_LINE_FOLLOW_START_FAILED", detail)
        if detail["status"] is None:  # review M: a timed-out PUT may still land after our OFF
            await asyncio.sleep(runner.config.port_timeout_s)
            live.view["detail"].update(await runner._halt(live))
            runner._save(live)
        raise TripError(409, "TRIP_LINE_FOLLOW_START_FAILED", detail) from exc
    live.command_ack_mono = time.monotonic()
    live.view["detail"]["line_follow_started"] = True
    await runner._after_send(live)  # a cancel or E-stop that landed meanwhile stops it again
    runner._save(live)


async def recheck_uturn_start(runner, robot_id: str, graph, plan: dict, repeat: bool, notes: dict,
                              nav2: bool, cusp: int | None, nav2_scope, start_token, start_guard,
                              caps, caps_view: dict):
    final_cusp = uturn_lane_index(graph, plan["segments"], runner._routing)
    if final_cusp is not None and final_cusp != cusp:
        caps = await runner._caps_checks(robot_id, graph, plan["segments"], repeat,
                                         plan["actions"][-1]["place_id"], detail=notes, nav2=nav2)
        await runner._guard_start(robot_id, start_token, start_guard)
        graph = runner._graph_for(plan["map_version"])
        if nav2_scope and (runner._store.map_bindings.active(robot_id) or {}).get("binding_id") != nav2_scope[1]:
            raise TripError(409, "TRIP_POSE_UNTRUSTED", {"reason": "APPROVED_SLAM_POSE_REQUIRED"})
        caps_view = _caps_view(caps)
        notes["uturn_handoff"] = {"index": final_cusp, "phase": "approaching"}
    return graph, caps, caps_view


async def start_uturn_lane(runner, live, index: int) -> None:
    """Re-admit the remaining camera road only after native standstill; never fall back to Nav2."""
    rid, detail = live.view["robot_id"], live.view["detail"]
    suffix = live.segments[index:]
    caps = await runner._caps_checks(rid, live.graph, suffix, live.repeat,
                                     live.view["plan"]["actions"][-1]["place_id"])
    cue = runner.lane_cue_refusal
    bounded = caps.line_follow_authority_required or (
        runner.lease.required and getattr(caps, "line_follow_authority_under_lease", False))
    if runner.authority.mode(caps) != "core" or not bounded:
        raise TripError(409, "TRIP_AUTHORITY_NOT_REQUIRED")
    if runner.named_stop_state is None:
        raise TripError(409, "TRIP_CAMERA_FALLBACK_STOP_UNCONFIRMED")
    deadline = await _camera_stationary(runner, live, runner._clock())
    if deadline is None:
        raise TripError(409, "TRIP_CAMERA_FALLBACK_STOP_UNCONFIRMED")
    probe = runner.lane_cue_check
    refusal = await runner._call(probe(rid)) if probe else "unknown"
    if refusal == "pending":
        return  # stay stopped while the monitor retries the cue within its failure bound
    if refusal or cue is None:
        raise TripError(409, "TRIP_MODE_UNSUPPORTED", {"reason": refusal or "unknown"})
    camera = await runner._call(runner._junction.front_camera(rid)) or {}
    observed, age = runner._clock(), camera.get("age_ms")
    if (camera.get("available") is not True or camera.get("stale") is not False
            or type(age) not in (int, float) or not 0 <= age < 1000):
        raise TripError(409, "TRIP_LANE_CAMERA_UNAVAILABLE")
    binding_id = detail.get("precision_binding_id") or detail.get("nav2_binding_id")
    scope = (live.view["map_version"], binding_id) if binding_id else None
    pose = (await precision_map_pose(runner, rid, scope) if scope else await runner.map_pose(rid))
    if (pose is None or pose.state != "LOCALIZED" or not camera_body_inside(live, index, pose)
            or start_check(live.graph, suffix, pose.x, pose.y, pose.yaw,
                           runner.config.start_heading_tol_deg)["code"]):
        raise TripError(409, "TRIP_CAMERA_FALLBACK_POSE_UNTRUSTED")
    pose_stamp = runner._clock() - pose.age_s
    version = live.view["map_version"]

    def check():
        runner._check_human_hold()
        now = runner._clock()
        active = runner._store.active()
        binding = runner._store.map_bindings.active(rid) or {}
        refusal = cue(rid)
        if refusal == "pending":
            detail["uturn_handoff"]["phase"] = "approaching"
            raise TripError(409, "TRIP_CAMERA_FALLBACK_ADMISSION_CHANGED")
        if (not live.open or live.view["hold"] is not None or runner.traffic.holds(live, index)
                or active is None or active[0] != version or now >= deadline
                or binding_id and binding.get("binding_id") != binding_id
                or not 0 <= now - pose_stamp < STALE_POSE_S
                or pose.odom_stamp is None or not 0 <= now - pose.odom_stamp < STALE_POSE_S
                or not 0 <= now - observed < 1. - age / 1000 or refusal):
            raise TripError(409, "TRIP_CAMERA_FALLBACK_ADMISSION_CHANGED")

    detail["uturn_handoff"]["phase"] = "starting"
    live.view["segment_index"] = index
    live.active_route, live.last_goal, live.sent = None, None, None
    live.first_seq = live.arc_base = live.replaceable = None
    live.junction = {}
    live.at, live.at_stamp = None, None
    live.request.pop("drive_mode", None)
    detail["line_follow_started"] = False
    runner._describe(live)
    runner._save(live)  # ambiguous PUT/restart must stop both possible owners
    with dispatch_guard(check, paths={"/api/v1/line-follow/mode"}):
        check()
        await runner._start_line(live)
    if live.open:
        detail["uturn_handoff"]["phase"] = "running"
        live.view["traffic_authority"] = "core"
        runner._describe(live)
        runner._save(live)


async def uturn_handoff_or_hold(runner, live, index: int) -> None:
    """Refused or ambiguous handoffs keep the existing operator-resumable hold."""
    try:
        if runner.traffic.holds(live, index):
            return
        if live.arc(index).drive_mode == "lane":
            await start_uturn_lane(runner, live, index)
        else:
            if runner.named_stop_state is None or await _camera_stationary(runner, live, runner._clock()) is None:
                raise TripError(409, "TRIP_CAMERA_FALLBACK_STOP_UNCONFIRMED")
            if not live.open:
                return
            live.request.pop("drive_mode", None)
            live.view["segment_index"] = index
            live.active_route = live.last_goal = None
            live.at, live.at_stamp = None, None
            live.view["detail"]["uturn_handoff"]["phase"] = "running"
            runner._describe(live)
            runner._save(live)
    except (TripError, *_ROBOT_ERRORS) as exc:
        if getattr(exc, "code", None) == "TRIP_LANE_CUE_PENDING":
            return
        if not live.open:
            return
        await hold_uturn_lane(runner, live, exc)


async def hold_uturn_lane(runner, live, exc) -> None:
    code = getattr(exc, "code", None) or type(exc).__name__
    live.view["hold"] = {"reason": "fleet_hold", "plan": None, "code": code,
                         "detail": getattr(exc, "detail", {}), "at": runner._clock(),
                         "stop": {"confirmed": False}}
    runner._save(live)
    await runner._check_pause(live)
    runner._describe(live)
    runner._save(live)


async def check_camera_fallback(runner, live: LiveTrip, index: int, lane: bool, pose) -> bool:
    camera = live.view["detail"].get("camera_lane_fallback")
    if not camera:
        return False
    if live.view["hold"] is not None:
        await runner._stop(live, "stopped", "TRIP_CAMERA_FALLBACK_HELD")
        return True
    if not camera_body_inside(live, index, pose):
        await runner._stop(live, "stopped", "TRIP_CAMERA_FALLBACK_BODY_OUTSIDE_LANE")
        return True
    if not lane or runner._clock() - camera["started_at"] > 2 * runner.config.stall_s:
        await runner._stop(live, "stopped", "TRIP_CAMERA_FALLBACK_TIMEOUT")
        return True
    return False


def check_uturn_lane_cue(runner, live: LiveTrip) -> bool:
    if not live.view["detail"].get("uturn_handoff"):
        return False
    robot_id = live.view["robot_id"]
    refusal = runner.lane_cue_refusal(robot_id) if runner.lane_cue_refusal else "unknown"
    if refusal == "pending":
        runner._save(live)
        return True  # no new instruction without fresh support; CORE's cue/authority still expire
    if refusal:
        raise TripError(409, "TRIP_MODE_UNSUPPORTED", {"reason": refusal})
    return False


async def step_free_uturn_handoff(runner, live: LiveTrip, index: int, remaining: float, pose) -> bool:
    if not (live.view["detail"].get("uturn_handoff") and index + 1 < len(live.segments)
            and live.segment_is_lane(index + 1) and live.last_goal is not None
            and runner._arrived(live, index, remaining, False, pose)):
        return False
    state = await runner._call(runner.named_stop_state(live.view["robot_id"]))
    if state.get("navigation") == "ARRIVED":
        live.view["detail"]["uturn_handoff"]["stopped_index"] = index
        await uturn_handoff_or_hold(runner, live, index + 1)
    return True


def uturn_free_goal(live: LiveTrip, index: int) -> tuple[float, float, float]:
    x, y, yaw = live.arc(index).point_at(live.segments[index]["s_to"])
    if (live.view["detail"].get("uturn_handoff") and index + 1 < len(live.segments)
            and live.segment_is_lane(index + 1)):
        yaw = live.arc(index + 1).start_tangent
    return x, y, yaw


async def handle_step_error(runner, live: LiveTrip, exc: Exception) -> None:
    if isinstance(exc, GoalRefused):
        if (live.view["detail"].get("uturn_handoff") or {}).get("phase") == "approaching":
            await hold_uturn_lane(runner, live, TripError(409, "TRIP_GOAL_REFUSED", exc.detail))
            return
        await runner._stop(live, "failed", "TRIP_GOAL_REFUSED", exc.detail)
        return
    if isinstance(exc, TripError):
        if live.open and live.view["detail"].get("uturn_handoff"):
            await hold_uturn_lane(runner, live, exc)
            return
        await runner._stop(live, "failed", exc.code, exc.detail)
        return
    if isinstance(exc, RobotApiError):
        if exc.status == 429 and await runner._link_wait(live, "rate_limited"):
            return
        lane = live.segment_is_lane(live.view["segment_index"])
        code = "TRIP_ROBOT_JUNCTION_UNSUPPORTED" if lane and exc.status == 404 else exc.code
        handoff = live.view["detail"].get("uturn_handoff") or {}
        if live.open and handoff and (lane or handoff.get("phase") == "approaching"):
            await hold_uturn_lane(runner, live, TripError(exc.status, code, {"status": exc.status}))
            return
        await runner._stop(live, "failed", code, {"status": exc.status})
        return
    if live.open and (live.view["detail"].get("uturn_handoff") or {}).get("phase") == "approaching":
        await hold_uturn_lane(runner, live, TripError(409, "TRIP_ROBOT_UNREACHABLE", {"kind": _code(exc)}))
        return
    # D-760 4: a leased trip waits only on no answer (Safety-Review HIGH-1); any other error ends it
    if not (isinstance(exc, (HubError, OSError, httpx.TransportError)) and await runner._link_wait(live, _code(exc))):
        await runner._stop(live, "failed", "TRIP_ROBOT_UNREACHABLE", {"kind": _code(exc)})


async def stop_or_hold_stalled(runner, live: LiveTrip) -> None:
    if (live.view["detail"].get("uturn_handoff") or {}).get("phase") == "approaching":
        await hold_uturn_lane(runner, live, TripError(409, "TRIP_STALL", {"stall_s": runner.config.stall_s}))
        return
    await runner._stop(live, "stopped", "stall", {"stall_s": runner.config.stall_s,
                                                  "progress_m": round(live.best_progress, 3)})
