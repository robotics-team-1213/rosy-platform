"""D-550 8 / D-760 3 (stage 1): Rule M, warn only.

Every motion Fleet starts must be bounded by a TTL or by a link signal the robot can see.
``verdict`` judges one robot from what Fleet already holds (D-550 7 table) and calls nothing:
no robot, no clock, no transport. Anything it cannot tell counts as unbounded, never as bounded.
Dashboard and Pilot motion is not Fleet's and is not judged; neither is a line follow opened
outside a trip (``POST /api/fleet/robots/{id}/line-follow``): Fleet keeps no record of having
opened it, so it cannot tell its own from the dashboard's.
"""

from __future__ import annotations

from typing import Optional

BOUNDED, UNBOUNDED, IDLE = "bounded", "unbounded", "idle"
LANE_TRIP, GOAL, FOLLOW = "lane_trip", "goal", "follow"
#: SAF-003 policies that stop or hold a paired robot when the hub link is lost (D-550 8).
LINK_BOUND_POLICIES = frozenset({"STOP", "HOLD", "RETURN_HOME"})
#: ``state.navigation`` values that say the goal is over; any other value (or none) may be moving.
GOAL_OVER = frozenset({"IDLE", "ARRIVED", "CANCELED", "FAILED"})


def _answer(state: str, motion: Optional[str] = None, reason: Optional[str] = None) -> dict:
    return {"state": state, "motion": motion, "reason": reason}


def _goal(goal_lease, gather_source, fleet_loss_policy) -> dict:
    if goal_lease == "leased":  # D-550 10: CORE cancels the goal when renewals stop
        return _answer(BOUNDED, GOAL)
    if gather_source != "hub":  # REST only: no FleetAgent, SAF-003 never fires
        return _answer(UNBOUNDED, GOAL, "rest_only")
    if fleet_loss_policy == "CONTINUE":
        return _answer(UNBOUNDED, GOAL, "policy_continue")
    if fleet_loss_policy not in LINK_BOUND_POLICIES:
        return _answer(UNBOUNDED, GOAL, "policy_unknown")
    return _answer(BOUNDED, GOAL)


def verdict(*, trip: Optional[dict] = None, leg: Optional[str] = None, follower: bool = False,
            goal: Optional[dict] = None, navigation: Optional[str] = None,
            gather_source: Optional[str] = None, fleet_loss_policy: Optional[str] = None) -> dict:
    """``{"state": bounded|unbounded|idle, "motion": lane_trip|goal|follow|None, "reason": ...}``.

    ``trip`` is the robot's open trip view and ``leg`` the drive mode of its current segment;
    ``follower`` says Fleet's formation session holds it as a follower; ``goal`` is the console
    goal record (with ``goal_lease``) and ``navigation`` the robot's last ``state.navigation``.
    """
    goal_lease = goal.get("goal_lease") if isinstance(goal, dict) else None
    if trip is not None:
        motion = GOAL if leg == "free" else LANE_TRIP
        lease = trip.get("lease")
        if isinstance(lease, dict) and lease.get("state") == "held":
            return _answer(BOUNDED, motion)  # D-541: CORE halts to IDLE when the trip lease expires
        if leg == "free":
            return _goal(goal_lease, gather_source, fleet_loss_policy)
        if leg != "lane":
            return _answer(UNBOUNDED, None, "leg_unknown")
        if trip.get("traffic_authority") == "core":  # D-517 4: authority ttl
            return _answer(BOUNDED, LANE_TRIP)
        return _answer(UNBOUNDED, LANE_TRIP, "hold_back")
    if follower:  # stream_timeout_ms -> HOLD
        return _answer(BOUNDED, FOLLOW)
    if goal is not None and navigation not in GOAL_OVER:
        return _goal(goal_lease, gather_source, fleet_loss_policy)
    return _answer(IDLE)
