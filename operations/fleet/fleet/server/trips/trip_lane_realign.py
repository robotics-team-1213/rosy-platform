"""D-1080: a Nav2 road trip whose body leaves its lane is slowed and given a route back, never stopped here.

Steering stays on the robot (Nav2/RPP); Fleet (2 Hz) only judges and acts through the channels it already owns:
the road_speed grant (``slow`` → ``REALIGN_SLOW_MPS``, ``trip_road_speed.RoadSpeed.renew``) and the existing
cancel → ack → resend of the current route, whose resend is ``sample_nav2_route(here=...)``'s recentring route
(``step_nav2_route``, the replan path). No hold, no end, no person: the trip stays ``running``.

Classification, every tick of a navigating route (``detail['lane_departure']['kind']``):
``excluded`` charge-bay leg, parking handoff or DOCKING (D-972) · ``location`` robot state unread, robot localization
not LOCALIZED, no approved-SLAM trip pose, or SLAM-vs-camera gap > ``GAP_MAX_M`` (robot-d3's transient_loc_hold owns
the answer; nothing here acts) · ``camera_unavailable`` / ``camera_stale`` (recorded and warned only) ·
``on_lane`` / ``near_edge`` (margin < ``NEAR_EDGE_M``, recorded) / ``departed`` (margin < 0). The margin is
D-511's body margin (``lane_offset``) of the ceiling-camera pose, never the robot's AMCL pose.

The slow cap ends when the camera sees the robot back (``REALIGNED_*``), on an excluded leg, or ``SLOW_EVIDENCE_S``
after the last fresh ``departed`` judgement.
"""
from __future__ import annotations

import inspect
import logging
import math

from fleet.localization.lane_compliance import BODY_HALF_WIDTH_M, lane_offset

GAP_MAX_M = 0.05            # robot SLAM pose vs ceiling-camera pose: farther apart is a location problem
#: The camera anchor must be this fresh to act. On site the anchor is 0.4-0.6 s old (2026-11-27), so 0.5 s threw
#: away every other tick and two consecutive ones almost never came. What the age costs is the odom carried since
#: the anchor, so that is bounded too: at most CAMERA_BRIDGE_MAX_M of dead reckoning.
CAMERA_MAX_AGE_S = 1.0
CAMERA_BRIDGE_MAX_M = 0.15
#: What set the pose's anchor (MapPose.anchor_source). While the robot moves the pose's own source reads "bridged"
#: (the camera anchor carried on by odom), so the anchor is what says "the camera saw it" (2026-11-27 live run: every
#: tick was camera_unavailable because the source was read instead). The anchor's age bounds the odom part.
CAMERA_SOURCES = ("sighting", "track")
NEAR_EDGE_M = 0.02
PERSIST_TICKS = 4
REALIGN_SLOW_MPS = 0.08   # = the tight-curve cap: no new speed step
COOLDOWN_S = 8.0            # one recentring resend per departure window; the resend itself must not be repeated
REALIGNED_LAT_M = 0.02
REALIGNED_DEG = 10.0
#: The slow cap lives on fresh camera evidence of a departure: this long without one (camera lost, a location
#: problem, or back inside the lane but not yet aligned) it is lifted, so no robot crawls on without a reason.
SLOW_EVIDENCE_S = 10.0
_RUNNING = ("NAVIGATING", "PLANNING")

_LOG = logging.getLogger("fleet.server.trip_runner")


def _excluded(runner, live, index: int, state) -> bool:
    arc = live.arc(index)
    places = getattr(live.graph, "places", None) or {}
    charge = any(getattr(places.get(p), "kind", None) == "charge" for p in (arc.start_place, arc.end_place))
    topview = getattr(runner, "cell_topview", None)  # the top-view stop sits off the lane centre by design
    return (charge or arc.edge_id.startswith("bay_") or live.view["detail"].get("parking_handoff") is not None
            or (topview is not None and topview.covers(arc.end_place))  # the approach into it, not the way out
            or (isinstance(state, dict) and state.get("mode") == "DOCKING"))


async def observe(runner, live, index: int, pose, state, nav) -> bool:
    """Record ``detail['lane_departure']``; True when the current route is to be replaced by a recentring one."""
    try:
        return await _observe(runner, live, index, pose, state, nav)
    except Exception as exc:  # noqa: BLE001 - a fault in this watch never fails the trip it watches
        _LOG.exception("lane departure %s: not judged", live.view.get("robot_id"))
        live.view["detail"]["lane_departure"] = {**(live.view["detail"].get("lane_departure") or {}),
                                                 "kind": "error", "reason": type(exc).__name__, "ticks": 0}
        return False


async def _observe(runner, live, index: int, pose, state, nav) -> bool:
    detail = live.view["detail"]
    last = detail.get("lane_departure") or {}
    now = runner._clock()
    out = {"at": now, "slow": bool(last.get("slow")), "replaced": last.get("replaced", 0),
           "replaced_at": last.get("replaced_at"), "departed_at": last.get("departed_at"), "ticks": 0}
    detail["lane_departure"] = out
    if out["slow"] and (out["departed_at"] is None or now - out["departed_at"] >= SLOW_EVIDENCE_S):
        out.update(slow=False, slow_expired_at=now)

    def note(kind, reason=None, **fields):
        if kind == "camera_stale" and last.get("kind") != kind:
            _LOG.warning("lane departure %s: camera pose %s s old, not acted on", live.view["robot_id"],
                         fields.get("camera_age_s"))
        out.update(kind=kind, reason=reason, **fields)
        return False

    if _excluded(runner, live, index, state):
        out["slow"] = False     # D-972: no judgement and no action on the bay leg
        return note("excluded")
    if not isinstance(state, dict):
        return note("location", "STATE_UNREAD")
    loc = (state.get("localization") or {}).get("state")
    if loc != "LOCALIZED":
        return note("location", "ROBOT_NOT_LOCALIZED", loc_state=loc)
    try:
        cam = runner._poses.arbitrated_pose(live.view["robot_id"])   # MapPosePort: sync or async
        cam = await cam if inspect.isawaitable(cam) else cam
    except Exception:  # noqa: BLE001 - an unreadable camera pose is no camera pose, never a trip failure
        cam = None
    active = runner._store.active()
    if (cam is None or cam.state != "LOCALIZED" or cam.x is None or cam.y is None
            or cam.anchor_source not in CAMERA_SOURCES or active is None
            or cam.map_id not in (None, active[1].map_id)):
        return note("camera_unavailable", source=getattr(cam, "source", None),
                    anchor_source=getattr(cam, "anchor_source", None))
    age = cam.anchor_age_s
    if age is None or not 0.0 <= age < CAMERA_MAX_AGE_S or not 0.0 <= cam.dead_reckon_m <= CAMERA_BRIDGE_MAX_M:
        return note("camera_stale", camera_age_s=age, bridged_m=cam.dead_reckon_m)
    if getattr(pose, "source", None) != "approved_slam":
        return note("location", "SLAM_POSE_UNBOUND", camera_age_s=round(age, 3))
    gap = math.hypot(pose.x - cam.x, pose.y - cam.y)
    if gap > GAP_MAX_M:
        return note("location", "SLAM_CAMERA_GAP", camera_age_s=round(age, 3), gap_m=round(gap, 4))
    lat, margin, tangent = lane_offset(live.arc(index), cam.x, cam.y, BODY_HALF_WIDTH_M)
    yaw = cam.yaw if cam.yaw is not None else pose.yaw
    turn = None if yaw is None else abs(math.degrees((tangent - yaw + math.pi) % (2 * math.pi) - math.pi))
    fields = {"lat_m": round(lat, 4), "margin_m": round(margin, 4), "camera_age_s": round(age, 3),
              "gap_m": round(gap, 4), "heading_deg": None if turn is None else round(turn, 1)}
    if out["slow"] and abs(lat) <= REALIGNED_LAT_M and turn is not None and turn <= REALIGNED_DEG:
        out.update(slow=False, realigned_at=now)
    if margin >= 0.0:
        return note("on_lane" if margin >= NEAR_EDGE_M else "near_edge", **fields)
    out["ticks"] = (last.get("ticks", 0) if last.get("kind") == "departed" else 0) + 1
    note("departed", **fields)
    out["departed_at"] = now
    if out["ticks"] < PERSIST_TICKS or nav not in _RUNNING:
        return False
    out["slow"] = True
    if ((live.active_route or {}).get("wait_prefix") or live.view.get("hold") is not None
            or (out["replaced_at"] is not None and now - out["replaced_at"] < COOLDOWN_S)):
        return False
    out.update(replaced=out["replaced"] + 1, replaced_at=now)
    _LOG.info("lane departure %s: lat %.3f m margin %.3f m, slowed and resending a recentring route",
              live.view["robot_id"], lat, margin)
    return True
