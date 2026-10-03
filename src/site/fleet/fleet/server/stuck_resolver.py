"""D-438 Fleet stuck resolver core: rules first, then (phase 2) a model, then a human.

Pure: the caller feeds console snapshot rows and a monotonic clock, sends the returned
Answers and reports CORE's reply with `result`. CORE re-checks every answer (D-407 §2);
nothing here widens a robot's local-recovery settings.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional, Union

#: CORE codes that mean "this answer was judged and refused": try the next candidate.
REFUSED = "STUCK_DECISION_REFUSED"
#: The stuck changed under us: drop this answer, re-read state.
MISMATCH = "STUCK_ID_MISMATCH"
#: Transport failures: one resend, then a human.
TRANSPORT = ("ROBOT_UNREACHABLE", "STUCK_DECISION_OUTCOME_UNKNOWN")


@dataclass(frozen=True)
class ResolverConfig:
    poll_s: float = 1.0
    restuck_s: float = 30.0
    rule_budget: int = 2
    escalate_after_s: float = 60.0
    peer_reach_m: float = 0.30
    # Own half width (Pinky 0.057 m) + a peer's rotation radius (0.083 m), rounded up.
    # ponytail: one body size for every robot; read per-robot geometry when kinds differ.
    peer_band_half_width_m: float = 0.15


@dataclass(frozen=True)
class Answer:
    robot_id: str
    stuck_id: str
    decision: str
    rule: str


@dataclass(frozen=True)
class Escalate:
    robot_id: str
    stuck_id: str
    reason: str


Action = Union[Answer, Escalate]


@dataclass
class _Chain:
    started_at: float
    mode: str
    stuck_id: Optional[str] = None
    closed_at: Optional[float] = None
    rule_answers: int = 0
    resumed: bool = False
    retired: set = field(default_factory=set)
    answered: set = field(default_factory=set)       # stuck ids with an answer in flight/done
    retries: dict = field(default_factory=dict)      # stuck id -> transport resends
    escalated: set = field(default_factory=set)      # stuck ids already escalated
    claimed: set = field(default_factory=set)        # stuck ids a human owns


def _stuck_of(row: Mapping) -> Optional[dict]:
    lf = (row.get("state") or {}).get("line_follow") or {}
    stuck = lf.get("stuck")
    return stuck if isinstance(stuck, dict) and stuck.get("stuck_id") else None


def _mode_of(row: Mapping) -> str:
    return str(((row.get("state") or {}).get("line_follow") or {}).get("mode") or "OFF")


def _pose_of(row: Mapping) -> Optional[tuple[float, float, float]]:
    pose = (row.get("state") or {}).get("pose") or {}
    try:
        return float(pose["x"]), float(pose["y"]), float(pose.get("yaw", 0.0))
    except (KeyError, TypeError, ValueError):
        return None


class StuckResolver:
    def __init__(self, config: ResolverConfig) -> None:
        self.config = config
        self._chains: dict[str, _Chain] = {}
        self._claims: set[tuple[str, str]] = set()

    # ---- inputs -----------------------------------------------------------------------

    def claim(self, robot_id: str, stuck_id: str) -> None:
        """A human opened this stuck's decision (D-438 §1): the resolver stays silent."""
        self._claims.add((robot_id, stuck_id))

    def sent(self, answer: Answer, now: float) -> None:
        chain = self._chains.get(answer.robot_id)
        if chain is None:
            chain = self._chains[answer.robot_id] = _Chain(started_at=now, mode="")
        chain.answered.add(answer.stuck_id)
        if answer.rule.startswith("R"):
            chain.rule_answers += 1
        if answer.decision == "RESUME":
            chain.resumed = True

    def result(self, answer: Answer, *, code: Optional[str]) -> Optional[Escalate]:
        """CORE's reply: None code = accepted. Returns an escalation when one is due."""
        chain = self._chains.get(answer.robot_id)
        if chain is None or code is None or code == MISMATCH:
            return None
        if code == REFUSED:
            chain.retired.add(answer.rule)
            chain.answered.discard(answer.stuck_id)
            return None
        if code in TRANSPORT and chain.retries.get(answer.stuck_id, 0) == 0:
            chain.retries[answer.stuck_id] = 1
            chain.answered.discard(answer.stuck_id)
            return None
        chain.escalated.add(answer.stuck_id)
        return Escalate(answer.robot_id, answer.stuck_id, f"core:{code}")

    # ---- decision ---------------------------------------------------------------------

    def step(self, now: float, rows: Iterable[Mapping]) -> list[Action]:
        rows = [r for r in rows if isinstance(r, Mapping) and r.get("robot_id")]
        actions: list[Action] = []
        for row in rows:
            action = self._one(now, row, rows)
            if action is not None:
                actions.append(action)
        return actions

    def _one(self, now: float, row: Mapping, rows: list) -> Optional[Action]:
        rid = str(row["robot_id"])
        if not row.get("online", True):
            return None
        stuck, mode = _stuck_of(row), _mode_of(row)
        chain = self._chains.get(rid)
        if chain is not None and (mode != chain.mode and chain.mode
                                  or (chain.closed_at is not None
                                      and now - chain.closed_at > self.config.restuck_s)):
            chain = self._chains.pop(rid)          # mode changed or the window passed
            chain = None
        if stuck is None:
            if chain is not None and chain.closed_at is None:
                chain.closed_at, chain.stuck_id = now, None
            return None
        sid = str(stuck["stuck_id"])
        if chain is None:
            chain = self._chains[rid] = _Chain(started_at=now, mode=mode)
        elif not chain.mode:
            chain.mode = mode
        if chain.stuck_id != sid:
            new = chain.stuck_id is None and chain.closed_at is not None
            chain.stuck_id, chain.closed_at = sid, None
            if new and chain.resumed:
                return self._escalate(chain, rid, sid, "restuck_after_resume")
        if (rid, sid) in self._claims or sid in chain.escalated:
            return None
        if ((row.get("state") or {}).get("safety") or {}).get("estop"):
            return self._escalate(chain, rid, sid, "estop")
        if now - chain.started_at > self.config.escalate_after_s:
            return self._escalate(chain, rid, sid, "deadline")
        if sid in chain.answered:
            return None
        rule = self._rule(row, stuck, rows, chain)
        if rule is None:
            return self._escalate(chain, rid, sid, "no_rule")
        if chain.rule_answers >= self.config.rule_budget:
            return self._escalate(chain, rid, sid, "rule_budget")
        return Answer(rid, sid, rule[1], rule[0])

    def _escalate(self, chain: _Chain, rid: str, sid: str, reason: str) -> Escalate:
        chain.escalated.add(sid)
        return Escalate(rid, sid, reason)

    # ---- rules (D-438 §2) -------------------------------------------------------------

    def _rule(self, row, stuck, rows, chain) -> Optional[tuple[str, str]]:
        cause = stuck.get("cause")
        can_back = (bool(stuck.get("local_enabled"))
                    and int(stuck.get("attempts") or 0) < int(stuck.get("max_attempts") or 0))
        peer = cause == "obstacle_ahead" and self._peer_ahead(row, rows)
        candidates = []
        if peer:
            candidates.append(("R1", "WAIT"))
        if cause == "obstacle_ahead" and not peer and can_back:
            candidates.append(("R2", "BACK_AND_RETRY"))
        if cause == "lane_lost" and can_back:
            candidates.append(("R3", "BACK_AND_RETRY"))
        if peer and can_back:
            candidates.append(("R2", "BACK_AND_RETRY"))      # after a refused WAIT
        for rule in candidates:
            if rule[0] not in chain.retired:
                return rule
        return None

    def _peer_ahead(self, row, rows) -> bool:
        me = _pose_of(row)
        if me is None:
            return False
        x0, y0, yaw = me
        c, s = math.cos(yaw), math.sin(yaw)
        for other in rows:
            if other is row or not other.get("online", True):
                continue
            pose = _pose_of(other)
            if pose is None:
                continue
            dx, dy = pose[0] - x0, pose[1] - y0
            ahead, side = c * dx + s * dy, -s * dx + c * dy
            if 0.0 < ahead <= self.config.peer_reach_m and abs(side) <= self.config.peer_band_half_width_m:
                return True
        return False
