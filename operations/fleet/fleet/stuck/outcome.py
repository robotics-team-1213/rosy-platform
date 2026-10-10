"""D-610 2: the closed loop. After CORE takes an answer, Fleet watches whether the problem went away.

Pure: the caller feeds the gathered rows and a monotonic clock. Outcomes are ``resolved``, ``unresolved``,
``refused`` (CORE said no) and ``superseded`` (a person took it, or an E-stop). Windows: stuck and stalled
20 s, pose_lost and deadlock 30 s. A stuck is resolved when it closed, no new stuck came on that robot inside
the window and, with a map pose at both ends, the robot made 0.10 m net along its heading. ``near_miss``
marks an E-stop or a new ``obstacle_ahead`` stuck after a moving answer (D-610 9 trend input).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

WINDOW_S = {"stuck": 20.0, "stalled": 20.0, "pose_lost": 30.0, "deadlock": 30.0}
MOVED_M = 0.10
MOVING = frozenset({"BACK_AND_RETRY", "RESUME", "YIELD", "REALIGN", "REPLAN"})


@dataclass
class _Open:
    kind: str
    robot_id: str
    problem_id: str
    decision: str
    opened_at: float
    pose: Optional[tuple]


def _pose(row: Mapping) -> Optional[tuple]:
    from fleet.stuck.lane_lost import _trusted_map_pose

    return _trusted_map_pose(row)


def _stuck_id(row: Mapping) -> Optional[str]:
    stuck = ((row.get("state") or {}).get("line_follow") or {}).get("stuck")
    return str(stuck["stuck_id"]) if isinstance(stuck, Mapping) and stuck.get("stuck_id") else None


class Outcomes:
    def __init__(self) -> None:
        self._open: dict[tuple[str, str], _Open] = {}

    def answered(self, kind: str, robot_id: str, problem_id: str, decision: str, code: Optional[str], now: float,
                 row: Optional[Mapping] = None) -> Optional[dict]:
        """CORE's reply to one answer: a ``refused`` outcome now, or a window opens (None)."""
        if code is not None:
            self._open.pop((robot_id, problem_id), None)
            return self._out(kind, robot_id, problem_id, decision, "refused" if code == "STUCK_DECISION_REFUSED"
                             else f"failed:{code}")
        self._open[(robot_id, problem_id)] = _Open(kind, robot_id, problem_id, decision, now,
                                                  _pose(row) if row is not None else None)
        return None

    def supersede(self, robot_id: str, problem_id: str) -> Optional[dict]:
        """A person took the problem (claim, escalation): its window ends without a verdict on the answer."""
        item = self._open.pop((robot_id, problem_id), None)
        return None if item is None else self._out(item.kind, robot_id, problem_id, item.decision, "superseded")

    def check(self, now: float, rows: Iterable[Mapping], *, cycles: frozenset = frozenset(),
              stalled: frozenset = frozenset()) -> list[dict]:
        """Outcomes due this pass. ``cycles``: robots in a wait cycle; ``stalled``: robots still stalled."""
        by_id = {str(row.get("robot_id")): row for row in rows}
        done = []
        for key, item in list(self._open.items()):
            row = by_id.get(item.robot_id)
            if row is None:
                continue
            outcome = self._judge(item, row, now, cycles, stalled)
            if outcome is not None:
                del self._open[key]
                done.append(self._out(item.kind, item.robot_id, item.problem_id, item.decision, *outcome))
        return done

    def _judge(self, item: _Open, row: Mapping, now: float, cycles, stalled) -> Optional[tuple]:
        state = row.get("state") or {}
        if (state.get("safety") or {}).get("estop"):
            return "superseded", item.decision in MOVING
        ended = now - item.opened_at >= WINDOW_S[item.kind]
        if item.kind == "stuck":
            current = _stuck_id(row)
            if current is not None and current != item.problem_id:
                cause = ((state.get("line_follow") or {}).get("stuck") or {}).get("cause")
                return "unresolved", item.decision in MOVING and cause == "obstacle_ahead"
            if not ended:
                return None
            if current is not None:
                return "unresolved", False
            pose = _pose(row)
            if item.pose is not None and pose is not None:
                ahead = ((pose[0] - item.pose[0]) * math.cos(item.pose[2])
                         + (pose[1] - item.pose[1]) * math.sin(item.pose[2]))
                if ahead < MOVED_M:
                    return "unresolved", False
            return "resolved", False
        if item.kind == "pose_lost":
            localized = (row.get("map_pose") or state.get("localization") or {}).get("state") == "LOCALIZED"
            return ("resolved", False) if localized else ("unresolved", False) if ended else None
        gone = item.robot_id not in (cycles if item.kind == "deadlock" else stalled)
        if gone and (ended or item.kind == "stalled"):
            return "resolved", False
        return ("unresolved", False) if ended else None

    @staticmethod
    def _out(kind, robot_id, problem_id, decision, outcome, near_miss=False) -> dict:
        return {"kind": kind, "robot_id": robot_id, "problem_id": problem_id, "decision": decision,
                "outcome": outcome, "near_miss": bool(near_miss)}
