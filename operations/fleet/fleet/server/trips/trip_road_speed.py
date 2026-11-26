"""Short-lived Nav2 speed grants from the route profile and supervised robot positions."""
from __future__ import annotations

from bisect import bisect_right
import math

from core_common.protocol.evidence import STALE_POSE_S
from fleet.lane_progress import MIN_GAP_M, ON_LOOP_M, follower_speed
from fleet.server.platoon_geometry import PlatoonGeometry
from fleet.server.road_route_lease import RoadSpeedRefused
from fleet.server.trip_ports import TripError
from fleet.speed_table import speed_table
from rosy.world.state.projections.map_pose_samples import parse_utc

GRANT_S = 1.5


async def _goal_finished(runner, rid) -> bool:
    """A lease 409 is a normal arrival only when CORE itself reports the goal done: ARRIVED, no goal,
    no e-stop, zero fresh velocity. Anything else (failed, cancelled, replaced, unknown) stays a stop."""
    if getattr(runner, "_robot_state", None) is None:
        return False
    try:
        state = await runner._call(runner._robot_state(rid))
    except Exception:
        return False
    if not isinstance(state, dict) or state.get("navigation") != "ARRIVED" or state.get("goal") is not None:
        return False
    evidence = (state.get("evidence") or {}).get("velocity") or {}
    stamp = parse_utc(evidence.get("sampled_at"))
    vel = state.get("velocity") or {}
    return (evidence.get("evidence") == "fresh" and stamp is not None and 0 <= runner._clock() - stamp < STALE_POSE_S
            and (state.get("safety") or {}).get("estop") is False
            and all(type(vel.get(a)) in (int, float) and math.isfinite(vel[a]) for a in ("linear", "angular"))
            and abs(vel["linear"]) <= 0.01 and abs(vel["angular"]) <= 0.02)


class RoadSpeed:
    def __init__(self, poses, update):
        self.geometry = PlatoonGeometry()
        self.poses = poses
        self.update = update

    async def renew(self, runner, live, active, index, s, pose):
        route = live.active_route
        rid = live.view["robot_id"]
        owner = route["road_speed_owner"]
        now = runner._clock()
        site = active[1]
        key = (active[0], live.route_rev, live.trim_m, len(live.segments))
        if getattr(live, "road_profile_key", None) != key:
            segs = [(row["edge_id"], row["forward"], row["s_from"], row["s_to"]) for row in live.segments]
            # Nav2 owns the acceleration from rest and the final pose controller.
            table = speed_table(site, segs, start_mps=math.inf, stop_at_end=False)
            live.road_profile = table["rows"]
            live.road_profile_key = key
        rows = live.road_profile
        limits = runner._store.rules.active_rules()
        formation = limits.formation if limits is not None else None
        max_speed = getattr(formation, "max_speed_mps", None)
        cap = max((v for _, v in rows), default=0.0)
        if max_speed is not None:
            cap = min(cap, max_speed)
        progress = live.progress(index, s)
        # A grant covers every profile change the robot could reach before expiry.
        end = progress + GRANT_S * cap
        lo = max(0, bisect_right(rows, [progress, math.inf]) - 1)
        for distance, speed in rows[lo:]:
            if distance > end:
                break
            cap = min(cap, speed)
        stamp = pose.odom_stamp
        reason = "route_profile"
        leader = None
        gap_m = None
        geometry = await self.geometry.get(active)
        if geometry:
            _, loop, _ = geometry
            pos, off = loop.project(pose.x, pose.y)
            if off <= ON_LOOP_M:
                for robot in runner._roster():
                    if robot == rid:
                        continue
                    pending = runner._live.get(robot)
                    native = getattr(pending, "road_pose", None)
                    if (pending is not None and pending.open and native is not None
                            and native.source == "approved_slam" and native.state == "LOCALIZED"
                            and native.map_id == site.map_id and native.odom_stamp is not None
                            and 0.0 <= now - native.odom_stamp < GRANT_S):
                        peer = native
                    else:
                        peer = self.poses.arbitrated_pose(robot)
                    if (peer is None or peer.state != "LOCALIZED" or peer.map_id != site.map_id
                            or peer.odom_stamp is None or not 0 <= now - peer.odom_stamp < GRANT_S):
                        if (peer is not None and peer.state == "LOCALIZED" and peer.map_id == site.map_id
                                and peer.odom_stamp is not None and 0 <= now - peer.odom_stamp
                                and loop.project(peer.x, peer.y)[1] - ON_LOOP_M > 0.25 * (now - peer.odom_stamp)):
                            continue
                        if pending is not None and pending.open:
                            cap, reason, leader, gap_m = 0.0, "peer_pose_stale", robot, None
                        continue
                    ahead, away = loop.project(peer.x, peer.y)
                    if away > ON_LOOP_M:
                        continue
                    stamp = min(stamp, peer.odom_stamp) if stamp is not None else None
                    gap = loop.gap(ahead, pos)
                    minimum = getattr(formation, "min_gap_m", None) or MIN_GAP_M
                    # No observed forward velocity is promised by a parked or braking leader.
                    allowed = min(follower_speed(0.0, gap, cap, target=minimum),
                                  max(0.0, (gap - minimum) / GRANT_S))
                    if allowed < cap:
                        cap, reason, leader, gap_m = allowed, "leader_gap", robot, gap
        now = runner._clock()
        expires_at = min(now + GRANT_S, stamp + GRANT_S) if stamp is not None else now
        if (expires_at <= now or pose.state != "LOCALIZED" or pose.map_id != site.map_id
                or not isinstance(pose.odom_stamp, (int, float))
                or not 0.0 <= now - pose.odom_stamp < GRANT_S):
            cap, reason, expires_at = 0.0, "pose_stale", now + GRANT_S
        if not live.open or live.active_route is not route or runner._store.active() != active:
            return
        grant = {"issued_at": now, "expires_at": expires_at, "limit_mps": cap}
        detail = {"state": "requested", **grant, "reason": reason, "owner": owner,
                  "leader": leader, "gap_m": gap_m}
        live.view["detail"]["road_speed"] = detail
        try:
            reply = await runner._call(self.update(rid, owner, grant))
            if not isinstance(reply, dict) or reply.get("renewed") is not True or reply.get("correlation_id") != owner:
                raise TripError(409, "ROAD_SPEED_ACK_UNCONFIRMED")
        except Exception as exc:
            if (getattr(exc, "status", None) == 409
                    and getattr(exc, "code", None) in ("GOAL_LEASE_NOT_ACTIVE", "ROAD_SPEED_OWNER_CHANGED")
                    and live.open and live.active_route is route and await _goal_finished(runner, rid)):
                detail["state"] = "arrived"  # reached the target before the first renewal; the step loop sees ARRIVED
                return
            detail.update(state="unconfirmed", error=getattr(exc, "code", type(exc).__name__))
            if isinstance(exc, RoadSpeedRefused):
                raise TripError(409, exc.code) from exc
            raise
        detail["state"] = "acknowledged"
