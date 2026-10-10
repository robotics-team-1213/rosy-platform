"""D-610 2·9: the resolver loop's closed loop — record every answer, watch its outcome, re-ask the AI.

Called by ``StuckResolverLoop`` (kept out of ``loop.py``/``board.py``). Every answered stuck becomes a
``fleet_problem_episodes`` row; CORE's reply either ends it (``refused``) or opens a window (``outcome.Outcomes``).
An ``unresolved`` stuck of an AI-first robot is reopened for one more AI answer (the case then carries the
outcome); the caps in ``ai_first.AiFirst.limit`` and the D-438 60 s deadline end that loop with a person.
SQLite writes run in a worker thread, never on the event loop (E-stop, resolver).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Mapping, Optional

from fleet.stuck.ai_first import problem_key
from fleet.stuck.resolver import REFUSED

log = logging.getLogger(__name__)


def context(row: Mapping, stuck: Optional[Mapping] = None) -> dict:
    """The compact problem context kept with an episode and served in a case (no pictures)."""
    state = row.get("state") or {}
    line_follow = state.get("line_follow") or {}
    stuck = stuck if stuck is not None else line_follow.get("stuck") or {}
    observed = row.get("_state_mono")
    age = row.get("state_age_s") if observed is None else round(max(0.0, time.monotonic() - observed), 3)
    return {"cause": stuck.get("cause"), "detail": stuck.get("detail"), "phase": stuck.get("phase"),
            "attempts": stuck.get("attempts"), "rear_state": stuck.get("rear_state"),
            "state_age_s": age,
            "robot_inquiry": stuck.get("inquiry"),
            "current_mode": state.get("mode"),
            "task_intent": {"task": "lane_follow_recovery", "trip_active": bool(row.get("trip")),
                            "goal": "recover the intended lane direction without overriding CORE safety"},
            "clearance_at_open_m": {k: stuck.get(k) for k in ("front_clearance_m", "rear_clearance_m",
                                                       "turn_clearance_m", "rear_blind_m")},
            "line_follow": {k: line_follow.get(k) for k in ("mode", "state", "reason")},
            "crosswalk": line_follow.get("crosswalk"), "map_pose": row.get("map_pose"),
            "localization": state.get("localization"), "trip": bool(row.get("trip")),
            "ai_facts": [f.get("kind") for f in row.get("ai_facts") or ()]}


async def _awrite(loop, method: str, *args, **kwargs) -> None:
    if loop.episodes is not None:
        await asyncio.to_thread(getattr(loop.episodes, method), *args, **kwargs)


def _write(loop, method: str, *args, **kwargs) -> None:
    """Fire and forget, for the sync callers (claim, escalation)."""
    if loop.episodes is None:
        return
    call = getattr(loop.episodes, method)
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        call(*args, **kwargs)
        return
    task = running.create_task(asyncio.to_thread(call, *args, **kwargs))
    task.add_done_callback(lambda t: t.cancelled() or t.exception() and log.warning("episode write: %s", t.exception()))


def human(loop, robot_id: str, problem_id: str) -> None:
    """A person has the problem: its window ends ``superseded`` and the episode is marked human."""
    out = loop.outcomes.supersede(robot_id, problem_id)
    if out is not None:
        _write(loop, "outcome", out)
    _write(loop, "human", robot_id, problem_id)


async def answered(loop, answer, code: Optional[str], now: float) -> None:
    rid, sid = answer.robot_id, answer.stuck_id
    row = loop._rows.get(rid) or {"robot_id": rid}
    first = getattr(loop._resolver, "ai_first", None)
    chain = loop._resolver._chains.get(rid)
    if code == REFUSED and answer.rule == "ai" and first is not None and chain is not None:
        first.refused(rid, chain.started_at, answer.decision)   # D-610 5: never the same answer again
    verdict = None
    if answer.rule == "ai" and loop.ai_board is not None:
        verdict = next((v for v in reversed(loop.ai_board.verdicts)
                        if v["robot_id"] == rid and v["stuck_id"] == sid), None)
    stuck = ((row.get("state") or {}).get("line_follow") or {}).get("stuck") or {}
    await _awrite(loop, "opened", robot_id=rid, problem_id=sid, kind="stuck",
           type_key=problem_key(row, "stuck", stuck.get("cause"), loop._resolver.at_crosswalk(rid)),
           context=context(row, stuck), decision=answer.decision,
           tier="ai" if answer.rule == "ai" else answer.rule,
           proposal=None if verdict is None else {k: verdict.get(k) for k in (
               "decision", "reason", "confidence", "source", "evidence")},
           verdict=None if verdict is None else verdict.get("verdict"),
           floor=() if verdict is None else verdict.get("floor") or (), core_code=code)
    if answer.escalate is not None:
        return                                    # WAIT + a person: nothing to confirm
    out = loop.outcomes.answered("stuck", rid, sid, answer.decision, code, now, row)
    if out is not None:
        await _awrite(loop, "outcome", out)


async def check(loop, now: float, robots) -> None:
    stalled = loop.problems.stalled_ids() if loop.problems is not None else frozenset()
    first = getattr(loop._resolver, "ai_first", None)
    for out in loop.outcomes.check(now, robots, stalled=stalled):
        log.info("problem %s on %s after %s: %s", out["problem_id"], out["robot_id"], out["decision"], out["outcome"])
        await _awrite(loop, "outcome", out)
        if out["outcome"] == "unresolved" and out["kind"] == "stuck" and first is not None and first.on(out["robot_id"]):
            reopen(loop._resolver, out["robot_id"], out["problem_id"], now)


def reopen(resolver, robot_id: str, stuck_id: str, now: float) -> None:
    """D-610 2: the same stuck is still open after its window: the AI may answer it once more."""
    chain = resolver._chains.get(robot_id)
    if chain is None or chain.stuck_id != stuck_id or stuck_id in chain.escalated:
        return
    chain.answered.discard(stuck_id)
    chain.ai_judged = {key for key in chain.ai_judged if key[0] != stuck_id}
    chain.seen_at = now
