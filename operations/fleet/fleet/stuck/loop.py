"""D-438 §1: the resolver runs inside Fleet without a browser.

Every `poll_s` (or sooner, when a `nav.line_stuck_*` hub event sets `wake`) it reads the
shared gather (which also refreshes the line-stuck board), and sends the core's answers with each
robot's stuck_resolver token. Answers are recorded as principal `fleet-resolver`.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
import hashlib
import json
from dataclasses import asdict
from typing import Awaitable, Callable, Mapping, Optional

from fleet.stuck import closed_loop, pipeline
from fleet.stuck.board import LineStuckBoard
from fleet.stuck.outcome import Outcomes
from fleet.stuck.resolver import Answer, Escalate, Hold, StuckResolver

from .submission.dispatch import PRINCIPAL_ID
log = logging.getLogger(__name__)


class StuckResolverLoop:
    def __init__(self, snapshot: Callable[[], Awaitable[dict]], board: LineStuckBoard,
                 resolver: StuckResolver, *, clients: Callable[[], Mapping[str, object]],
                 clock: Callable[[], float] = time.monotonic, incident_worker=None) -> None:
        self._snapshot, self._board, self._resolver = snapshot, board, resolver
        self._clients, self._clock = clients, clock
        self.incident_worker = incident_worker
        self.operating_state, self.operating_grant = None, None
        from fleet.observe.rules import RuleSelectionStore
        self.rule_selections = RuleSelectionStore(board._log.path) if board is not None and board._log is not None else None
        self._rule_selections = {}
        #: D-517 5 (M4): a robot on a running trip gets stopping answers only (app.py sets it).
        self.trip_busy: Callable[[str], bool] = lambda _robot_id: False
        #: D-577 1: `MapPoseService.stuck_pose` for R3's freshness check (app.py sets it).
        self.map_pose: Callable[[str], Optional[dict]] = lambda _robot_id: None
        self.heading_review: Callable[[str], Optional[dict]] = lambda _robot_id: None
        self.realign_evidence: Callable[[str], Optional[dict]] = lambda _robot_id: None
        self._heading_notes: dict[str, tuple] = {}
        #: D-577 7: live acting AI facts about a robot (`AiFactsBoard.acting_facts`, app.py sets it).
        self.ai_facts: Callable[[str], list] = lambda _robot_id: []
        #: D-577 개정 2026-10-10: the AI PC proposal board (`AiFactsBoard`; app.py sets it). None = no AI.
        self.ai_board = None
        #: 2026-10-28 자원 경계: closed 사건 판정은 hub의 stuck 인덱스만 읽는다
        #: (app.py가 registry.stuck_event를 넣는다). 전체 이벤트 스캔은 없다.
        self.stuck_event = lambda _robot_id, _event_type, _stuck_id: None
        #: D-610 2·9: the closed loop and the problem record (app.py sets ``episodes``; None = not kept).
        self.outcomes, self.episodes, self.problems = Outcomes(), None, None
        self._rows: dict[str, dict] = {}
        self.wake = asyncio.Event()
        if board is not None and board._log is not None and hasattr(resolver, "_uncertain"):
            resolver._uncertain.update(board._log.uncertain_motion())

    def claim(self, robot_id: str, stuck_id: str) -> None:
        self._resolver.claim(robot_id, stuck_id)
        closed_loop.human(self, robot_id, stuck_id)
        previous = self._board.resolver_note(robot_id, stuck_id) or {}
        self._board.note_resolver(robot_id, stuck_id, tier="human", rule=None, decision=None,
                                  escalated=previous.get("escalated") or "human_claimed")

    async def run_once(self) -> None:
        snapshot = await self._snapshot()
        robots = [self._row(row) for row in snapshot["robots"]]
        now = self._clock()
        self._rows = {str(row["robot_id"]): row for row in robots}
        for rid, sid in tuple(getattr(self._resolver, "_uncertain", ())):
            if self.stuck_event(rid, "nav.line_stuck_closed", sid) is not None:
                await self._reconcile(rid, sid, "owner_case_closed")
                chain = self._resolver._chains.get(rid)
                if chain and chain.observing == "core:STUCK_DECISION_OUTCOME_UNKNOWN":
                    chain.observing = None
        if self._board is not None and self._board._log is not None:
            for claim in await asyncio.to_thread(self._board._log.handoff.active):
                rid, sid = claim['robot_id'], claim['stuck_id']
                if self._board.is_open(rid, sid) and not self._resolver.is_claimed(rid, sid):
                    self.claim(rid, sid)
        self._review_headings(robots)
        await closed_loop.check(self, now, robots)
        # ponytail: sequential awaits; asyncio.gather per robot when a hung robot delays others
        actions = self._resolver.step(now, robots)
        await self._record_selections(robots, actions)
        if self.incident_worker is not None:
            try: self.incident_worker.feed(snapshot)
            except (ValueError, TypeError, KeyError): log.warning('incident worker rejected poll')
        selected = self._rows.copy()
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
                if not self._resolver.is_claimed(action.robot_id, action.stuck_id): self._escalated(action)
            else:
                await self._answer(action, now, selected=selected.get(action.robot_id))
        if self.problems is not None:              # D-610 4: stalled and pose_lost
            await self.problems.run(self, now, robots)

    async def _record_selections(self, robots, actions):
        self._rule_selections = {}
        if self.rule_selections is None: return
        try:
            def digest(value):
                raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
                if len(raw) > 1024 * 1024: raise ValueError('RULE_SELECTION_SOURCE_LIMIT')
                return hashlib.sha256(raw).hexdigest()
            source = digest(robots)
            config = digest(self._rule_config())
            selected = {action.robot_id: action for action in actions}
            active_ai = sorted(r['robot_id'] for r in robots if self._resolver.ai_first is not None
                               and self._resolver.ai_first.on(r['robot_id']))
            mixed = bool(active_ai) or any(
                r.get('ai_facts') or r.get('ai_proposal') or r.get('ai_wait') for r in robots)
            records = [pipeline.selection_receipt(self._board.intervention_assessment(r['robot_id']),
                selected.get(r['robot_id']), source_sha256=source, config_sha256=config, mixed=bool(mixed)) for r in robots]
            records = await asyncio.to_thread(self.rule_selections.append_batch, records, now=self._board._wall())
            self._rule_selections = {r['assessment']['request']['subject_id']: r for r in records}
        except (ValueError, TypeError, KeyError, OSError, sqlite3.Error):
            log.warning('rule selection journal unavailable; no current model baseline')

    def _rule_config(self):                            # D-622: the REALIGN opt-in changes the selection
        return dict(config=asdict(self._resolver.config), autonomous=sorted(self._resolver.autonomous_robots),
                    realign=dict(robots=sorted(self._resolver.realign.robots), areas=self._resolver.realign.areas))

    def rule_baseline(self, assessment):
        from rosy.contracts.learning.incident_rule import baseline_choice
        from fleet.server.incident_deliberation import FleetBaseline
        from rosy_situation.snapshot_assessment import POLICY
        if assessment is None or not assessment.applies_to(assessment.request, now=self._board._wall(), policy_revision=POLICY.revision):
            return None
        if self._resolver.is_claimed(assessment.request.subject_id, assessment.request.case_id): return None
        record = self._rule_selections.get(assessment.request.subject_id)
        if (record is None or record['assessment']['request'] != json.loads(json.dumps(asdict(assessment.request)))
                or record['assessment']['policy_revision'] != assessment.policy_revision
                or not record['assessment']['evaluated_at'] <= self._board._wall() < record['assessment']['valid_until']):
            return None
        config_sha = hashlib.sha256(json.dumps(self._rule_config(), sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        if record['config_sha256'] != config_sha: return None
        choice = baseline_choice(record)
        return FleetBaseline.from_assessment(assessment, choice) if choice is not None else None

    def _row(self, row: dict) -> dict:
        extra = {}
        if getattr(getattr(self._resolver, "realign", None), "robots", None):   # D-622; absent = off
            try:
                extra["realign_evidence"] = self.realign_evidence(row["robot_id"])
            except Exception:  # noqa: BLE001 - absence must hold, never authorize motion
                extra["realign_evidence"] = {"status":"observer_unavailable"}
            extra["clearance_evidence"] = self._board.view(row["robot_id"])
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

    def _review_headings(self, robots: list[dict]) -> None:
        active = set()
        for row in robots:
            robot_id = row["robot_id"]
            stuck = ((row.get("state") or {}).get("line_follow") or {}).get("stuck") or {}
            if not row.get("online") or not stuck.get("stuck_id"):
                continue
            active.add(robot_id)
            try:
                review = self.heading_review(robot_id)
            except Exception:  # noqa: BLE001 - observation cannot interrupt existing recovery decisions
                log.debug("heading observer failed for %s", robot_id, exc_info=True)
                review = {"status": "observer_unavailable"}
            if review is None:
                continue
            row["heading_review"] = review
            turn = review.get("turn_deg")
            key = (stuck["stuck_id"], review["status"], review.get("map_version"),
                   review.get("edge_id"), round(turn / 5) if turn is not None else None)
            if self._heading_notes.get(robot_id) != key:
                self._heading_notes[robot_id] = key
                log.info("stuck heading robot=%s stuck=%s evidence=%s", robot_id, stuck["stuck_id"], review)
        self._heading_notes = {rid: note for rid, note in self._heading_notes.items() if rid in active}

    async def run(self) -> None:
        try:
            await self._run()
        finally:
            if self.incident_worker is not None:
                await self.incident_worker.aclose()

    async def _run(self) -> None:
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
        if isinstance(action, Hold):
            reason = f"auto_hold:{action.reason}"
            self._board.note_resolver(action.robot_id, action.stuck_id, tier="rule", rule=rule or "R5",
                                      decision="WAIT", escalated=reason)
            self._board.record(robot_id=action.robot_id, stuck_id=action.stuck_id,
                               decision="ESCALATE", principal_id=PRINCIPAL_ID, accepted=None,
                               tier="rule", rule=rule or "R5", escalated=reason)
            return
        log.warning("stuck %s on %s escalated to a human: %s",
                    action.stuck_id, action.robot_id, action.reason)
        closed_loop.human(self, action.robot_id, action.stuck_id)
        self._board.note_resolver(action.robot_id, action.stuck_id, tier="human", rule=rule,
                                  decision=decision, escalated=action.reason)
        self._board.record(robot_id=action.robot_id, stuck_id=action.stuck_id,
                           decision="ESCALATE", principal_id=PRINCIPAL_ID, accepted=None,
                           tier="human", escalated=action.reason)

    async def _admission_row(self, robot_id: str) -> Optional[dict]:
        rows = (await self._snapshot())["robots"]
        self._rows = {str(row["robot_id"]): self._row(row) for row in rows}
        return self._rows.get(robot_id)

    from .submission.dispatch import answer as _answer, model_answer as _model_answer

    async def _reconcile(self, robot_id, stuck_id, reason):
        await asyncio.to_thread(self._board.record, robot_id=robot_id, stuck_id=stuck_id,
                                decision="ESCALATE", principal_id=PRINCIPAL_ID, accepted=None,
                                tier="rule", code="STUCK_DECISION_RECONCILED",
                                escalated="auto_reconciled:" + reason, durable=True)
        self._resolver._uncertain.discard((robot_id, stuck_id))
