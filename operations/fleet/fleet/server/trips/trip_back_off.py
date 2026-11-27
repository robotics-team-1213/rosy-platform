"""D-1087: before a same-spot failure is sent again, the robot backs off once along its own rear and looks again.

User 2026-11-28 ("그렇게 주행해도 돼. 후진하고 보는 것도 더 고민해서 해 봐"). A D-1082 episode that ran out with
``recovery.same_spot`` (three or more stops with one reason within 0.05 m) would fail the same way if D-1086 resent it
as it stands, so D-1086 does not. This is the one change of condition left that the robot can make by itself: back off
BACK_OFF_M along its rear, look again, then reissue with the first leg slowed and recentred (``detail['first_leg']``,
read by nav2_recovery_ladder). It is the first path where Fleet itself backs a robot.

Why here and not inside the trip: CORE's ``nudge_backward`` (``POST /localization/mission``) takes NAVIGATION from
IDLE, and a robot whose trip lease is open stays in NAVIGATION after a cancel. Between D-1086's end and its reissue the
trip is closed and the robot is IDLE, so the back-off meets no lease or mode.

The step is the console's own reviewed one (``nudge_routes.request_step``: busy robot and other trips refuse it, cable
inhibit, the traffic hold for the mover), and CORE keeps every guard of its own (rear strip, stop gap, a beam without a
return refuses; the mission ends on its own distance and time, on an obstacle, E-stop or stale sensors). Fleet adds what
it alone knows (``refusal``): no other robot unknown or within PEER_CLEAR_M, not on a charge-bay edge, parking
handoff, DOCKING, precision stop, crosswalk or signal zone, and room behind inside the lane on the same edge or a
straight predecessor. A refused or unread step never reissues (the same-spot failure stands).
"""
from __future__ import annotations

import inspect
import math

from fleet.localization.lane_compliance import BODY_HALF_WIDTH_M, lane_offset
from fleet.routing.execute import arc_id
from fleet.server.trip_lane_realign import (CAMERA_BRIDGE_MAX_M, CAMERA_MAX_AGE_S, CAMERA_SOURCES, GAP_MAX_M,
                                            _excluded)
from fleet.server.trip_start_checks import crosswalks_on, signals_on

BACK_OFF_M = 0.08
MAX_BACK_OFFS = 2
MAX_TOTAL_M = 0.16            # below stuck's lane_lost reverse cap 0.20 m
PEER_CLEAR_M = 0.50           # another robot this close (or not placed) means no back-off
PEER_FRESH_S = 1.5
CONTINUITY_DEG = 10.0         # a predecessor edge that joins at most this bent counts as room behind
STEP_SPEED_MPS = 0.03         # CORE nudge_linear (nudge_routes.NUDGE_LINEAR_MPS)
STEP_SPARE_S = 10.0           # past distance / speed + this, an unread end is "unconfirmed"
FIRST_LEG_M = 1.0             # the reissued trip's slow, recentred start: D-1082's RESET_M, past the failed spot


async def _pose(runner, robot_id):
    try:
        pose = runner._poses.arbitrated_pose(robot_id)
        return await pose if inspect.isawaitable(pose) else pose
    except Exception:  # noqa: BLE001 - an unread pose is no pose
        return None


def _room(live, index: int, x: float, y: float, yaw: float) -> bool:
    """The rear point BACK_OFF_M behind lies inside the lane of this edge or of a straight predecessor."""
    bx, by = x - BACK_OFF_M * math.cos(yaw), y - BACK_OFF_M * math.sin(yaw)
    arc = live.arc(index)
    _d, s, _t = arc.project(bx, by)
    if s <= 1e-3:   # behind the edge start: only a predecessor of this route that joins straight
        if index == 0:
            return False
        prev = live.arc(index - 1)
        bend = abs(math.degrees((prev.point_at(prev.length_m)[2] - arc.point_at(0.0)[2] + math.pi)
                                % (2 * math.pi) - math.pi))
        if bend > CONTINUITY_DEG:
            return False
        arc = prev
    return lane_offset(arc, bx, by, BODY_HALF_WIDTH_M)[1] >= 0.0


async def refusal(runner, live, robot_id: str, state: dict) -> str | None:
    """Why the robot may not back off now; None: Fleet's own conditions hold (CORE still judges the rear)."""
    if (state.get("safety") or {}).get("estop") is not False:
        return "estop"
    if state.get("mode") != "IDLE":
        return "mode_not_idle"
    cable = getattr(runner, "bay_cable_inhibited", None)
    if cable is None or cable(robot_id):
        return "cable"
    if getattr(runner, "robot_step", None) is None:
        return "step_unavailable"
    active = runner._store.active()
    if active is None or active[0] != live.view["map_version"]:
        return "map_version"
    index = live.view["segment_index"]
    if _excluded(runner, live, index, state) or runner._strict_named_stop(live, index) is not None:
        return "excluded_zone"
    near = live.segments[max(0, index - 1): index + 1]
    if crosswalks_on(active[2], near, getattr(active[1], "crosswalks", ()) or ()):
        return "crosswalk"
    if getattr(runner, "traffic", None) is not None and signals_on(runner.traffic, near):
        return "signal"
    me = await _pose(runner, robot_id)
    if me is None or me.state != "LOCALIZED" or me.x is None or me.yaw is None:
        return "pose"
    if not _room(live, index, me.x, me.y, me.yaw):
        return "no_room"
    now = runner._clock()
    roster = getattr(runner, "_roster", None)
    if not callable(roster):
        return "peer_unknown"   # no roster: nobody can say who else is on the floor
    for other in roster():
        if other == robot_id:
            continue
        peer = await _pose(runner, other)
        if (peer is None or peer.state != "LOCALIZED" or peer.x is None or peer.map_id not in (None, active[1].map_id)
                or peer.odom_stamp is None or not 0.0 <= now - peer.odom_stamp < PEER_FRESH_S):
            return "peer_unknown"   # a robot nobody can place may stand behind
        if math.hypot(peer.x - me.x, peer.y - me.y) < PEER_CLEAR_M:
            return "peer_near"
    return None


async def looked_again(runner, live, robot_id: str, state: dict) -> str | None:
    """After the back-off: what is still missing before the reissue (D-1080's trust rule), or None."""
    from fleet.server.named_stop_map_pose import read_precision_pose
    if (state.get("localization") or {}).get("state") != "LOCALIZED":
        return "localized"
    if _excluded(runner, live, live.view["segment_index"], state):
        return None   # D-1080: the bay leg is not judged by the camera
    cam = await _pose(runner, robot_id)
    if (cam is None or cam.state != "LOCALIZED" or cam.x is None or cam.anchor_source not in CAMERA_SOURCES
            or cam.anchor_age_s is None or not 0.0 <= cam.anchor_age_s < CAMERA_MAX_AGE_S
            or not 0.0 <= cam.dead_reckon_m <= CAMERA_BRIDGE_MAX_M):
        return "camera"
    try:
        bound = await read_precision_pose(runner, robot_id, live.view["map_version"])
    except Exception:  # noqa: BLE001 - no SLAM pose is no agreement
        bound = None
    if bound is None:
        return "slam_pose"
    slam = bound[0]
    if math.hypot(slam.x - cam.x, slam.y - cam.y) > GAP_MAX_M:
        return "slam_camera_gap"
    return None


def side_text(rec: dict, attempts: list) -> str:
    """The end reason a person reads when backing off has run out."""
    same = rec.get("same_spot") or {}
    tried = ", ".join(f"{a.get('attempt')}: cap {a.get('speed_cap_mps')} recentre {a.get('recentre')}" for a in attempts)
    return (f"한쪽 치우침 복구 실패: lat {same.get('lat_m')} m, 벽 여유 {same.get('wall_clear_m')} m, "
            f"시도한 조건 [{tried}]")
