"""D-438 Fleet stuck resolver core: rules first, then (phase 2) a model, then a human.

Pure: the caller feeds console snapshot rows and a monotonic clock, sends the returned
Answers and reports CORE's reply with `result`. CORE re-checks every answer (D-407 §2);
nothing here widens a robot's local-recovery settings.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping, Optional, Union

from fleet.stuck.meet_yield import (
    _YieldPlan,
    _door_xy,
    _gap_target,
    _hold_xy,
    is_door_clear,
    resolve_meet_yield,
    retain_active_pins,
    step_off_paint,
    step_rejoin,
)
from fleet.stuck import pipeline

#: CORE codes that mean "this answer was judged and refused": try the next candidate.
REFUSED = "STUCK_DECISION_REFUSED"
#: The stuck changed under us: drop this answer, re-read state.
MISMATCH = "STUCK_ID_MISMATCH"
#: Transport failures: one resend, then a human; uncertain YIELD is never replayed.
TRANSPORT = ("ROBOT_UNREACHABLE", "STUCK_DECISION_OUTCOME_UNKNOWN")
#: Causes that only ever get WAIT or BACK_AND_RETRY (D-577 1; no_motion = CORE stuck_report_s).
LOST_LIKE = ("lane_lost", "no_motion")


@dataclass(frozen=True)
class ResolverConfig:
    poll_s: float = 1.0
    restuck_s: float = 30.0
    rule_budget: int = 2
    escalate_after_s: float = 60.0
    peer_reach_m: float = 0.30
    # Own URDF half width (0.057 m) + a peer's rotation radius (0.083 m), rounded up.
    # ponytail: one body size for every robot; read per-robot geometry when kinds differ.
    peer_band_half_width_m: float = 0.15
    peer_radius_m: float = 0.083          # reach is measured to the peer's body, not its centre
    #: D-577 1: R3 trusts a known Fleet map pose only while it is LOCALIZED and this fresh.
    pose_max_age_s: float = 2.0
    #: D-577 개정 2026-10-10: how long a stuck waits for an AI PC proposal before the rules answer.
    ai_wait_s: float = 12.0


@dataclass(frozen=True)
class Answer:
    robot_id: str
    stuck_id: str
    decision: str
    rule: str
    # D-453: one yield segment. None on WAIT / BACK_AND_RETRY / RESUME.
    yield_m: Optional[float] = None
    yield_turn_rad: Optional[float] = None
    # D-577 1: R5 sends this WAIT and hands the stuck to a human in the same pass.
    escalate: Optional[str] = None
    realign: Optional[dict] = None


@dataclass(frozen=True)
class Escalate:
    robot_id: str
    stuck_id: str
    reason: str


@dataclass(frozen=True)
class Hold(Escalate):
    """Autonomous observation retains ownership; no human claim or implicit retry."""


Action = Union[Answer, Escalate]


@dataclass
class _Chain:
    started_at: float
    mode: str
    stuck_id: Optional[str] = None
    closed_at: Optional[float] = None
    rule_answers: int = 0
    realign_attempts: int = 0
    # Phase 2 (model tier) only: phase-1 rules never answer RESUME, so this stays None.
    resume_id: Optional[str] = None                  # stuck id the resolver answered RESUME
    retired: set = field(default_factory=set)
    answered: set = field(default_factory=set)       # stuck ids with an answer in flight/done
    retries: dict = field(default_factory=dict)      # stuck id -> transport resends
    escalated: set = field(default_factory=set)      # stuck ids already escalated
    seen_at: float = 0.0                             # when the current stuck id was first seen
    ai_judged: set = field(default_factory=set)      # (stuck id, decision, reason) proposals judged
    held: dict = field(default_factory=dict)         # stuck id -> R5 escalation sent (D-577 남은 항목 2)
    observing: Optional[str] = None
    unresolved: set = field(default_factory=set)


def _stuck_of(row: Mapping) -> Optional[dict]:
    lf = (row.get("state") or {}).get("line_follow") or {}
    stuck = lf.get("stuck")
    return stuck if isinstance(stuck, dict) and stuck.get("stuck_id") else None


def _mode_of(row: Mapping) -> str:
    return str(((row.get("state") or {}).get("line_follow") or {}).get("mode") or "")


class StuckResolver:
    def __init__(self, config: ResolverConfig, *, painted: Optional[Callable[[], object]] = None,
                 realign=None, wall: Callable[[], float] = time.time) -> None:
        """``painted()`` is the active site map's ``Painted`` (D-488) or None: no meet rules."""
        self.config = config
        from fleet.stuck.realign import RealignConfig
        self.realign, self._wall = realign or RealignConfig(), wall
        self._painted = painted or (lambda: None)
        self._warned_no_map = False
        self._chains: dict[str, _Chain] = {}
        self._claims: set[tuple[str, str]] = set()
        self._pins: dict[str, str] = {}
        self._plans: dict[str, _YieldPlan] = {}
        self._sent_yield: dict[str, tuple] = {}
        self.ai_verdicts: list[dict] = []            # judged AI proposals; the loop drains them to the audit
        #: D-573 개정 2026-10-10: robot_id -> on / at a mapped crosswalk (the lane monitor's view).
        self.at_crosswalk: Callable[[str], bool] = lambda robot_id: False
        self.ai_first = None                          # D-610 3: `ai_first.AiFirst` (app.py), None = D-577 only
        self.autonomous_robots: frozenset[str] = frozenset()
        self._uncertain: set[tuple[str, str]] = set()

    # ---- inputs -----------------------------------------------------------------------

    def claim(self, robot_id: str, stuck_id: str) -> None:
        """A human opened this stuck's decision (D-438 §1): the resolver stays silent."""
        self._claims.add((robot_id, stuck_id))

    def is_claimed(self, robot_id: str, stuck_id: str) -> bool:
        return (robot_id, stuck_id) in self._claims

    def sent(self, answer: Answer, now: float) -> None:
        chain = self._chains.get(answer.robot_id)
        if chain is None:
            chain = self._chains[answer.robot_id] = _Chain(started_at=now, mode="")
        chain.answered.add(answer.stuck_id)
        if answer.decision == "REALIGN":
            chain.realign_attempts += 1
        if answer.rule == "R5":
            chain.held[answer.stuck_id] = answer.escalate
        if answer.decision == "YIELD" and answer.yield_m is not None:
            self._sent_yield[answer.robot_id] = (
                answer.stuck_id, round(answer.yield_turn_rad or 0.0, 3), round(answer.yield_m, 3))
        if ((answer.rule.startswith("R") and answer.rule != "R5"   # D-577 1: R5 stops, spends no budget
             or answer.rule in {"ai", "model_v2"} and answer.decision != "WAIT")
                and chain.retries.get(answer.stuck_id, 0) == 0):
            chain.rule_answers += 1                   # a transport resend is the same answer
        if answer.decision == "RESUME" and answer.rule != "meet" and not (    # D-610 2: a re-stuck goes back to the AI
                answer.rule == "ai" and self.ai_first is not None and self.ai_first.on(answer.robot_id)):
            chain.resume_id = answer.stuck_id

    def result(self, answer: Answer, *, code: Optional[str]) -> Optional[Escalate]:
        """CORE's reply: None code = accepted. Returns an escalation when one is due."""
        chain = self._chains.get(answer.robot_id)
        if chain is None:
            return None
        if answer.robot_id in self.autonomous_robots and code is None and answer.decision == "WAIT":
            return self._escalate(chain, answer.robot_id, answer.stuck_id, answer.escalate or "waiting")
        if (answer.robot_id in self.autonomous_robots and code == "STUCK_DECISION_OUTCOME_UNKNOWN"
                and answer.decision != "WAIT"):
            self._uncertain.add((answer.robot_id, answer.stuck_id))
            return self._escalate(chain, answer.robot_id, answer.stuck_id, f"core:{code}")
        if code is None and answer.escalate is None:
            if answer.decision == "RESUME" and answer.rule == "meet":
                chain.resume_id = answer.stuck_id
                self._plans.pop(answer.robot_id, None)
                self._pins = {edge: yielder for edge, yielder in self._pins.items()
                              if yielder != answer.robot_id}
            return None
        if code == MISMATCH:
            return None
        if answer.escalate is not None:               # D-577 1 R5: WAIT, then a human whatever CORE said
            if code in TRANSPORT and chain.retries.get(answer.stuck_id, 0) == 0:
                chain.retries[answer.stuck_id] = 1    # WAIT stops; resending it once is safe
                chain.answered.discard(answer.stuck_id)
                return None
            reason = (f"core:{code}" if answer.robot_id in self.autonomous_robots and code
                      and not answer.escalate.startswith("realign_hold:") else answer.escalate)
            return self._escalate(chain, answer.robot_id, answer.stuck_id, reason)
        if answer.stuck_id != chain.stuck_id and answer.stuck_id not in chain.answered:
            return None                               # late reply from an older chain
        if code == REFUSED:
            # The robot is still in YIELDED. Retry the return on the next poll.
            if answer.decision == "RESUME" and answer.rule == "meet":
                return None
            chain.retired.add(answer.rule)
            chain.answered.discard(answer.stuck_id)
            return None
        if code in TRANSPORT and answer.decision == "REALIGN":
            return self._escalate(chain, answer.robot_id, answer.stuck_id, f"core:{code}")
        if code == "STUCK_DECISION_OUTCOME_UNKNOWN" and answer.decision == "YIELD":
            # CORE may already have completed this segment. A replay can restart motion.
            return self._escalate(chain, answer.robot_id, answer.stuck_id, f"core:{code}")
        if code in TRANSPORT and chain.retries.get(answer.stuck_id, 0) == 0:
            chain.retries[answer.stuck_id] = 1
            chain.answered.discard(answer.stuck_id)
            return None
        return self._escalate(chain, answer.robot_id, answer.stuck_id, f"core:{code}")

    # ---- decision ---------------------------------------------------------------------

    def step(self, now: float, rows: Iterable[Mapping]) -> list[Action]:
        rows = [r for r in rows if isinstance(r, Mapping) and r.get("robot_id")]
        present = {str(r["robot_id"]) for r in rows}         # rows are the full roster
        for rid in set(self._chains) - present:
            del self._chains[rid]
        self._claims = {c for c in self._claims if c[0] in present}
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
        if chain is not None and (mode and chain.mode and mode != chain.mode
                                  and not (rid in self.autonomous_robots and stuck is not None
                                           and chain.stuck_id == str(stuck["stuck_id"]))
                                  or (chain.closed_at is not None
                                      and now - chain.closed_at > self.config.restuck_s)):
            del self._chains[rid]                  # mode changed or the window passed
            if chain.closed_at is not None:        # a human's claim lives while its stuck is open
                self._claims = {c for c in self._claims if c[0] != rid}
            chain = None
        if stuck is None:
            self._plans.pop(rid, None)
            if chain is not None and chain.closed_at is None:
                chain.closed_at, chain.stuck_id = now, None
            return None
        sid = str(stuck["stuck_id"])
        if chain is None:
            chain = self._chains[rid] = _Chain(started_at=now, mode=mode)
        elif not chain.mode:
            chain.mode = mode
        if chain.stuck_id != sid:
            chain.stuck_id, chain.closed_at, chain.seen_at = sid, None, now
            chain.observing = None
            if chain.resume_id is not None and sid != chain.resume_id:
                return self._escalate(chain, rid, sid, "restuck_after_resume")
        if (rid, sid) in self._claims or sid in chain.escalated:
            return None
        continuation_hold = self._continuation_hold(rid, chain)
        if continuation_hold == "core:STUCK_DECISION_OUTCOME_UNKNOWN":
            return self._escalate(chain, rid, sid, "core:STUCK_DECISION_OUTCOME_UNKNOWN")
        if continuation_hold is not None:
            return None  # Preserve uncertainty and exhausted budgets even across another hold.
        hold = pipeline.law_hold(row)
        if hold is not None:
            return self._escalate(chain, rid, sid, hold)
        if now - chain.started_at > self.config.escalate_after_s:
            return self._escalate(chain, rid, sid, "deadline")
        if rid in self.autonomous_robots and chain.observing is not None:
            # A changed clock is not recovery evidence; only a newly admissible candidate reopens WAIT.
            if stuck.get("phase") == "YIELDED":
                if chain.rule_answers >= self.config.rule_budget:
                    return self._escalate(chain, rid, sid, "rule_budget")
                action = self._next_segment(row, rows)
            elif stuck.get("phase") in ("ASKING", "WAITING_CONSOLE"):
                action = pipeline.candidate(self, now, row, stuck, rows, chain)
            else:
                return None
            if not isinstance(action, Answer) or action.decision == "WAIT":
                return action if isinstance(action, Escalate) else None
            if action.decision in chain.unresolved:
                return None
            chain.answered.discard(sid)
            chain.held.pop(sid, None)
            chain.observing = None
            return action
        from fleet.stuck.lane_lost import ai_late

        if sid in chain.answered:
            ai_late(self, now, row, chain)
            return self._next_segment(row, rows)
        if sid in chain.held:                         # D-577 남은 항목 2: a resent R5 stays R5, never R3
            return Answer(rid, sid, "WAIT", "R5", escalate=chain.held[sid])
        return pipeline.candidate(self, now, row, stuck, rows, chain)

    def _continuation_hold(self, rid: str, chain: _Chain) -> Optional[str]:
        if rid in self.autonomous_robots:
            if any(robot == rid for robot, _case in self._uncertain):
                return "core:STUCK_DECISION_OUTCOME_UNKNOWN"
            if chain.observing is not None and (chain.observing.startswith("core:")
                    or chain.observing in ("rule_budget", "deadline", "ai_exhausted", "ai_oscillation")):
                return chain.observing
        return None

    def _escalate(self, chain: _Chain, rid: str, sid: str, reason: str) -> Escalate:
        if rid in self.autonomous_robots and not reason.startswith(("human_class:", "realign_hold:")) and (
                reason not in ("ai_manual", "no_resolver_token")):   # D-622: a REALIGN hold goes to a human
            if chain.observing == reason:
                return None
            chain.observing = reason
            return Hold(rid, sid, reason)
        chain.escalated.add(sid)
        return Escalate(rid, sid, reason)

    # ---- rules (D-438 §2) -------------------------------------------------------------

    def _rule(self, row, stuck, rows, chain) -> Optional[tuple[str, str]]:
        cause = stuck.get("cause")
        peer = cause == "obstacle_ahead" and self._peer_ahead(row, rows)
        if peer is None:  # D-577 남은 항목 4: no trusted map pose; neither R1 nor a blind back-off
            return ("R5", "WAIT", "peer_unknown")
        if row.get("trip"):
            # D-517 5 (M4): a trip robot gets only the stopping R1 WAIT. A back-off, yield or resume could
            # take its body into a block the table already released behind it or never granted (D-494 14);
            # CORE's own site-evidence retrace (D-507 6) stays local. Anything else goes to a human.
            return ("R1", "WAIT") if peer and "R1" not in chain.retired else None
        can_back = (bool(stuck.get("local_enabled"))
                    and int(stuck.get("attempts") or 0) < int(stuck.get("max_attempts") or 0))
        if peer and "meet" not in chain.retired:
            meet = self._meet(row, rows)
            if meet is not None:
                return meet
        candidates = []
        if peer:
            candidates.append(("R1", "WAIT"))
        if cause == "obstacle_ahead" and not peer and can_back:
            candidates.append(("R2", "BACK_AND_RETRY"))
        if cause in LOST_LIKE:
            from fleet.stuck.lane_lost import lane_lost_hold

            # no_motion (2026-10-10, any zero-command reason >= stuck_report_s): R6 = R3's back-off
            # and look again under R3's preconditions; CORE re-checks the rear (D-407 §4).
            hold = lane_lost_hold(row, stuck, rows, chain, self.config, painted=self._painted(),
                                  rule="R3" if cause == "lane_lost" else "R6")
            if hold is None:
                return ("R3" if cause == "lane_lost" else "R6", "BACK_AND_RETRY")
            return ("R5", "WAIT", hold)
        if peer and can_back:
            candidates.append(("R2", "BACK_AND_RETRY"))      # after a refused WAIT
        for rule in candidates:
            if rule[0] not in chain.retired:
                return rule
        return None

    def _next_segment(self, row, rows) -> Optional[Answer]:
        """The robot finished one segment and is holding off the resume path."""
        stuck = _stuck_of(row)
        if stuck is None or stuck.get("phase") != "YIELDED" or stuck.get("cause") in LOST_LIKE:
            return None
        meet = self._meet(row, rows)
        if meet is None:
            return None
        rid = str(row["robot_id"])
        sid = str(stuck["stuck_id"])
        if meet[1] == "RESUME":
            return Answer(rid, sid, "RESUME", "meet")
        if len(meet) != 4:
            return None
        key = (sid, round(meet[2], 3), round(meet[3], 3))
        if self._sent_yield.get(rid) == key:
            return None
        return Answer(rid, sid, "YIELD", "meet", yield_m=meet[3], yield_turn_rad=meet[2])

    def _meet(self, row, rows):
        return resolve_meet_yield(self, row, rows)

    def _off_paint(self, pose, plan, painted, rows, rid):
        return step_off_paint(self, pose, plan, painted, rows, rid)

    def _rejoin(self, row, mine, plan, painted, rows, rid):
        return step_rejoin(self, row, mine, plan, painted, rows, rid)

    def _door_clear(self, plan, painted, rows, rid) -> bool:
        return is_door_clear(self, plan, painted, rows, rid)

    def _keep_pins(self, scene, orders) -> None:
        retain_active_pins(self, scene, orders)

    def _peer_ahead(self, row, rows) -> Optional[bool]:
        from fleet.stuck.lane_lost import peer_ahead

        return peer_ahead(row, rows, self.config)

