"""D-865 P2a 정책 승인 판정 core — 범위·전환·상한·감사 (서버 조립은 P2b).

Fleet이 승인(admit) 권한을 소유한다(사용자 2026-10-25 확정, ADR D-865). 이 모듈은
순수 판정만 한다: 자동 승인 후보가 범위에 닿는지, 상한이 남았는지, 그 결정의 감사
기록. 제안 열거·digest 재판정·generation 결정·admit 호출은 P2b 조립이 기존 mission
경로(mission_routes/mission_store)와 같은 소유에서 한다. 규칙집 law(FL-*)는 이
모듈도 우회하지 않는다.

상한은 이 core의 감사 기록에서 센다(프로세스 수명). 재시작은 설정을 다시 읽고 발행
수는 0에서 시작한다 — 상한의 지속화는 P2b가 감사 저장소를 기존 SQLite와 같은 주인으
로 결속하며 막는다. 그 전에 이 core는 어떤 실행 경로에도 연결되지 않는다.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from core_common.protocol.policy_admission import (
    POLICY_ADMISSION_PRINCIPAL,
    PolicyAdmissionAuditEntry,
    PolicyAdmissionAuditResponse,
    PolicyAdmissionScope,
    PolicyAdmissionStatus,
)

ALLOWED_STEP_APPROVAL_KINDS = frozenset({"one_person"})
AUDIT_LIMIT = 100


@dataclass(frozen=True)
class PolicyAdmissionSettings:
    """``fleet.policy_admission`` 사이트 설정 절 — 사람이 정한 승인 범위(D-865 결정 2)."""
    enabled: bool = False
    robots: frozenset[str] = frozenset()
    step_approval_kinds: frozenset[str] = frozenset({"one_person"})
    max_admits: int = 1
    valid_until: str | None = None
    scope_revision: str = "none"

    @classmethod
    def from_config(cls, section: object) -> "PolicyAdmissionSettings":
        """Fail-closed: 빈 절은 비활성, 활성 절은 로봇·종류·상한을 갖춰야 한다."""
        if section is None:
            return cls()
        if not isinstance(section, dict):
            raise ValueError("fleet.policy_admission must be a mapping")
        robots = frozenset(section.get("robots") or [])
        kinds = frozenset(section.get("step_approval_kinds") or ["one_person"])
        unknown = kinds - ALLOWED_STEP_APPROVAL_KINDS
        if unknown:
            raise ValueError(f"unsupported approval kinds: {sorted(unknown)}")
        max_admits = section.get("max_admits", 1)
        if type(max_admits) is not int or max_admits < 1:
            raise ValueError("max_admits must be an integer >= 1")
        valid_until = section.get("valid_until")
        if valid_until is not None and not isinstance(valid_until, str):
            raise ValueError("valid_until must be an ISO-8601 string or null")
        scope_revision = section.get("scope_revision", "none")
        if not isinstance(scope_revision, str) or not scope_revision:
            raise ValueError("scope_revision must be a non-empty string")
        enabled = bool(section.get("enabled", False))
        if enabled and (not robots or not kinds):
            raise ValueError("an enabled scope must name robots and approval kinds")
        return cls(enabled=enabled, robots=robots, step_approval_kinds=kinds,
                   max_admits=max_admits, valid_until=valid_until,
                   scope_revision=scope_revision)


class PolicyAdmissionCore:
    """범위 상태·운영자 전환(메모리, D-610 패턴)·상한·감사."""

    def __init__(self, settings: PolicyAdmissionSettings, now):
        self._settings = settings
        self._now = now  # callable -> ISO-8601 UTC string
        self._switch = settings.enabled
        self._audit: deque[PolicyAdmissionAuditEntry] = deque(maxlen=AUDIT_LIMIT)

    def scope(self) -> PolicyAdmissionScope:
        return PolicyAdmissionScope(
            enabled=self._settings.enabled and self._switch,
            robots=sorted(self._settings.robots),
            step_approval_kinds=sorted(self._settings.step_approval_kinds),
            max_admits=self._settings.max_admits,
            valid_until=self._settings.valid_until,
            scope_revision=self._settings.scope_revision)

    def _issued(self) -> int:
        return sum(1 for entry in self._audit
                   if entry.scope_revision == self._settings.scope_revision
                   and entry.outcome == "ADMITTED")

    def status(self) -> PolicyAdmissionStatus:
        active = self.scope().enabled
        issued = self._issued()
        remaining = max(self._settings.max_admits - issued, 0) if active else 0
        reason = None
        if not self._settings.enabled:
            reason = "NOT_CONFIGURED"
        elif not self._switch:
            reason = "DISABLED"
        elif remaining == 0:
            reason = "EXHAUSTED"
        return PolicyAdmissionStatus(scope=self.scope(), admits_issued=issued,
                                     admits_remaining=remaining, reason=reason)

    def toggle(self, *, enabled: bool) -> PolicyAdmissionStatus:
        """기명 운영자 전환. 전환은 스위치만 바꾸고 범위 내용은 사이트 설정만 정한다."""
        if enabled and not self._settings.enabled:
            raise ValueError("cannot enable an unconfigured scope")
        self._switch = bool(enabled)
        return self.status()

    def audit(self) -> PolicyAdmissionAuditResponse:
        return PolicyAdmissionAuditResponse(entries=list(self._audit)[::-1])

    def hold_reason(self, *, robot_id: str, approval_rule: str) -> str | None:
        """범위 밖이면 그 사유, 범위 안이면 None(자동 승인 후보)."""
        if not self._settings.enabled:
            return "NOT_CONFIGURED"
        if not self._switch:
            return "DISABLED"
        if approval_rule not in self._settings.step_approval_kinds:
            return "APPROVAL_RULE_OUT_OF_SCOPE"
        if robot_id not in self._settings.robots:
            return "ROBOT_OUT_OF_SCOPE"
        if self._issued() >= self._settings.max_admits:
            return "EXHAUSTED"
        return None

    def record(self, *, mission_id: str, outcome: str, generation: int,
               reason: str | None = None) -> PolicyAdmissionAuditEntry:
        """사람 승인과 같은 원장 행위에 더해 정책 principal·범위 revision을 남긴다."""
        entry = PolicyAdmissionAuditEntry(
            mission_id=mission_id, decided_at=self._now(),
            principal=POLICY_ADMISSION_PRINCIPAL,
            scope_revision=self._settings.scope_revision,
            outcome=outcome, generation=generation, reason=reason)
        self._audit.append(entry)
        return entry
