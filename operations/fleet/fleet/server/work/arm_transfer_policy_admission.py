"""D-938 정책 승인 — ARM_TRANSFER 팔 이송을 사람 승인과 같은 store 검사로 자동 admit.

D-865 worker(missions/policy_admission_worker.py)의 팔 이송판이다. 판정 core는 같은
PolicyAdmissionCore를 쓰고, admit은 PhysicalTransferStore.admit_by_policy가 사람 admit과
같은 `_admit`(snapshot·정지 세대·capability 신선도 전후 두 번·자원 claim·원장)을 탄다.
capability는 사람 route와 같은 함수로 매번 새로 읽는다. 팔 단계라서 drive-only보다
보수적으로 한 틱에 한 건만 admit한다. 다른 작업이 참여 팔 자원을 쥐고 있으면 claim이
거절되어 HELD로 남고 다음 틱에 다시 본다. 범위 밖 제안(사람 제안 포함)은 조용히
지나친다(감사 홍수 방지). 규칙집 law(FL-*)·E-stop·정지 세대는 이 경로도 우회하지 않는다.
"""

from __future__ import annotations

import asyncio
import time

KIND = "arm_transfer"
PERIOD_S = 5.0
BATCH_LIMIT = 20


class ArmTransferPolicyWorker:
    def __init__(self, *, core, store, read_capabilities, dispatcher, audit_log, log, clock=time.time):
        self._core = core
        self._store = store
        self._read_capabilities = read_capabilities
        self._dispatcher = dispatcher
        self._audit = audit_log
        self._log = log
        self._clock = clock
        self._held: dict[str, str] = {}  # mission_id -> last recorded HELD reason (one row per change)

    def _record(self, *, at, mission_id, outcome, scope_revision, generation, reason):
        if outcome == "HELD":
            if self._held.get(mission_id) == reason:
                return
            self._held[mission_id] = reason
        else:
            self._held.pop(mission_id, None)
        self._audit.append(at=at, mission_id=mission_id, outcome=outcome, scope_revision=scope_revision,
                           generation=generation, reason=reason)

    def tick(self) -> int:
        """이번 틱에 내린 판정 수(0 또는 1)."""
        status = self._core.status()
        scope = status.scope
        if not scope.enabled or KIND not in scope.step_approval_kinds or status.admits_remaining <= 0:
            return 0
        candidates = self._store.proposed_ids(limit=BATCH_LIMIT)
        live = {mission_id for mission_id, _ in candidates}
        self._held = {m: r for m, r in self._held.items() if m in live}
        for mission_id, proposer in candidates:
            if self._scope_reason(proposer, status.enabled_by) is not None:
                continue
            return self._admit(mission_id, proposer, status)
        return 0

    def _scope_reason(self, proposer, enabled_by):
        """Live scope judgment for every participant; also run inside the admit transaction."""
        if self._core.status().enabled_by != enabled_by:
            return "ENABLER_CHANGED"
        for participant in self._store.installation.policy.participants:
            reason = self._core.hold_reason(robot_id=participant.instance_id, approval_rule=KIND, proposer=proposer)
            if reason is not None:
                return reason
        return None

    def _admit(self, mission_id, proposer, status) -> int:
        at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self._clock()))
        revision = status.scope.scope_revision
        try:
            capabilities, observed_at = self._read_capabilities()
            job = self._store.admit_by_policy(
                mission_id, scope_revision=revision, enabled_by=status.enabled_by,
                proposers=frozenset(status.scope.proposers), capabilities=capabilities,
                capabilities_observed_at_ns=observed_at,
                recheck=lambda: self._scope_reason(proposer, status.enabled_by))
        except Exception as exc:  # conflict, stale capability, closed generation: next tick re-judges
            self._log.warning("arm transfer policy admission refused for %s: %s", mission_id, exc)
            self._record(at=at, mission_id=mission_id, outcome="HELD", scope_revision=revision,
                         generation=0, reason=f"ADMIT_REFUSED:{type(exc).__name__}")
            return 1
        self._record(at=at, mission_id=mission_id, outcome="ADMITTED", scope_revision=revision,
                     generation=job["dispatch_generation"], reason=None)
        if self._dispatcher is not None and job["status"] == "READY":
            try:
                self._dispatcher.prepare(mission_id)
            except Exception:  # admitted stays admitted, as after a human admit whose prepare failed
                self._log.exception("arm transfer prepare failed after policy admission for %s", mission_id)
        return 1


async def arm_transfer_policy_loop(worker, log, period_s: float = PERIOD_S) -> None:
    """한 틱 실패가 감시를 끝내지 않는다(policy_admission_loop와 같은 모양)."""
    while True:
        try:
            await asyncio.to_thread(worker.tick)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("arm transfer policy admission tick failed")
        await asyncio.sleep(period_s)
