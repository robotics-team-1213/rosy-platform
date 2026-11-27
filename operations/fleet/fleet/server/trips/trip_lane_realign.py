"""D-1080: a Nav2 road trip whose body leaves its lane is slowed and given a route back, never stopped here.

Steering stays on the robot (Nav2/RPP); Fleet (2 Hz) only judges and acts through the channels it already owns:
the road_speed grant (``slow`` → ``REALIGN_SLOW_MPS``, ``trip_road_speed.RoadSpeed.renew``) and the existing
cancel → ack → resend of the current route, whose resend is ``sample_nav2_route(here=...)``'s recentring route
(``step_nav2_route``, the replan path). No hold, no end, no person: the trip stays ``running``.

Classification, every tick of a navigating route (``detail['lane_departure']['kind']``):
``excluded`` charge-bay leg, parking handoff or DOCKING (D-972) · ``location`` robot state unread, robot localization
not LOCALIZED, no bound SLAM pose to read (the trip's own, or the robot's through its binding), or SLAM-vs-camera gap > ``GAP_MAX_M`` (robot-d3's transient_loc_hold owns
the answer; nothing here acts) · ``camera_unavailable`` / ``camera_stale`` (recorded and warned only) ·
``on_lane`` / ``near_edge`` (margin < ``NEAR_EDGE_M``, recorded) / ``departed`` (margin < 0). The margin is
D-511's body margin (``lane_offset``) of the ceiling-camera pose, never the robot's AMCL pose.

The slow cap ends when the camera sees the robot back (``REALIGNED_*``), on an excluded leg, or ``SLOW_EVIDENCE_S``
after the last fresh ``departed`` or ``wall_side`` judgement.

Prevention (D-1082 ladder, user 2026-11-28): still inside the lane, a robot at least WALL_SIDE_M off the centre whose
wall clearance is WALL_CLOSER_M below the centreline's for PERSIST_TICKS judged ticks gets the slow cap only
(``wall_side_at``); no route is replaced, a resend there would zigzag. A map with no walls is never judged.
"""
from __future__ import annotations

import inspect
import logging
import math
from types import SimpleNamespace

from fleet.localization.lane_compliance import BODY_HALF_WIDTH_M, lane_offset
from fleet.localization.lane_compliance_helpers import parking_edge
from fleet.localization.map_binding import bound_pose
from fleet.server.named_stop_map_pose import fresh_native_slam
from fleet.server.trip_geometry import _wall_clearance

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
PERSIST_TICKS = 2
REALIGN_SLOW_MPS = 0.05
COOLDOWN_S = 3.0            # one recentring resend per departure window; the resend itself must not be repeated
REALIGNED_LAT_M = 0.02
REALIGNED_DEG = 10.0
#: The slow cap lives on fresh camera evidence of a departure: this long without one (camera lost, a location
#: problem, or back inside the lane but not yet aligned) it is lifted, so no robot crawls on without a reason.
SLOW_EVIDENCE_S = 10.0
WALL_SIDE_M = 0.02          # off the centre toward a wall by this much (rosy_45 2026-11-27: 0.03 m, wall 0.13 m)
WALL_CLOSER_M = 0.02        # and its wall clearance this much below the centreline's
_RUNNING = ("NAVIGATING", "PLANNING")

_LOG = logging.getLogger("fleet.server.trip_runner")


def _excluded(runner, live, index: int, state) -> bool:
    arc = live.arc(index)
    topview = getattr(runner, "cell_topview", None)  # the top-view stop sits off the lane centre by design
    return (parking_edge(live.graph, arc.edge_id) or live.view["detail"].get("parking_handoff") is not None
            or (topview is not None and topview.covers(arc.end_place))  # the approach into it, not the way out
            or (isinstance(state, dict) and state.get("mode") == "DOCKING"))


def _wall_side(arc, x: float, y: float, walls) -> tuple[float, float] | None:
    """(wall clearance here, at the lane centre beside it), or None with no wall on the map."""
    if not walls:
        return None
    _dist, s, _t = arc.project(x, y)
    px, py, _ = arc.point_at(s)
    here, centre = _wall_clearance(x, y, walls), _wall_clearance(px, py, walls)
    return (round(here, 4), round(centre, 4)) if math.isfinite(here) and math.isfinite(centre) else None


async def observe(runner, live, index: int, pose, state, nav) -> bool:
    """Record ``detail['lane_departure']``; True when the current route is to be replaced by a recentring one."""
    try:
        return await _observe(runner, live, index, pose, state, nav)
    except Exception as exc:  # noqa: BLE001 - a fault in this watch never fails the trip it watches
        _LOG.exception("lane departure %s: not judged", live.view.get("robot_id"))
        live.view["detail"]["lane_departure"] = {**(live.view["detail"].get("lane_departure") or {}),
                                                 "kind": "error", "reason": type(exc).__name__, "ticks": 0}
        return False


def _bound_slam(runner, live, state, active, now):
    """The robot's fresh native SLAM pose through its approved map binding, on the active site map: ``(pose, None)``
    or ``(None, why)``. The same read a bound Nav2 trip drives on (``read_precision_pose_status``), without a trip scope."""
    try:
        bindings = runner._store.map_bindings
        fit, why = bindings.matching_fit(live.view["robot_id"], state, (active[1].map_id, active[0]))
    except Exception as exc:  # noqa: BLE001 - no binding store or an unreadable one is "no SLAM pose", never a failure
        return None, type(exc).__name__
    if fit is None:
        return None, why or "MAP_BINDING_REQUIRED"
    sample = fresh_native_slam(state, now)
    if sample is None:
        return None, "SLAM_POSE_STALE"
    x, y, yaw = bound_pose(fit, sample[0])
    return SimpleNamespace(x=x, y=y, yaw=yaw, source="approved_slam"), None


async def _observe(runner, live, index: int, pose, state, nav) -> bool:
    detail = live.view["detail"]
    last = detail.get("lane_departure") or {}
    now = runner._clock()
    out = {"at": now, "slow": bool(last.get("slow")), "replaced": last.get("replaced", 0),
           "replaced_at": last.get("replaced_at"), "departed_at": last.get("departed_at"), "ticks": 0,
           "wall_side_at": last.get("wall_side_at")}
    detail["lane_departure"] = out
    seen = max((t for t in (out["departed_at"], out["wall_side_at"]) if t is not None), default=None)
    if out["slow"] and (seen is None or now - seen >= SLOW_EVIDENCE_S):
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
        # A trip that does not drive on the bound SLAM pose (its pose is the camera's): read the robot's own.
        pose, why = _bound_slam(runner, live, state, active, now)
        if pose is None:
            return note("location", "SLAM_POSE_UNBOUND", camera_age_s=round(age, 3), slam_reason=why)
    gap = math.hypot(pose.x - cam.x, pose.y - cam.y)
    if gap > GAP_MAX_M:
        return note("location", "SLAM_CAMERA_GAP", camera_age_s=round(age, 3), gap_m=round(gap, 4))
    lat, margin, tangent = lane_offset(live.arc(index), cam.x, cam.y, BODY_HALF_WIDTH_M)
    yaw = pose.yaw if pose.yaw is not None else cam.yaw   # the robot's own heading: the camera's is off at the edges
    turn = None if yaw is None else abs(math.degrees((tangent - yaw + math.pi) % (2 * math.pi) - math.pi))
    fields = {"lat_m": round(lat, 4), "margin_m": round(margin, 4), "camera_age_s": round(age, 3),
              "gap_m": round(gap, 4), "heading_deg": None if turn is None else round(turn, 1)}
    if out["slow"] and abs(lat) <= REALIGNED_LAT_M and turn is not None and turn <= REALIGNED_DEG:
        out.update(slow=False, realigned_at=now)
    clear = _wall_side(live.arc(index), cam.x, cam.y, getattr(active[1], "walls", None))
    if clear is not None:
        fields.update(wall_clear_m=clear[0], centre_wall_clear_m=clear[1])
    if margin >= 0.0:
        near = clear is not None and abs(lat) >= WALL_SIDE_M and clear[0] <= clear[1] - WALL_CLOSER_M
        out["wall_ticks"] = last.get("wall_ticks", 0) + 1 if near else 0
        if out["wall_ticks"] >= PERSIST_TICKS and nav in _RUNNING:
            out.update(slow=True, wall_side_at=now)   # slow only: no resend
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
