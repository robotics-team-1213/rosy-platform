"""Named-stop arrival confirmation helpers extracted from ``trip_steps`` (D-766 size cap)."""

from __future__ import annotations

from fleet.routing.cost import STOP
from fleet.server.auto_repark import evaluate_named_stop
from fleet.server.channel.execution.outcomes.evidence import safe_proof
from fleet.server.named_stop_decision import confirm_precision_arrival
from fleet.server.trip_live import LiveTrip


class GoalRefused(RuntimeError):
    """A trip goal was refused or canceled by the console's admission checks."""

    def __init__(self, reason: str, reply: dict | None = None):
        super().__init__(reason)
        self.detail = {"goal_reason": reason or None}
        if reply is not None:
            evidence = {key: reply[key] for key in (
                "blocked_by", "waiting_on", "dispatch_attempted", "cancel_confirmed",
            ) if key in reply}
            if evidence:
                self.detail["goal_admission"] = evidence


def confirm_lane_stop(steps, live: LiveTrip, index: int) -> bool:
    """Confirm CORE holds the lane arrival stop under this trip's active lease."""
    sent, junction = live.sent or {}, live.junction
    lease = live.view.get("lease") or {}
    if (sent.get("index") != index or sent.get("action") != STOP
            or type(sent.get("seq")) is not int or sent["seq"] != junction.get("seq")
            or not sent.get("place") or sent["place"] != junction.get("place_id")
            or junction.get("state") != "executing" or junction.get("pending_action") != STOP
            or junction.get("line_stop_held") is not True or lease.get("state") != "held"
            or not lease.get("lease_id") or lease["lease_id"] != junction.get("active_trip_lease_id")
            or steps.traffic.holds(live, index)):
        return False
    live.view["detail"]["named_stop_lane_hold"] = {
        "seq": sent["seq"], "place_id": sent["place"], "lease_id": lease["lease_id"]}
    return True


async def confirm_free_stop(steps, live: LiveTrip) -> bool:
    """Confirm CORE completed the Nav2 free-segment stop and any precision repark."""
    expected = live.view["detail"].get("named_stop_operation")
    if expected is None or steps.navigation_readback is None:
        return False
    view = await steps._call(steps.navigation_readback(live.view["robot_id"], expected["run_id"]))
    if not isinstance(view, dict) or view.get("lookup") != "FOUND":
        return False
    operation = view.get("operation") or {}
    owner, proof = view.get("owner") or {}, view.get("quiescence") or {}
    if not all(isinstance(value, dict) for value in (operation, owner, proof)):
        return False
    identity = ("kind", "boot_id", "run_id", "correlation_id")
    if not all(operation.get(k) == expected[k] for k in identity) or operation.get("phase") != "TERMINAL":
        return False
    if operation.get("result") != "SUCCEEDED":
        raise GoalRefused("NAMED_STOP_NAV2_FAILED")
    if not safe_proof(view, operation):
        return False
    evidence = live.view["detail"].get("named_stop_dispatch")
    if not evidence or evidence["attempt_id"] != operation["correlation_id"]:
        raise GoalRefused("NAMED_STOP_DISPATCH_EVIDENCE_MISSING")
    robot_id = live.view["robot_id"]
    read_state = steps.named_stop_state or steps._robot_state
    state = await steps._call(read_state(robot_id)) if read_state is not None else None
    if not live.open:
        return False
    state = state or {}
    velocity = state.get("velocity") or {}
    if (state.get("navigation") != "ARRIVED" or state.get("mode") not in ("NAVIGATION", "IDLE")
            or (state.get("line_follow") or {}).get("mode") != "OFF"
            or velocity.get("linear") != 0.0 or velocity.get("angular") != 0.0):
        return False
    active = steps._store.active_view()
    bindings = steps._store.map_bindings
    binding = bindings.active(robot_id) or {}
    fit, _ = bindings.matching_fit(robot_id, state, (evidence["map_id"], evidence["map_version"]))
    if (active is None or (active["version"], active["sha256"]) !=
            (evidence["map_version"], evidence["map_sha256"])
            or fit is None or state.get("map_grid_id") != evidence["map_grid_id"]
            or binding.get("binding_id") != evidence["binding_id"]):
        raise GoalRefused("NAMED_STOP_DISPATCH_FRAME_CHANGED")
    place = next((place for place in active["map"]["places"] if place["id"] == evidence["place"]), None)
    if place is not None and place.get("precision_stop") is not None:
        decision = await evaluate_named_stop(steps, live, evidence, place, fit, state)
        live.view["detail"]["named_stop_precision"] = decision
        if decision["decision"] != "IN_TOLERANCE":
            return False
        if not await confirm_precision_arrival(steps, live, operation, evidence, place):
            return False
    live.view["detail"]["named_stop_completion"] = {
        "dispatch": evidence, "operation": operation, "owner": owner, "quiescence": proof,
    }
    return True
