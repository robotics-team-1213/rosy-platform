"""D-517 5 (M4): Fleet's resolver for trip robots the block table cannot move. Pure: no clock, no robot.

The robot resolves locally first (CORE body stop, D-407 stuck with the R1 WAIT answer). The table hands a
robot over when it waits in a cycle or holds an UNKNOWN unit for ``UNKNOWN_LIMIT_S``. Decisions:

- A cycle must persist ``CYCLE_PERIODS`` periods before a replan is chosen: ``wait_cycle`` counts any
  holder, so a holder about to leave can close a cycle for one period (review M2).
- ``replan``: one robot of a cycle is planned again from its next place with the edges of the unit it
  waits for closed (D-490 ``blocked``). A changed route stands at that place for an operator's
  confirmation (D-489 9 ``replan_hold``); Fleet never switches a route by itself. The others ``wait``.
  The rows stay so while that hold waits for the operator.
- ``human``: no cycle member can leave before the unit it waits for (that unit is on its current lane,
  or it is on its last segment), a replan was already asked for on this route, or the pose is UNKNOWN.
"""

from __future__ import annotations

from typing import Mapping, Optional, Sequence

UNKNOWN_LIMIT_S = 30.0
#: 3 trip periods (1.5 s): longer than a holder needs to leave a one-period cycle, far below the 20 s stall.
CYCLE_PERIODS = 3


def decide(cycle: Optional[Sequence[str]], periods: int, avoidable: Mapping[str, Sequence[str]],
           tried: Mapping[str, Sequence[str]], pending: set, unknown_since: Mapping[str, float], now: float, *,
           unknown_limit_s: float = UNKNOWN_LIMIT_S) -> dict[str, dict]:
    """``{robot id: {trigger, decision, ...}}`` for every robot handed over this period.

    ``periods``: how many periods in a row this cycle was seen; ``avoidable``: robot id -> edges it
    may be planned around (empty: it cannot leave first); ``tried``: robot id -> edges of the replan
    already given on its current route; ``pending``: robots whose replan hold waits for an operator.
    """
    out = {robot_id: {"trigger": "unknown", "decision": "human", "since": since}
           for robot_id, since in unknown_since.items() if now - since > unknown_limit_s}
    if not cycle:
        return out
    members = sorted(cycle)
    held = next((r for r in members if r in pending and r in tried), None)
    if held is not None:
        pick, edges = held, tried[held]
    elif periods < CYCLE_PERIODS:
        return out
    elif any(r in tried or r in out for r in members):
        pick, edges = None, ()
    else:
        pick = next((r for r in members if avoidable.get(r)), None)
        edges = avoidable.get(pick, ())
    for robot_id in members:
        row = {"trigger": "wait_cycle", "cycle": list(cycle),
               "decision": "replan" if robot_id == pick else "wait" if pick else "human"}
        if robot_id == pick:
            row["blocked_edges"] = sorted(edges)
        out.setdefault(robot_id, row)
    return out
