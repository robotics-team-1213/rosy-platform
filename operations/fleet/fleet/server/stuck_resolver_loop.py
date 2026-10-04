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
from fleet.server.line_stuck import LineStuckBoard
from fleet.server.stuck_resolver import Answer, Escalate, StuckResolver
from fleet.swarm.transport import RobotApiError

PRINCIPAL_ID = "fleet-resolver"
log = logging.getLogger(__name__)


class StuckResolverLoop:
    def __init__(self, snapshot: Callable[[], Awaitable[dict]], board: LineStuckBoard,
                 resolver: StuckResolver, *, clients: Callable[[], Mapping[str, object]],
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._snapshot, self._board, self._resolver = snapshot, board, resolver
        self._clients, self._clock = clients, clock
        self.wake = asyncio.Event()

    def claim(self, robot_id: str, stuck_id: str) -> None:
        self._resolver.claim(robot_id, stuck_id)
        previous = self._board.resolver_note(robot_id, stuck_id) or {}
        self._board.note_resolver(robot_id, stuck_id, tier="human", rule=None, decision=None,
                                  escalated=previous.get("escalated") or "human_claimed")

    async def run_once(self) -> None:
        robots = (await self._snapshot())["robots"]
        now = self._clock()
        # ponytail: sequential awaits; asyncio.gather per robot when a hung robot delays others
        for action in self._resolver.step(now, robots):
            if isinstance(action, Escalate):
                self._escalated(action)
            else:
                await self._answer(action, now)

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

    def _escalated(self, action: Escalate) -> None:
        log.warning("stuck %s on %s escalated to a human: %s",
                    action.stuck_id, action.robot_id, action.reason)
        self._board.note_resolver(action.robot_id, action.stuck_id, tier="human", rule=None,
                                  decision=None, escalated=action.reason)
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
                      decision=answer.decision, principal_id=PRINCIPAL_ID, tier="rule",
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
        self._board.note_resolver(answer.robot_id, answer.stuck_id, tier="rule",
                                  rule=answer.rule, decision=answer.decision, escalated=None)
        escalation = self._resolver.result(answer, code=code)
        if escalation is not None:
            self._escalated(escalation)
