"""D-438 §1: the resolver runs inside Fleet without a browser.

Every `poll_s` (or sooner, when a `nav.line_stuck_*` hub event sets `wake`) it reads the
shared gather (which also refreshes the line-stuck board), and sends the core's answers with each
robot's stuck_resolver token. Answers are recorded as principal `fleet-resolver`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable, Mapping, Optional

import httpx

from fleet.server.console_routes import transport_failure
from fleet.stuck.board import LineStuckBoard
from fleet.stuck.resolver import Answer, Escalate, StuckResolver
from fleet.swarm.transport import RobotApiError

PRINCIPAL_ID = "fleet-resolver"
log = logging.getLogger(__name__)


class StuckResolverLoop:
    def __init__(self, snapshot: Callable[[], Awaitable[dict]], board: LineStuckBoard,
                 resolver: StuckResolver, *, clients: Callable[[], Mapping[str, object]],
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._snapshot, self._board, self._resolver = snapshot, board, resolver
        self._clients, self._clock = clients, clock
        #: D-517 5 (M4): a robot on a running trip gets stopping answers only (app.py sets it).
        self.trip_busy: Callable[[str], bool] = lambda _robot_id: False
        #: D-577 1: `MapPoseService.stuck_pose` for R3's freshness check (app.py sets it).
        self.map_pose: Callable[[str], Optional[dict]] = lambda _robot_id: None
        #: D-577 7: live acting AI facts about a robot (`AiFactsBoard.acting_facts`, app.py sets it).
        self.ai_facts: Callable[[str], list] = lambda _robot_id: []
        #: D-577 개정 2026-10-10: the AI PC proposal board (`AiFactsBoard`; app.py sets it). None = no AI.
        self.ai_board = None
        self.wake = asyncio.Event()

    def claim(self, robot_id: str, stuck_id: str) -> None:
        self._resolver.claim(robot_id, stuck_id)
        previous = self._board.resolver_note(robot_id, stuck_id) or {}
        self._board.note_resolver(robot_id, stuck_id, tier="human", rule=None, decision=None,
                                  escalated=previous.get("escalated") or "human_claimed")

    async def run_once(self) -> None:
        robots = [self._row(row) for row in (await self._snapshot())["robots"]]
        now = self._clock()
        # ponytail: sequential awaits; asyncio.gather per robot when a hung robot delays others
        actions = self._resolver.step(now, robots)
        verdicts, self._resolver.ai_verdicts[:] = list(self._resolver.ai_verdicts), []
        if verdicts and self.ai_board is not None:
            for verdict in verdicts:
                log.info("ai proposal robot=%s stuck=%s %s/%s -> %s", verdict["robot_id"], verdict["stuck_id"],
                         verdict["decision"], verdict["reason"], verdict["verdict"])
            self.ai_board.verdicts.extend(verdicts)
            if self.ai_board.log is not None:
                await asyncio.to_thread(self.ai_board.log.append_verdicts, verdicts)
        for action in actions:
            if isinstance(action, Escalate):
                self._escalated(action)
            else:
                await self._answer(action, now)

    def _row(self, row: dict) -> dict:
        extra = {}
        if self.trip_busy(row["robot_id"]):
            extra["trip"] = True
        pose = self.map_pose(row["robot_id"])
        if pose is not None:
            extra["map_pose"] = pose
        facts = self.ai_facts(row["robot_id"])
        if facts:
            extra["ai_facts"] = facts
        if self.ai_board is not None:
            proposal = self.ai_board.proposal(row["robot_id"])
            if proposal is not None:
                extra["ai_proposal"] = proposal
            if self.ai_board.waiting(row["robot_id"]):
                extra["ai_wait"] = True
        return {**row, **extra} if extra else row

    async def run(self) -> None:
        last_error = None
        while True:
            try:
                await self.run_once()
                last_error = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - one bad pass must not stop the resolver
                if str(exc) != last_error:
                    log.exception("stuck resolver pass failed")
                else:
                    log.debug("stuck resolver pass failed again: %s", exc)
                last_error = str(exc)
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=self._resolver.config.poll_s)
            except asyncio.TimeoutError:
                pass
            self.wake.clear()

    def _escalated(self, action: Escalate, *, rule: Optional[str] = None,
                   decision: Optional[str] = None) -> None:
        log.warning("stuck %s on %s escalated to a human: %s",
                    action.stuck_id, action.robot_id, action.reason)
        self._board.note_resolver(action.robot_id, action.stuck_id, tier="human", rule=rule,
                                  decision=decision, escalated=action.reason)
        self._board.record(robot_id=action.robot_id, stuck_id=action.stuck_id,
                           decision="ESCALATE", principal_id=PRINCIPAL_ID, accepted=None,
                           tier="human", escalated=action.reason)

    async def _answer(self, answer: Answer, now: float) -> None:
        client = self._clients().get(answer.robot_id)
        if client is None:
            self._resolver.claim(answer.robot_id, answer.stuck_id)   # never retry without a token
            self._escalated(Escalate(answer.robot_id, answer.stuck_id, "no_resolver_token"))
            return
        self._resolver.sent(answer, now)
        record = dict(robot_id=answer.robot_id, stuck_id=answer.stuck_id,
                      decision=answer.decision, principal_id=PRINCIPAL_ID,
                      tier="ai" if answer.rule == "ai" else "rule",
                      rule=answer.rule)
        code: Optional[str] = None
        try:
            extra = {}
            if answer.yield_m is not None and answer.yield_turn_rad is not None:
                extra = {"yield_m": answer.yield_m, "yield_turn_rad": answer.yield_turn_rad}
            result = await client.line_stuck_decision(answer.stuck_id, answer.decision, **extra)
        except asyncio.CancelledError:
            # Fleet is stopping mid-request: the robot may have applied the answer.
            self._board.record(**record, accepted=None, code="STUCK_DECISION_OUTCOME_UNKNOWN",
                               message="resolver stopped before the robot replied")
            if answer.decision == "YIELD":
                escalation = self._resolver.result(answer, code="STUCK_DECISION_OUTCOME_UNKNOWN")
                if escalation is not None:
                    self._escalated(escalation)
            elif answer.escalate is not None:          # D-577 남은 항목 3: R5's human row is not lost
                self._escalated(Escalate(answer.robot_id, answer.stuck_id, answer.escalate),
                                rule=answer.rule, decision=answer.decision)
            raise
        except RobotApiError as exc:
            code = exc.code
            self._board.record(**record, accepted=False, code=exc.code, message=exc.message)
        except (httpx.HTTPError, OSError) as exc:
            code, message = transport_failure(exc)
            self._board.record(**record, accepted=False if code == "ROBOT_UNREACHABLE" else None,
                               code=code, message=f"{message} ({type(exc).__name__})")
        except Exception as exc:  # noqa: BLE001 - a broken client must not stop the other robots
            code = "STUCK_DECISION_OUTCOME_UNKNOWN"
            self._board.record(**record, accepted=None, code=code,
                               message=f"unexpected client error ({type(exc).__name__})")
        else:
            self._board.record(**record, accepted=True, outcome=result.get("outcome"))
        if answer.rule == "ai" and self.ai_board is not None:
            self.ai_board.note_outcome(answer.robot_id, answer.stuck_id, answer.decision, code or "accepted")
            if self.ai_board.log is not None:
                await asyncio.to_thread(self.ai_board.log.set_outcome, answer.robot_id, answer.stuck_id,
                                        answer.decision, code or "accepted")
        self._board.note_resolver(answer.robot_id, answer.stuck_id, tier="ai" if answer.rule == "ai" else "rule",
                                  rule=answer.rule, decision=answer.decision, escalated=None)
        escalation = self._resolver.result(answer, code=code)
        if escalation is not None:
            self._escalated(escalation, rule=answer.rule if answer.escalate else None,
                            decision=answer.decision if answer.escalate else None)
