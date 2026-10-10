"""D-610 4 (P2): problems beyond a CORE stuck on AI-first robots — ``stalled`` and ``pose_lost``.

``stalled``: line following on, no stuck, zero command and < 0.05 m of travel for 20 s (low light and
over-exposure HOLDs included). ``pose_lost``: the map pose is ``DEGRADED`` or ``UNKNOWN`` (D-395). The AI PC
answers ``<kind>:<robot>:<epoch>`` with WAIT / LINE_OFF / STOP (stalled) or WAIT / IDENTIFY / STOP (pose_lost);
Fleet checks the word, the evidence (``AiFirst.evidence_invalid``), the human-class table and the caps, then
sends existing CORE commands with the resolver's credential (never a trip owner's): ``line_follow_mode("OFF")``,
``navigation_cancel``, ``identify_lamp`` (D-596). A trip robot gets WAIT only. Without an AI answer nothing is
sent: the robot keeps today's behaviour (D-395 ``needs_human``, the shadow ``stalled`` fact). Robots outside
AI-first are not watched here.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import Mapping, Optional

from fleet.stuck.ai_first import problem_key
from fleet.stuck.closed_loop import _awrite, context

STALL_S, STILL_M = 20.0, 0.05
WORDS = {"stalled": ("WAIT", "LINE_OFF", "STOP"), "pose_lost": ("WAIT", "IDENTIFY", "STOP")}
log = logging.getLogger(__name__)


def _xy(row: Mapping) -> Optional[tuple]:
    pose = (row.get("state") or {}).get("pose") or {}
    try:
        return float(pose["x"]), float(pose["y"])
    except (KeyError, TypeError, ValueError):
        return None


class ProblemWatch:
    def __init__(self) -> None:
        self.open: dict[tuple[str, str], dict] = {}
        self._still: dict[str, tuple[float, tuple]] = {}

    def stalled_ids(self) -> frozenset:
        return frozenset(rid for rid, kind in self.open if kind == "stalled")

    def _stalled(self, rid: str, row: Mapping, now: float) -> bool:
        line_follow = (row.get("state") or {}).get("line_follow") or {}
        moving = any(abs(float(line_follow.get(k) or 0.0)) > 1e-6 for k in ("linear", "angular"))
        xy = _xy(row)
        if line_follow.get("mode") in (None, "OFF") or line_follow.get("stuck") or moving or xy is None:
            self._still.pop(rid, None)
            return False
        since, where = self._still.setdefault(rid, (now, xy))
        if math.hypot(xy[0] - where[0], xy[1] - where[1]) >= STILL_M:
            self._still[rid] = (now, xy)
            return False
        return now - since >= STALL_S

    @staticmethod
    def _lost(row: Mapping) -> bool:
        pose = row.get("map_pose") or (row.get("state") or {}).get("localization") or {}
        return isinstance(pose, Mapping) and pose.get("state") in ("DEGRADED", "UNKNOWN")

    async def run(self, loop, now: float, robots) -> None:
        first = getattr(loop._resolver, "ai_first", None)
        for row in robots:
            rid = str(row["robot_id"])
            watched = first is not None and first.on(rid) and row.get("online", True)
            for kind, active in (("stalled", watched and self._stalled(rid, row, now)),
                                 ("pose_lost", watched and self._lost(row))):
                if not active:
                    self.open.pop((rid, kind), None)
                    continue
                problem = self.open.setdefault((rid, kind), {
                    "kind": kind, "robot_id": rid, "problem_id": f"{kind}:{rid}:{int(first.wall())}",
                    "judged": set()})
                await self._answer(loop, first, row, problem, now)

    async def _answer(self, loop, first, row: Mapping, problem: dict, now: float) -> None:
        rid, pid, kind = problem["robot_id"], problem["problem_id"], problem["kind"]
        if ((row.get("state") or {}).get("safety") or {}).get("estop") or loop.ai_board is None:
            return                                             # D-610 1: never an answer during an E-stop
        proposal = loop.ai_board.problem_proposal(pid)
        if proposal is None or proposal["robot_id"] != rid:
            return
        judged = (proposal["decision"], proposal["reason"])
        if judged in problem["judged"]:
            return
        problem["judged"].add(judged)
        decision, key = proposal["decision"], problem_key(row, kind, None, loop._resolver.at_crosswalk(rid))
        verdict = (f"human_class:{key}" if key in first.human_classes()
                   else "word_not_allowed" if decision not in WORDS[kind]
                   else first.evidence_invalid(proposal, rid) or first.limit(rid, pid, decision, now)
                   or ("trip" if row.get("trip") and decision != "WAIT" else None) or "forwarded")
        code = None
        client = loop._clients().get(rid)
        if verdict == "forwarded" and client is None:
            verdict = "no_resolver_token"
        if verdict == "forwarded":
            first.sent(rid, pid, decision, now)
            code = await self._send(client, decision)
        audit = {**proposal, "verdict": verdict, "judged_at": time.time()}
        loop.ai_board.verdicts.append(audit)
        if loop.ai_board.log is not None:
            await asyncio.to_thread(loop.ai_board.log.append_verdicts, [audit])
        await _awrite(loop, "opened", robot_id=rid, problem_id=pid, kind=kind, type_key=key, context=context(row),
               decision=decision if verdict == "forwarded" else None, tier="ai",
               proposal={k: proposal.get(k) for k in ("decision", "reason", "confidence", "source", "evidence")},
               verdict=verdict, core_code=code)
        if verdict == "forwarded":
            out = loop.outcomes.answered(kind, rid, pid, decision, code, now, row)
            if out is not None:
                await _awrite(loop, "outcome", out)
        log.info("ai %s %s on %s: %s -> %s", kind, pid, rid, decision, verdict)

    @staticmethod
    async def _send(client, decision: str) -> Optional[str]:
        """None = CORE took it, else the error code (the closed loop records ``failed:<code>``)."""
        try:
            if decision in ("LINE_OFF", "STOP"):
                await client.line_follow_mode("OFF")
            if decision == "STOP":
                await client.navigation_cancel()
            if decision == "IDENTIFY":
                await client.identify_lamp(quiet=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - one robot's failure is that answer's outcome
            return str(getattr(exc, "code", None) or type(exc).__name__)
        return None
