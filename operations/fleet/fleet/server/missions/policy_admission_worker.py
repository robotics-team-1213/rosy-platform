"""D-865 P2c 정책 승인 자동 admit worker — 사람 승인과 같은 검사를 매 주기 적용.

사람 승인 경로(mission_routes.fleet_mission_admit)와 같은 소유의 재료만 쓴다:
RESOLVED 제안(proposal_queries.list_resolved) → 승인 종류(required_approval)·자원
(robot) → 범위 판정(core) → mission_service.admit(expected_generation=제안의
source_dispatch_generation, resources=resolution.resources). admit 트랜잭션이 정지
세대를 다시 검증하므로 세대가 바뀌었으면 MissionConflict 로 HOLD 되고 다음 주기에
다시 본다. 규칙집 law(FL-*)는 사람 승인에 적용되는 것과 같은 admission 안에서
그대로 굴러간다 — 이 worker 는 검사를 줄이지 않는다.

감사·상한은 PolicyAdmissionAuditLog(SQLite)에 지속된다. HELD 기록은 범위 소속
후보가 조건에서 거절된 경우만 남긴다(범위 밖 제안은 조용히 지나친다 — 감시 홍수
방지). digest 재판정(_stable_resolution·resolver 재호출)은 P2b HTTP 표면과 같은
이유로 아직 붙이지 않았다: 운영 candidate_resolver 주입이 확인되지 않았고(admit
경로의 재판정은 해석 주체가 resolver 인 경우만 의미가 있다), 1차 범위는 사람이
resolve 한 제안만 받는다. resolver 연결은 후속 조각이 한다.
"""

from __future__ import annotations

import asyncio
import time

from fleet.server.evidence.proposal_queries import list_resolved
from fleet.server.step_action_kinds import required_approval

PERIOD_S = 5.0
BATCH_LIMIT = 20
ROBOT_KIND = "robot"


class PolicyAdmissionWorker:
    """한 틱: RESOLVED 제안을 훑고 범위 안 one_person 만 자동 승인한다."""

    def __init__(self, *, core, proposal_store, mission_service,
                 audit_log, log, clock=time.time):
        self._core = core
        self._proposal_store = proposal_store
        self._mission_service = mission_service
        self._audit = audit_log
        self._log = log
        self._clock = clock

    def _admitted(self, mission_id: str, generation: int, reason: str | None,
                  at: str, scope_revision: str) -> str:
        outcome = "ADMITTED" if reason is None else "HELD"
        self._audit.append(at=at, mission_id=mission_id, outcome=outcome,
                           scope_revision=scope_revision,
                           generation=generation, reason=reason)
        return outcome

    def _consider(self, proposal, *, at: str, scope_revision: str) -> str | None:
        mission_id = proposal.get("mission_id") or proposal["proposal_id"]
        if proposal.get("state") != "RESOLVED" or not proposal.get("mission_id"):
            return None
        record = self._mission_service.get(mission_id)
        if record is None or record.get("status") != "PROPOSED":
            return None
        try:
            rule = required_approval([record["action_kind"]])
        except ValueError:
            return None  # 등록되지 않은 종류는 사람 영역 그대로
        resources = [tuple(item) for item in
                     (proposal.get("resolution") or {}).get("resources") or []]
        robots = sorted({rid for kind, rid in resources if kind == ROBOT_KIND})
        reason = self._core.hold_reason(
            robot_id=robots[0] if len(robots) == 1 else "",
            approval_rule=rule)
        if reason is None and len(robots) != 1:
            reason = "ROBOT_UNBOUND"  # 로봇이 없거나 여럿이면 사람 승인으로
        if reason is not None:
            return self._admitted(mission_id, -1, reason, at, scope_revision)
        generation = proposal.get("source_dispatch_generation")
        if not isinstance(generation, int) or generation < 0:
            return self._admitted(mission_id, -1, "GENERATION_UNKNOWN",
                                  at, scope_revision)
        try:
            self._mission_service.admit(
                mission_id, actor_id="fleet-policy-admission",
                expected_generation=generation, resources=resources)
        except Exception as exc:  # MissionConflict/ValueError/KeyError: 다음 틱 재판정
            self._log.warning("policy admission admit refused for %s: %s",
                              mission_id, exc)
            return self._admitted(mission_id, generation, "ADMIT_REFUSED",
                                  at, scope_revision)
        return self._admitted(mission_id, generation, None, at, scope_revision)

    def tick(self) -> int:
        """이번 틱에 내린 판정 수. 비활성 범위는 0."""
        status = self._core.status()
        if not status.scope.enabled:
            return 0
        at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self._clock()))
        scope_revision = status.scope.scope_revision
        decisions = 0
        for proposal in list_resolved(self._proposal_store, limit=BATCH_LIMIT):
            if self._core.status().admits_remaining <= 0:
                break
            outcome = self._consider(proposal, at=at, scope_revision=scope_revision)
            decisions += 1 if outcome else 0
        return decisions


async def policy_admission_loop(worker, log, period_s: float = PERIOD_S) -> None:
    """lane_compliance_loop 패턴: 한 틱 실패가 감시를 끝내지 않는다."""
    while True:
        try:
            await asyncio.to_thread(worker.tick)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("policy admission tick failed")
        await asyncio.sleep(period_s)
