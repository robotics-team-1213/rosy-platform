"""Read a stopped mover's native scan for an axis-aligned part of its refused route."""
import asyncio
import math

import httpx

from fleet.server.handoff_traffic import _fresh_stopped
from fleet.server.named_stop_map_pose import fresh_native_slam
from fleet.swarm.transport import RobotApiError


def _request(state, points, now):
    slam = fresh_native_slam(state, now)
    if slam is None or state.get("navigation") not in {"IDLE", "ARRIVED"} or not _fresh_stopped(state):
        return None, "stopped_map_pose_unverified"
    if not points:
        return None, "no_route_point"
    x, y, yaw = slam[0]
    dx, dy = points[0]["x"] - x, points[0]["y"] - y
    longitudinal = dx * math.cos(yaw) + dy * math.sin(yaw)
    lateral = -dx * math.sin(yaw) + dy * math.cos(yaw)
    # Route points are written to 0.1 mm. Exclude any distinct lateral component.
    if not math.isfinite(longitudinal) or not math.isfinite(lateral) or abs(lateral) > .0001:
        return None, "first_leg_not_body_aligned"
    distance = math.floor(min(.03, abs(longitudinal)) * 10000) / 10000
    if distance <= 0:
        return None, "no_straight_translation"
    return {"direction": "forward" if longitudinal > 0 else "reverse", "distance_m": distance}, None


def _assessment(row, robot, requested, now):
    if not isinstance(row, dict) or (row.get("kind"), row.get("robot_id"), row.get("direction"),
            row.get("distance_m")) != ("native_lidar_straight_corridor_v1", robot, requested["direction"], requested["distance_m"]):
        return {"status": "unknown", "reason": "response_scope_mismatch"}
    status, reason = row.get("status"), row.get("reason")
    required, observed = row.get("required_beams"), row.get("observed_beams")
    if (type(required) is not int or type(observed) is not int or not 0 <= observed <= required
            or type(row.get("checked_at")) not in (int, float) or not math.isfinite(row["checked_at"])):
        return {"status": "unknown", "reason": "invalid_scan_evidence"}
    if status in {"observed_clear", "blocked"}:
        received = row.get("received_at")
        if (row.get("frame_id") not in {"rplidar_link", f"{robot}/rplidar_link"}
                or type(row.get("source_stamp_ns")) is not int or row["source_stamp_ns"] <= 0
                or type(received) not in (int, float) or not 0 <= now - received <= .5
                or not received <= row["checked_at"] <= now
                or status == "observed_clear" and (reason != "required_sector_observed" or not required or observed != required)
                or status == "blocked" and reason != "obstacle_in_corridor"):
            return {"status": "unknown", "reason": "invalid_scan_evidence"}
    elif status != "unknown" or not isinstance(reason, str):
        return {"status": "unknown", "reason": "invalid_scan_evidence"}
    return {k: row.get(k) for k in ("status", "reason", "frame_id", "source_stamp_ns", "checked_at",
                                     "received_at", "required_beams", "observed_beams")}


async def inspect_held_route(runner, live, state, points):
    reader = getattr(runner, "read_held_lidar", None)
    if reader is None:
        return
    now = runner._clock()
    detail = live.view["detail"]
    prior = detail.get("held_lidar_observation") or {}
    if prior.get("route_rev") == live.route_rev and now - prior["requested_at"] < 5:
        return
    robot = live.view["robot_id"]
    receipt = {"requested_at": now, "route_rev": live.route_rev, "map_version": live.view["map_version"],
               "robot_id": robot, "scope": "body_axis_scan_only", "trip_id": live.view["trip_id"]}
    request, reason = _request(state, points, now)
    if request is None:
        receipt.update(status="unknown", reason=reason)
    else:
        receipt.update(request)
        receipt.update(native_map_id=state.get("map_id"), native_grid_id=state.get("map_grid_id"),
                       start={k: state["pose"][k] for k in ("x", "y", "yaw")},
                       first_waypoint={k: points[0][k] for k in ("x", "y")})
        try:
            row = await asyncio.wait_for(reader(robot, request), timeout=.4)
        except RobotApiError as exc:
            receipt.update(status="unknown", reason="unsupported" if exc.status == 404 else "read_failed")
        except (TimeoutError, OSError, httpx.HTTPError, RuntimeError, ValueError, KeyError):
            receipt.update(status="unknown", reason="read_failed")
        else:
            receipt.update(_assessment(row, robot, request, runner._clock()))
    if live.open and live.route_rev == receipt["route_rev"] and detail.get("peer_wait"):
        detail["held_lidar_observation"] = receipt
