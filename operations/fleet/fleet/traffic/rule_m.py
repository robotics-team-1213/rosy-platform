"""D-550 8 / D-760 3 (stage 1): Rule M, warn only.

Every motion Fleet starts must be bounded. ``verdict`` judges one robot from what Fleet already
holds and calls nothing. Only the TTL bounds Fleet itself keeps count: lane authority ``core``,
a held trip lease, a leased goal. Anything else, or anything it cannot tell, is unbounded.
Not judged: dashboard and Pilot motion, and a line follow opened outside a trip (Fleet keeps no
record of opening one, so it cannot tell its own from the dashboard's).
"""

from __future__ import annotations

from typing import Optional


def _answer(state: str, motion: Optional[str] = None, reason: Optional[str] = None) -> dict:
    return {"state": state, "motion": motion, "reason": reason}


def verdict(*, trip: Optional[dict] = None, leg: Optional[str] = None,
            goal: Optional[dict] = None, navigation: object = None) -> dict:
    """``{"state": bounded|unbounded|idle, "motion": lane_trip|goal|None, "reason": ...}``.

    ``trip`` is the robot's open trip view and ``leg`` the drive mode of its current segment;
    ``goal`` is the console goal record and ``navigation`` the robot's last ``state.navigation``.
    """
    leased = isinstance(goal, dict) and goal.get("goal_lease") == "leased"
    if trip is not None:
        lease = trip.get("lease")
        if isinstance(lease, dict) and lease.get("state") == "held":  # D-541: CORE halts on expiry
            return _answer("bounded", "goal" if leg == "free" else "lane_trip")
        if leg == "free":
            return _answer("bounded", "goal") if leased else _answer("unbounded", "goal", "no_goal_lease")
        if leg != "lane":
            return _answer("unbounded", None, "leg_unknown")
        if trip.get("traffic_authority") == "core":  # D-517 4: authority ttl
            return _answer("bounded", "lane_trip")
        return _answer("unbounded", "lane_trip", "hold_back")
    # The record outlives the goal, so only a navigation word that says "over" clears it.
    if goal and not (isinstance(navigation, str) and navigation in ("IDLE", "ARRIVED", "CANCELED", "FAILED")):
        return _answer("bounded", "goal") if leased else _answer("unbounded", "goal", "no_goal_lease")
    return _answer("idle")
