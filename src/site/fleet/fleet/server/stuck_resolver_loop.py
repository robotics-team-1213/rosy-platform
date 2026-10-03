"""D-438 §1: the resolver runs inside Fleet without a browser.

Every `poll_s` (or sooner, when a `nav.line_stuck_*` hub event sets `wake`) it reads the
console snapshot, refreshes the line-stuck board, and sends the core's answers with each
robot's stuck_resolver token. Answers are recorded as principal `fleet-resolver`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable, Mapping, Optional

import httpx

from fleet.server.console_routes import _transport_failure
from fleet.server.line_stuck import LineStuckBoard
from fleet.server.stuck_resolver import Answer, Escalate, StuckResolver
from fleet.swarm.transport import RobotApiError

PRINCIPAL_ID = "fleet-resolver"
log = logging.getLogger(__name__)


class StuckResolverLoop:
    def __init__(self, console, board: LineStuckBoard, resolver: StuckResolver, *,
                 clients: Callable[[], Mapping[str, object]],
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._console, self._board, self._resolver = console, board, resolver
        self._clients, self._clock = clients, clock
        self.wake = asyncio.Event()

    def claim(self, robot_id: str, stuck_id: str) -> None:
        self._resolver.claim(robot_id, stuck_id)
        self._board.note_resolver(robot_id, stuck_id, tier="human", rule=None,
                                  decision=None, escalated="human_claimed")

    async def run_once(self) -> None:
        snapshot = await self._console.snapshot()
        robots = snapshot["robots"]
        self._board.observe(robots, self._console.hub.registry.events_since)
        now = self._clock()
        for action in self._resolver.step(now, robots):
            if isinstance(action, Escalate):
                self._escalated(action)
            else:
                await self._answer(action, now)

    async def run(self) -> None:
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - one bad pass must not stop the resolver
                log.exception("stuck resolver pass failed")
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

    async def _answer(self, answer: Answer, now: float) -> None:
        client = self._clients().get(answer.robot_id)
        if client is None:
            self._resolver.claim(answer.robot_id, answer.stuck_id)   # never retry without a token
            self._escalated(Escalate(answer.robot_id, answer.stuck_id, "no_resolver_token"))
            return
        self._resolver.sent(answer, now)
        record = dict(robot_id=answer.robot_id, stuck_id=answer.stuck_id,
                      decision=answer.decision, principal_id=PRINCIPAL_ID)
        code: Optional[str] = None
        try:
            result = await client.line_stuck_decision(answer.stuck_id, answer.decision)
        except RobotApiError as exc:
            code = exc.code
            self._board.record(**record, accepted=False, code=exc.code, message=exc.message)
        except (httpx.HTTPError, OSError) as exc:
            code, message = _transport_failure(exc)
            self._board.record(**record, accepted=None, code=code,
                               message=f"{message} ({type(exc).__name__})")
        else:
            self._board.record(**record, accepted=True, outcome=result.get("outcome"))
        self._board.note_resolver(answer.robot_id, answer.stuck_id, tier="rule",
                                  rule=answer.rule, decision=answer.decision, escalated=None)
        escalation = self._resolver.result(answer, code=code)
        if escalation is not None:
            self._escalated(escalation)
