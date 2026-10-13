"""D-610 7 (P3): the AI PC picks the replan for a D-517 wait cycle; Fleet checks it can carry it out.

``LaneTraffic._hand_over`` asks ``AiReplan`` once a cycle has lasted ``CYCLE_PERIODS``. The answer is the AI PC
proposal for ``deadlock:<member>:<member>...`` (sorted ids) with ``REPLAN``, ``robot_id`` = the robot to plan again and
``body.blocked_edges`` = the edges to plan around. Fleet takes it only when every cycle member is AI-first, the
proposal is ``vlm:`` with fresh evidence (``AiFirst.evidence_invalid``), the key is not a human class, the problem
has had fewer than 3 AI answers, the robot is a member and the edges lie inside its ``avoidable`` set. The trip
runner (the lease owner) then plans again with the same D-489/D-494/D-601 checks as a first trip and switches the
route without ``replan_hold`` only when they pass; the block table still grants every block. Anything else: M4
as before (operator confirmation or a person).
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Mapping, Sequence

from fleet.stuck.closed_loop import _write
from fleet.stuck.ai_first import VLM_WAIT_S


class AiReplan:
    def __init__(self, first, board, episodes=None) -> None:
        self.first, self.board, self._log = first, board, SimpleNamespace(episodes=episodes)
        self._judged: set = set()
        self.case = None
        self.waiting = False
        self._started = None

    def __call__(self, cycle: Sequence[str], avoidable: Mapping[str, Sequence[str]], now: float):
        members = sorted(cycle)
        self.case = None
        self.waiting = False
        if not members or not all(self.first.on(r) for r in members):
            self._started = None
            return None
        pid = "deadlock:" + ":".join(members)
        if self._started is None or self._started[0] != pid:
            self._started = (pid, now)
        self.waiting = bool(set(self.first.profiles())) and now - self._started[1] < VLM_WAIT_S
        self.case = {"problem_id": pid, "kind": "deadlock", "robot_id": members[0],
                     "context": {"cycle": members, "avoidable": {r: list(avoidable.get(r, ())) for r in members}}}
        proposal = self.board.problem_proposal(pid)
        if proposal is None or proposal["decision"] != "REPLAN":
            return None
        pick, edges = proposal["robot_id"], tuple(proposal.get("body", {}).get("blocked_edges") or ())
        judged = (pid, pick, edges, proposal["reason"], proposal.get("observed_at"))
        if judged in self._judged:
            self.waiting = False
            return None
        key = "deadlock:wait_cycle:lane"           # ponytail: one place word until blocks name their place
        verdict = self._verdict(proposal, pid, pick, edges, avoidable, key, now)
        if judged not in self._judged:
            self._judged.add(judged)
            self.board.verdicts.append({**proposal, "verdict": verdict, "judged_at": time.time()})
            _write(self._log, "opened", robot_id=pick, problem_id=pid, kind="deadlock", type_key=key,
                   context={"cycle": members, "avoidable": {r: list(avoidable.get(r, ())) for r in members}},
                   decision="REPLAN" if verdict == "forwarded" else None, tier="ai",
                   proposal={k: proposal.get(k) for k in ("decision", "reason", "confidence", "source", "body")},
                   verdict=verdict)
            if verdict == "forwarded":
                self.first.sent(pick, pid, "REPLAN", now)
        if verdict == "forwarded":
            self.waiting = False
            return pick, edges
        return None

    def _verdict(self, proposal, pid, pick, edges, avoidable, key, now) -> str:
        if not str(proposal.get("source", "")).startswith("vlm:"):
            return "not_vlm"
        if key in self.first.human_classes():
            return f"human_class:{key}"
        missing = self.first.evidence_invalid(proposal, pick)
        if missing is not None:
            return missing
        evidence = (proposal.get("evidence") or {}).get("members") or {}
        for member in pid.split(":")[1:]:
            if member not in evidence:
                return "evidence_missing:member"
            missing = self.first.evidence_invalid({**proposal, "evidence": evidence[member]}, member)
            if missing is not None:
                return missing
        limit = self.first.limit(pick, pid, "REPLAN", now)
        if limit is not None:
            return limit
        if pick not in pid.split(":")[1:]:
            return "not_a_member"
        if not edges or not set(edges) <= set(avoidable.get(pick, ())):
            return "edges_not_avoidable"
        return "forwarded"

