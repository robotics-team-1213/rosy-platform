"""Existing Fleet physical answer writer; no provider or independent policy."""
from __future__ import annotations
import asyncio
import sqlite3
from typing import Optional
import httpx
from .owned import owned
from fleet.swarm.transport import HttpRobotClient
from fleet.incidents.automation.recovery_candidates import observed_recovery
from fleet.server.console_routes import transport_failure
from .. import closed_loop, pipeline, lane_lost
from ..resolver import Answer, Escalate, Hold
from fleet.swarm.transport import RobotApiError
PRINCIPAL_ID = "fleet-resolver"


async def answer(self, answer, now, *, selected=None):
    operating = getattr(self, 'operating_state', None)
    if operating is None or answer.decision in {'WAIT', 'ABORT', 'MANUAL'}:
        return await legacy_answer(self, answer, now, selected=selected)
    row = await self._admission_row(answer.robot_id)
    state = (row or {}).get('state') or {}
    generation = f"core:{state.get('seq')}:{state.get('timestamp')}"
    claimed, result = [], None
    def claim():
        record = operating.claim_rule(answer.robot_id, answer.stuck_id, generation=generation,
            decision=answer.decision, guard=lambda conn: not self._resolver.is_claimed(answer.robot_id, answer.stuck_id)
            and pipeline.law_hold(row, decision=answer.decision, stuck_id=answer.stuck_id) is None)
        claimed.append(record)
    try:
        await owned(claim)
        result = await legacy_answer(self, answer, now, selected=selected)
    except ValueError:
        return
    finally:
        if claimed:
            await owned(operating.finish_rule, answer.robot_id, answer.stuck_id, generation=generation,
                state=result['state'] if result else 'UNKNOWN', reply=result['reply'] if result else {'code': 'NO_TERMINAL_REPLY'})


async def model_answer(self, scope, attempt_id, problem, worker):
    operating = getattr(self, 'operating_state', None)
    grant_id = getattr(self, 'operating_grant', None)
    client = self._clients().get(scope.subject_id)
    method = getattr(client, 'line_stuck_decision', None)
    if (operating is None or operating.store is not worker.store or not isinstance(client, HttpRobotClient)
            or getattr(method, '__func__', None) is not HttpRobotClient.line_stuck_decision
            or client.robot_id != scope.subject_id):
        return False
    claimed, reply, terminal = [], {'code': 'NO_TERMINAL_REPLY'}, 'UNKNOWN'
    action = Answer(scope.subject_id, scope.case_id, 'BACK_AND_RETRY', 'model_v2')
    try:
        if await owned(operating.submission, scope.subject_id, scope.case_id) is not None: return False
        candidates = await owned(operating.candidates.candidates, scope)
        candidate = next(c for c in candidates if c['attempt_id'] == attempt_id)
        if candidate['input_hash'] != problem.digest: return False
        approval = await owned(operating.grant, grant_id)
        case = await owned(operating.store.case, scope)
        async def before_submit():
            row = await self._admission_row(scope.subject_id)
            def guard(conn):
                context = observed_recovery({'robots': [row]} if row else {}, scope.subject_id, scope.case_id, problem.generation)
                chain = self._resolver._chains.get(scope.subject_id)
                return (self.operating_state is operating and self.operating_grant == grant_id and self._clients().get(scope.subject_id) is client
                    and scope.subject_id in self._resolver.autonomous_robots
                    and not self._resolver.is_claimed(scope.subject_id, scope.case_id)
                    and worker.human_owned(scope.subject_id, scope.case_id) is False and worker._fresh(problem) is True
                    and pipeline.law_hold(row, decision='BACK_AND_RETRY', stuck_id=scope.case_id) is None
                    and chain is not None and not self._resolver.at_crosswalk(scope.subject_id)
                    and chain.stuck_id == scope.case_id and scope.case_id not in chain.escalated
                    and action.rule not in chain.retired
                    and self._resolver._continuation_hold(scope.subject_id, chain) is None
                    and self._clock() - chain.started_at <= self._resolver.config.escalate_after_s
                    and lane_lost.ai_proposal_invalid({'decision': 'BACK_AND_RETRY'}, row,
                        row['state']['line_follow']['stuck'], list(self._rows.values()), chain,
                        self._resolver.config, self._resolver._painted()) is None
                    and context is not None and {k: context[k] for k in ('phase', 'attempts')} == candidate['expected_stuck'])
            def claim():
                pending_rows = []
                def pending(conn):
                    pending_rows.append(self._board.record(robot_id=scope.subject_id, stuck_id=scope.case_id, decision='BACK_AND_RETRY',
                        principal_id=PRINCIPAL_ID, tier='ai', rule='model_v2', accepted=None,
                        code='FLEET_STUCK_DISPATCH_PENDING', durable=True, connection=conn))
                    return True
                record = operating.claim_model(scope, grant_id, attempt_id, expected_epoch=approval['epoch'],
                    generation=problem.generation, guard=guard, on_claim=pending)
                claimed.append(record)
                self._resolver.sent(action, self._clock())
                self._board._publish_answer(pending_rows[0])
            await owned(claim)
            return True
        async with asyncio.timeout(min(30, max(0, case['deadline'] - operating.store.clock()))):
            result = await method(scope.case_id, 'BACK_AND_RETRY', expected_stuck=candidate['expected_stuck'], before_submit=before_submit)
        terminal = 'ACK' if result.get('outcome') == 'back' else 'UNKNOWN'
        reply = {'outcome': 'back'} if terminal == 'ACK' else {'code': 'BAD_RESPONSE'}
    except asyncio.CancelledError:
        raise
    except RobotApiError as exc:
        reply = {'code': exc.code}
        terminal = 'REFUSED' if 400 <= exc.status < 500 else 'UNKNOWN'
    except (ValueError, TypeError, KeyError, StopIteration, httpx.HTTPError, OSError, TimeoutError):
        return False
    finally:
        if claimed:
            final = await owned(operating.finish, scope, state=terminal, reply=reply)
            terminal = final['state']
            await owned(self._board.record, robot_id=scope.subject_id, stuck_id=scope.case_id,
                decision='BACK_AND_RETRY', principal_id=PRINCIPAL_ID, tier='ai', rule='model_v2',
                accepted=True if terminal == 'ACK' else False if terminal == 'REFUSED' else None,
                outcome='back' if terminal == 'ACK' else None, durable=True,
                code='STUCK_DECISION_OUTCOME_UNKNOWN' if terminal == 'UNKNOWN' else reply.get('code'))
            if terminal != 'UNKNOWN':
                await owned(self._board.record, robot_id=scope.subject_id, stuck_id=scope.case_id,
                    decision='ESCALATE', principal_id=PRINCIPAL_ID, accepted=None, tier='ai',
                    code='STUCK_DECISION_RECONCILED', durable=True)
            else: self._resolver._uncertain.add((scope.subject_id, scope.case_id))
            escalation = self._resolver.result(action, code=None if terminal == 'ACK' else
                'STUCK_DECISION_OUTCOME_UNKNOWN' if terminal == 'UNKNOWN' else reply.get('code'))
            if escalation is not None: self._escalated(escalation, rule=action.rule, decision=action.decision)
    return bool(claimed) and terminal == 'ACK'

async def legacy_answer(self, answer: Answer, now: float, *, selected: Optional[dict] = None) -> dict | None:
    row = await self._admission_row(answer.robot_id)
    if self._resolver.is_claimed(answer.robot_id, answer.stuck_id):
        return
    hold = pipeline.law_hold(row, decision=answer.decision, stuck_id=answer.stuck_id) \
        or pipeline.ai_hold(self._resolver, answer, selected, row, list(self._rows.values()))
    if hold is not None:
        if answer.robot_id in self._resolver.autonomous_robots:
            chain = self._resolver._chains.get(answer.robot_id)
            action = self._resolver._escalate(chain, answer.robot_id, answer.stuck_id, hold) if chain else None
            if action is not None:
                self._escalated(action, rule=answer.rule, decision=answer.decision)
        else:
            self._resolver.claim(answer.robot_id, answer.stuck_id)
            self._escalated(Escalate(answer.robot_id, answer.stuck_id, hold),
                            rule=answer.rule, decision=answer.decision)
        return
    client = self._clients().get(answer.robot_id)
    if client is None:
        self._resolver.claim(answer.robot_id, answer.stuck_id)   # never retry without a token
        self._escalated(Escalate(answer.robot_id, answer.stuck_id, "no_resolver_token"))
        return
    now = self._clock()
    self._rows[answer.robot_id] = row
    record = dict(robot_id=answer.robot_id, stuck_id=answer.stuck_id,
                  decision=answer.decision, principal_id=PRINCIPAL_ID,
                  tier="ai" if answer.rule == "ai" else "rule",
                  rule=answer.rule)
    pending = answer.robot_id in self._resolver.autonomous_robots and answer.decision != "WAIT"
    if pending:
        self._resolver._uncertain.add((answer.robot_id, answer.stuck_id))
        try:
            await asyncio.to_thread(self._board.record, **record, accepted=None,
                                    code="FLEET_STUCK_DISPATCH_PENDING", durable=True)
            row = await self._admission_row(answer.robot_id)
            hold = pipeline.law_hold(row, decision=answer.decision, stuck_id=answer.stuck_id) \
                or pipeline.ai_hold(self._resolver, answer, selected, row, list(self._rows.values()))
            if (hold or self._resolver.is_claimed(answer.robot_id, answer.stuck_id)
                    or self._clients().get(answer.robot_id) is not client):
                await self._reconcile(answer.robot_id, answer.stuck_id, "not_dispatched")
                return
        except (OSError, sqlite3.Error):
            self._escalated(Hold(answer.robot_id, answer.stuck_id, "journal_unavailable"))
            return
    self._resolver.sent(answer, now)
    code: Optional[str] = None
    try:
        extra = {}
        if answer.yield_m is not None and answer.yield_turn_rad is not None:
            extra = {"yield_m": answer.yield_m, "yield_turn_rad": answer.yield_turn_rad}
        if answer.realign is not None:
            extra["realign"] = answer.realign
        result = await client.line_stuck_decision(answer.stuck_id, answer.decision, **extra)
        if pending and result.get("outcome") != {
                "BACK_AND_RETRY": "back", "RESUME": "resume", "YIELD": "yield", "ABORT": "idle",
                "REALIGN": "realign", "MANUAL": "manual"}.get(answer.decision):
            raise RobotApiError(answer.robot_id, 200, "BAD_RESPONSE", "missing or mismatched stuck receipt")
    except asyncio.CancelledError:
        # Fleet is stopping mid-request: the robot may have applied the answer.
        self._board.record(**record, accepted=None, code="STUCK_DECISION_OUTCOME_UNKNOWN",
                           message="resolver stopped before the robot replied")
        if answer.decision in ("YIELD", "REALIGN"):
            escalation = self._resolver.result(answer, code="STUCK_DECISION_OUTCOME_UNKNOWN")
            if escalation is not None:
                self._escalated(escalation)
        elif answer.escalate is not None:          # D-577 남은 항목 3: R5's human row is not lost
            self._escalated(Escalate(answer.robot_id, answer.stuck_id, answer.escalate),
                            rule=answer.rule, decision=answer.decision)
        raise
    except RobotApiError as exc:
        code = (exc.code if not pending or (400 <= exc.status < 500 and exc.code != "BAD_RESPONSE")
                else "STUCK_DECISION_OUTCOME_UNKNOWN")
        self._board.record(**record, accepted=None if code == "STUCK_DECISION_OUTCOME_UNKNOWN" else False,
                           code=code, message=exc.message)
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
    if pending and code != "STUCK_DECISION_OUTCOME_UNKNOWN":
        try:
            await self._reconcile(answer.robot_id, answer.stuck_id, "dispatch_receipt_known")
        except (OSError, sqlite3.Error):
            self._escalated(Hold(answer.robot_id, answer.stuck_id, "journal_unavailable"))
    if answer.rule == "ai" and self.ai_board is not None:
        self.ai_board.note_outcome(answer.robot_id, answer.stuck_id, answer.decision, code or "accepted")
        if self.ai_board.log is not None:
            await asyncio.to_thread(self.ai_board.log.set_outcome, answer.robot_id, answer.stuck_id,
                                    answer.decision, code or "accepted")
    self._board.note_resolver(answer.robot_id, answer.stuck_id, tier="ai" if answer.rule == "ai" else "rule",
                              rule=answer.rule, decision=answer.decision, escalated=None)
    escalation = self._resolver.result(answer, code=code)
    await closed_loop.answered(self, answer, code, now)
    if escalation is not None:
        self._escalated(escalation, rule=answer.rule if answer.escalate else None,
                        decision=answer.decision if answer.escalate else None)

    return dict(state="UNKNOWN" if code == "STUCK_DECISION_OUTCOME_UNKNOWN" else "REFUSED" if code else "ACK",
                reply={"code": code})
