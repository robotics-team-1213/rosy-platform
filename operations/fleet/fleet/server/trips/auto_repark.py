"""A named stop's REPARK verdict inside CORE's fine re-park caps runs without an operator (2026-11-21).

Nav2 ends 0-5 cm short of a goal by construction, so REPARK is the normal verdict. The trip step issues the
exact correction the operator route would (`dispatch_correction`: lease, stop token, cable, frame and corridor
checks, handover, one scoped POST) as `fleet-auto-repark`; the next steps re-evaluate the verdict until
IN_TOLERANCE. Anything else stays HOLD and the operator clearance route is unchanged.

The robot can report LOCALIZED while its pose is 10+ cm off (measured 2026-11-21), and no person looks at an
automatic correction. So it runs only while the ceiling camera's own sighting (D-1062) agrees with the pose the
verdict used, inside the stop's commissioned pose uncertainty."""

import math

from fastapi import HTTPException

from core_common.stop_pose import repark_within_limits
from fleet.localization import trust
from fleet.localization.topview_pose import TopviewError
from fleet.localization.map_binding import bound_pose
from fleet.server.named_stop_decision import check_repark_decision, named_stop_decision
from fleet.server.named_stop_topview import KEY as TOPVIEW_KEY, SOURCE as TOPVIEW_SOURCE, heading_agrees, topview_decision
from fleet.server.precision_correction_routes import CorrectionClearance, dispatch_correction
from fleet.site_map import SitePlace
from fleet.traffic.trip_lease import HELD

ACTOR = "fleet-auto-repark"


class AutoNamedCorrection:
    def __init__(self, console, runner, cable_inhibited):
        self.console, self.runner, self.cable_inhibited = console, runner, cable_inhibited

    def armed(self, robot_id):
        return self.console.goal_leases.named_repark_armed(robot_id)

    async def send(self, trip_id, clearance):
        return await dispatch_correction(self.console, self.runner, trip_id, clearance,
                                         cable_inhibited=self.cable_inhibited, actor=ACTOR)


def _hold(decision, reason):
    return {**decision, "decision": "HOLD", "reason": reason}


def _refusal(live, state):
    lease = live.view.get("lease")
    if not live.open or live.view.get("hold") is not None or (lease and lease.get("state") != HELD):
        return "trip_not_running"
    if (state.get("safety") or {}).get("estop") is not False:
        return "estop"
    if trust.classify(state) != trust.TRUSTED:
        return "not_localized"
    return None


async def _camera_refusal(runner, robot, fit, state, limits):
    seen = await runner.map_pose(robot)
    camera = getattr(seen, "camera_x", None), getattr(seen, "camera_y", None)  # None: no sighting in the last seconds
    if None in camera:
        return "camera_sighting_required"
    pose = state["pose"]
    x, y, _ = bound_pose(fit, (pose["x"], pose["y"], pose["yaw"]))
    if math.hypot(camera[0] - x, camera[1] - y) > limits.position_uncertainty_m + fit.max:
        return "camera_disagrees_with_pose"
    return None


async def auto_repark(runner, live, evidence, decision, state, fit, limits):
    auto = runner.auto_named_correction
    if decision["decision"] != "REPARK" or not decision.get("path_preview") or auto is None:
        return decision
    robot = live.view["robot_id"]
    if auto.armed(robot):
        return decision  # our re-park is running: the next steps re-evaluate when it ends
    topview = decision.get("source") == TOPVIEW_SOURCE  # the camera that made the verdict is its own evidence
    record = live.view["detail"].setdefault("named_stop_auto_repark", {"attempts": 0})
    if record["attempts"] >= (runner.config.cell_topview_corrections if topview
                              else runner.config.named_stop_auto_corrections):
        return _hold(decision, "auto_correction_limit")
    left = decision.get("left_m", 0.0)
    turn = decision.get("turn_deg", 0.0)
    if not repark_within_limits(decision["forward_m"], left, turn):
        return _hold(decision, "outside_repark_limits")
    reason = _refusal(live, state) or (None if topview else await _camera_refusal(runner, robot, fit, state, limits))
    if reason is not None:
        return _hold(decision, reason)
    record["attempts"] += 1  # counted before the POST: a lost reply still armed custody
    try:
        clearance = CorrectionClearance(nav_run_id=live.view["detail"]["named_stop_operation"]["run_id"],
                                        map_sha256=evidence["map_sha256"], forward_m=decision["forward_m"], left_m=left, turn_deg=turn,
                                        site_end=tuple(decision["site_end"]), cable_and_path_clear=True)
        await auto.send(live.view["trip_id"], clearance)
    except HTTPException as exc:
        code = (exc.detail or {}).get("code") if isinstance(exc.detail, dict) else None
        return _hold(decision, code or "NAMED_STOP_CORRECTION_REFUSED")
    except ValueError:  # a correction the clearance model rejects is a refused correction, not an unreachable robot
        return _hold(decision, "NAMED_STOP_CORRECTION_REFUSED")
    return {**decision, "auto_repark": "dispatched"}


async def _topview_verdict(runner, live, evidence, place, site_place, fit, state, topview):
    """(verdict, None), or (None, reason) when the top view is no evidence and the SLAM verdict stands."""
    detail, robot = live.view["detail"], live.view["robot_id"]
    record, auto = detail.get(TOPVIEW_KEY), runner.auto_named_correction
    if record is not None and record.get("place") == site_place.id and auto is not None and auto.armed(robot):
        return {**record["decision"], "auto_repark": "running"}, None  # our re-park runs; the next step reads again
    pose = (state or {}).get("pose") or {}
    try:
        if any(type(pose.get(axis)) not in (int, float) for axis in ("x", "y", "yaw")):
            raise TopviewError("robot_pose_unavailable")
        seen = await topview.read(robot)
        if not heading_agrees(site_place, seen, bound_pose(fit, (pose["x"], pose["y"], pose["yaw"]))[2]):
            raise TopviewError("heading_disagrees_with_pose")
        decision = topview_decision(site_place, seen)
    except Exception as exc:  # noqa: BLE001 - whatever the camera or vision does wrong is no evidence, never a crash
        detail.pop(TOPVIEW_KEY, None)
        return None, exc.reason if isinstance(exc, TopviewError) else f"topview_{type(exc).__name__}"
    detail[TOPVIEW_KEY] = {"place": site_place.id, "decision": decision, "read_at": runner._clock(),
                           "pose": {axis: pose[axis] for axis in ("x", "y", "yaw")}}
    return await check_repark_decision(runner, live, evidence, place, decision), None


def _with_steps(live, result):
    """The top-view stop's trip detail lists every correction step with the error that asked for it."""
    if result.get("source") != TOPVIEW_SOURCE:
        return result
    steps = live.view["detail"].setdefault("named_stop_topview_steps", [])
    if result.get("auto_repark") == "dispatched":
        error = result["error"]
        if result.get("turn_deg"):
            steps.append({"step": "rotate", "turn_deg": result["turn_deg"],
                          "measured_heading_deg": round(math.degrees(error["heading_rad"]), 2)})
        if result["forward_m"] or result.get("left_m"):
            steps.append({"step": "translate", "forward_m": result["forward_m"], "left_m": result.get("left_m", 0.0),
                          "measured_longitudinal_m": round(error["longitudinal_m"], 4),
                          "measured_lateral_m": round(error["lateral_m"], 4)})
    return {**result, "steps": list(steps)}


async def evaluate_named_stop(runner, live, evidence, place, fit, state):
    site_place = SitePlace.model_validate(place)
    topview, unavailable = getattr(runner, "cell_topview", None), None
    if topview is not None and topview.covers(site_place.id):
        verdict, unavailable = await _topview_verdict(runner, live, evidence, place, site_place, fit, state, topview)
        if verdict is not None:
            return _with_steps(live, await auto_repark(runner, live, evidence, verdict, state, fit, site_place.precision_stop))
    decision = await check_repark_decision(runner, live, evidence, place, named_stop_decision(site_place, fit, state))
    result = await auto_repark(runner, live, evidence, decision, state, fit, site_place.precision_stop)
    return {**result, "topview_unavailable": unavailable} if unavailable else result
