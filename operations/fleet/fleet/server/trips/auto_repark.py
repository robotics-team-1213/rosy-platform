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
from fleet.localization.map_binding import bound_pose
from fleet.server.named_stop_decision import check_repark_decision, named_stop_decision
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
    record = live.view["detail"].setdefault("named_stop_auto_repark", {"attempts": 0})
    if record["attempts"] >= runner.config.named_stop_auto_corrections:
        return _hold(decision, "auto_correction_limit")
    if not repark_within_limits(decision["forward_m"]):
        return _hold(decision, "outside_repark_limits")
    reason = _refusal(live, state) or await _camera_refusal(runner, robot, fit, state, limits)
    if reason is not None:
        return _hold(decision, reason)
    record["attempts"] += 1  # counted before the POST: a lost reply still armed custody
    try:
        clearance = CorrectionClearance(nav_run_id=live.view["detail"]["named_stop_operation"]["run_id"],
                                        map_sha256=evidence["map_sha256"], forward_m=decision["forward_m"],
                                        site_end=tuple(decision["site_end"]), cable_and_path_clear=True)
        await auto.send(live.view["trip_id"], clearance)
    except HTTPException as exc:
        code = (exc.detail or {}).get("code") if isinstance(exc.detail, dict) else None
        return _hold(decision, code or "NAMED_STOP_CORRECTION_REFUSED")
    except ValueError:  # a correction the clearance model rejects is a refused correction, not an unreachable robot
        return _hold(decision, "NAMED_STOP_CORRECTION_REFUSED")
    return {**decision, "auto_repark": "dispatched"}


async def evaluate_named_stop(runner, live, evidence, place, fit, state):
    site_place = SitePlace.model_validate(place)
    decision = await check_repark_decision(runner, live, evidence, place, named_stop_decision(site_place, fit, state))
    return await auto_repark(runner, live, evidence, decision, state, fit, site_place.precision_stop)
