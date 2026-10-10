"""D-610 1·2·3·5: AI-first robots. Fleet checks a VLM answer's shape and evidence, then sends it.

Pure beside ``resolver.py``: ``StuckResolver._one`` calls ``ai_answer``. A robot outside ``fleet.ai_first.robots``
(default empty), with the console switch off, or a proposal that is not ``vlm:`` keeps the D-577 path
(``lane_lost.ai_answer``) with every gate. The physical last line (CORE body stop, LiDAR stop, 300 ms watchdog,
E-stop latch, CORE re-check, D-541 lease, D-517 authority) runs on the robot; nothing here reaches it. The resolver
escalates an E-stop before this runs, and never sends with a trip owner's credential (its clients are the
stuck-resolver tokens), so a trip robot gets no moving AI answer.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Callable, Iterable, Mapping, Optional

from fleet.stuck.resolver import LOST_LIKE, Answer

#: D-610 3 (rosy-b3 2026-10-10): the D-577 gates an AI-first robot can keep, by name.
GATES = ("ai_words", "trip_wait_only", "crosswalk", "trusted_pose", "r3_preconditions", "acting_fact_hold",
         "abort_requires_crosswalk_null")
#: D-610 3: kept on an AI-first robot unless its keep_gates says otherwise (until a Gazebo trip set + Safety-Review).
DEFAULT_KEEP = frozenset({"trip_wait_only"})
MOVING = frozenset({"BACK_AND_RETRY", "RESUME", "YIELD", "REALIGN"})
#: D-610 4: a VLM stuck answer. REALIGN joins with D-607's CORE contract (not on main yet).
STUCK_WORDS = frozenset({"WAIT", "BACK_AND_RETRY", "RESUME", "ABORT", "YIELD", "MANUAL"})
#: D-610 4: CORE's D-573 gate object states in which an AI RESUME means "go once the gate's scan passes".
GATE_STATES = frozenset({"armed", "approaching", "looking", "waiting"})
MAX_AGE_S = {"rosy_cam": 2.0, "front": 3.0}           # D-610 5
PER_PROBLEM, PER_HOUR = 3, 6                          # D-610 2
VLM_WAIT_S = 12.0                                     # D-619: 10 s inference plus delivery.
OPPOSITE = {"BACK_AND_RETRY": "RESUME", "RESUME": "BACK_AND_RETRY"}


class AiFirst:
    """Site config ``fleet.ai_first`` plus the console switch (memory; a restart reads the config again)."""

    def __init__(self, robots: Iterable[str] = (), keep_gates: Optional[Mapping[str, Iterable[str]]] = None, *,
                 wall: Callable[[], float] = time.time) -> None:
        self.robots = frozenset(robots)
        self.keep_gates = {rid: frozenset(names) for rid, names in (keep_gates or {}).items()}
        self.enabled = True
        self.wall = wall
        self.profiles: Callable[[], Iterable[str]] = lambda: ()      # heartbeat model_profiles (app.py)
        self.human_classes: Callable[[], frozenset] = frozenset      # D-610 9 active keys (app.py)
        self._answers: dict[tuple, list] = {}                        # (robot, problem) -> AI decisions sent
        self._moves: dict[str, deque] = {}                           # robot -> monotonic times of moving AI answers
        self._refused: set = set()                                   # (robot, problem, decision) CORE refused

    @classmethod
    def from_config(cls, section: Optional[Mapping]) -> "AiFirst":
        """``fleet.ai_first: {robots: [id...], keep_gates: {id: [gate...]}}``; ValueError on a bad shape."""
        section = section or {}
        robots, keep = section.get("robots") or [], section.get("keep_gates") or {}
        if not isinstance(robots, list) or not all(isinstance(r, str) and r for r in robots):
            raise ValueError("fleet.ai_first.robots must be a list of robot ids")
        if not isinstance(keep, Mapping) or not all(
                isinstance(names, list) and set(names) <= set(GATES) for names in keep.values()):
            raise ValueError(f"fleet.ai_first.keep_gates must map robot ids to gate names {GATES}")
        return cls(robots, keep)

    def on(self, robot_id: str) -> bool:
        return self.enabled and robot_id in self.robots

    def gate(self, robot_id: str, name: str) -> bool:
        """True where the D-577 gate still applies: every robot outside AI-first, and kept gates."""
        return not self.on(robot_id) or name in self.keep_gates.get(robot_id, DEFAULT_KEEP)

    def view(self) -> dict:
        return {"enabled": self.enabled, "robots": sorted(self.robots),
                "keep_gates": {rid: sorted(self.keep_gates.get(rid, DEFAULT_KEEP)) for rid in sorted(self.robots)}}

    def refused(self, robot_id: str, problem, decision: str) -> None:
        self._refused.add((robot_id, problem, decision))

    def limit(self, robot_id: str, problem, decision: str, now: float) -> Optional[str]:
        """D-610 2: the escalation reason once a problem or robot has had enough AI answers, else None."""
        sent = self._answers.get((robot_id, problem), [])
        if len(sent) >= PER_PROBLEM:
            return "ai_exhausted"
        moves = self._moves.setdefault(robot_id, deque())
        while moves and now - moves[0] >= 3600.0:
            moves.popleft()
        if decision in MOVING and len(moves) >= PER_HOUR:
            return "ai_hourly_cap"
        moving = [d for d in sent if d in MOVING]
        if (decision in MOVING and len(moving) >= 2 and OPPOSITE.get(decision) == moving[-1]
                and moving[-2] == decision):
            return "ai_oscillation"
        return None

    def sent(self, robot_id: str, problem, decision: str, now: float) -> None:
        self._answers.setdefault((robot_id, problem), []).append(decision)
        if decision in MOVING:
            self._moves.setdefault(robot_id, deque()).append(now)
        if len(self._answers) > 256:                                 # ponytail: oldest problems go first
            self._answers.pop(next(iter(self._answers)))

    def evidence_invalid(self, proposal: Mapping, robot_id: str) -> Optional[str]:
        """D-610 5: both views cited and fresh by Fleet's wall clock, a map pose state, a loaded profile."""
        evidence = proposal.get("evidence") or {}
        views, wall = evidence.get("views") or {}, self.wall()
        for view, limit in MAX_AGE_S.items():
            cited = views.get(view)
            if (not isinstance(cited, Mapping) or not cited.get("frame_id")
                    or not isinstance(cited.get("captured_at"), (int, float))):
                return f"evidence_missing:{view}"
            if not -1.0 <= wall - cited["captured_at"] <= limit:
                return f"evidence_stale:{view}"
        pose = evidence.get("map_pose")
        if not isinstance(pose, Mapping) or not pose.get("state"):
            return "evidence_missing:map_pose"
        if str(proposal.get("source", ""))[4:] not in set(self.profiles()):
            return "profile_unknown"
        return None


def problem_key(row: Mapping, kind: str, cause, at_crosswalk: bool) -> str:
    """D-610 9 type key ``<kind>:<cause>:<place>``. ponytail: no turn_spot/off_lane until a site-map place lookup."""
    from fleet.stuck.lane_lost import _trusted_map_pose

    crosswalk = ((row.get("state") or {}).get("line_follow") or {}).get("crosswalk")
    place = ("crosswalk" if crosswalk is not None or at_crosswalk
             else "lane" if _trusted_map_pose(row) is not None else "unknown")
    return f"{kind}:{cause or 'none'}:{place}"


def ai_answer(resolver, now, row, stuck, rows, chain):
    """``lane_lost.ai_answer``'s contract: an Answer, "wait" while the AI PC has time, or None (rules)."""
    from fleet.stuck import lane_lost

    first, rid, sid = resolver.ai_first, str(row["robot_id"]), str(stuck["stuck_id"])
    if first is None or not first.on(rid):
        return lane_lost.ai_answer(resolver, now, row, stuck, rows, chain)
    problem = chain.started_at                         # one problem = one resolver chain (re-stucks included)
    key = problem_key(row, "stuck", stuck.get("cause"), resolver.at_crosswalk(rid))
    if key in first.human_classes():
        return Answer(rid, sid, "WAIT", "ai", escalate=f"human_class:{key}")
    proposal = row.get("ai_proposal")
    if proposal is None or proposal.get("stuck_id") != sid or not str(proposal.get("source", "")).startswith("vlm:"):
        if proposal is None and row.get("ai_wait") and set(first.profiles()) and now - chain.seen_at < VLM_WAIT_S:
            return "wait"
        answer = lane_lost.ai_answer(resolver, now, row, stuck, rows, chain)   # analyzer: every D-577 gate
        return _counted(first, rid, problem, answer, now)
    judged = (proposal["stuck_id"], proposal["decision"], proposal["reason"])
    if judged in chain.ai_judged:
        return None
    chain.ai_judged.add(judged)
    notes: list[str] = []
    verdict, answer = _check(resolver, first, proposal, row, stuck, rows, chain, problem, now, notes)
    resolver.ai_verdicts.append({**proposal, "verdict": verdict, "judged_at": time.time(), "floor": notes})
    return _counted(first, rid, problem, answer, now)


def _counted(first: AiFirst, rid: str, problem, answer, now: float):
    if (isinstance(answer, Answer) and answer.rule == "ai"
            and (answer.escalate is None or answer.escalate.startswith("ai_wait:"))):
        first.sent(rid, problem, answer.decision, now)
    return answer


def _check(resolver, first, proposal, row, stuck, rows, chain, problem, now, notes):
    """(verdict, Answer or None). None = the rules answer; an escalating WAIT = a human."""
    rid, sid, decision = str(row["robot_id"]), str(stuck["stuck_id"]), proposal["decision"]
    if decision not in STUCK_WORDS:
        return "word_not_allowed", None
    missing = first.evidence_invalid(proposal, rid)
    if missing is not None:
        return missing, None
    if (rid, problem, decision) in first._refused:
        return "core_refused_before", None
    limit = first.limit(rid, problem, decision, now)
    if limit is not None:
        return limit, Answer(rid, sid, "WAIT", "ai", escalate=limit)
    if decision == "MANUAL":
        return "ai_manual", Answer(rid, sid, "WAIT", "ai", escalate="ai_manual")
    if row.get("trip") and decision in MOVING:        # the trip runner owns the lease; this resolver never moves it
        return "trip", None
    for gate, reason in _gate_holds(resolver, proposal, row, stuck, rows, chain):
        if first.gate(rid, gate):
            return reason, None
        notes.append(f"floor_would_hold:{gate}:{reason}")
    line_follow = (row.get("state") or {}).get("line_follow") or {}
    crosswalk = line_follow.get("crosswalk", {"state": "unknown"})
    near = crosswalk is not None or resolver.at_crosswalk(rid)
    if decision == "RESUME" and near and not (isinstance(crosswalk, Mapping) and crosswalk.get("state") in GATE_STATES):
        notes.append("floor_would_hold:crosswalk:gate_off")   # no CORE gate scan to re-check this RESUME
        return "crosswalk_human", Answer(rid, sid, "WAIT", "ai", escalate="crosswalk_human")
    if decision == "YIELD":
        meet = resolver._meet(row, rows)                    # Fleet's meet geometry or nothing (D-610 4)
        if meet is None or len(meet) != 4:
            return "yield_no_geometry", None
        return "forwarded", Answer(rid, sid, "YIELD", "ai", yield_m=meet[3], yield_turn_rad=meet[2])
    return "forwarded", Answer(rid, sid, decision, "ai",
                               escalate=f"ai_wait:{proposal['reason']}" if decision == "WAIT" else None)


def _gate_holds(resolver, proposal, row, stuck, rows, chain):
    """Every (gate, reason) the D-577 gates would hold this proposal on; ``first.gate`` decides which apply."""
    from fleet.stuck.lane_lost import AI_WORDS, _trusted_map_pose, lane_lost_hold, peer_behind

    cause, decision, rid = stuck.get("cause"), proposal["decision"], str(row["robot_id"])
    line_follow = (row.get("state") or {}).get("line_follow") or {}
    crosswalk = line_follow.get("crosswalk", {"state": "unknown"})
    if decision not in AI_WORDS.get(cause, ()):
        yield "ai_words", "word_not_allowed"
    if row.get("trip") and decision != "WAIT":
        yield "trip_wait_only", "trip"
    if decision in MOVING and (crosswalk is not None or resolver.at_crosswalk(rid)):
        yield "crosswalk", "crosswalk"
    if decision in MOVING and _trusted_map_pose(row) is None:
        yield "trusted_pose", "pose"
    if decision == "BACK_AND_RETRY":
        if stuck.get("rear_state") == "blocked":
            yield "r3_preconditions", "rear_blocked"
        elif cause in LOST_LIKE:
            hold = lane_lost_hold(row, stuck, rows, chain, resolver.config, painted=resolver._painted(),
                                  rule="R3" if cause == "lane_lost" else "R6")
            if hold is not None:
                yield "r3_preconditions", hold
        elif peer_behind(row, rows, resolver.config) is not False:
            yield "r3_preconditions", "peer_behind"
        fact = next((f["kind"] for f in row.get("ai_facts") or ()), None)
        if fact is not None:
            yield "acting_fact_hold", f"ai:{fact}"
    if decision == "ABORT" and crosswalk is not None:
        yield "abort_requires_crosswalk_null", "ai_abort_held"
