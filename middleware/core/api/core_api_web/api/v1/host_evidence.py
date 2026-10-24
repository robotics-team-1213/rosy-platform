"""Freshness of Host Agent status observations."""
from datetime import datetime, timezone

from core_common.protocol.evidence import EvidenceState
from core_common.protocol.schemas import HostStatusEvidence
from core_api_web.api.host_agent_client import TIMEOUT, UNAVAILABLE

HOST_STATUS_STALE_AFTER_S = 15.0


def status_evidence(reply) -> HostStatusEvidence:
    base = {"stale_after_s": HOST_STATUS_STALE_AFTER_S}
    if reply.code in {UNAVAILABLE, TIMEOUT}:
        return HostStatusEvidence(evidence=EvidenceState.DISCONNECTED,
                                  reason="Host Agent에 연결되지 않았거나 응답이 시간 안에 오지 않았습니다.", **base)
    if not reply.reachable or not reply.ok:
        return HostStatusEvidence(reason="Host Agent가 완전한 상태 조회 결과를 주지 않았습니다.", **base)
    try:
        observed = datetime.fromisoformat(reply.observed_at) if reply.observed_at else None
    except (TypeError, ValueError):
        observed = None
    if observed is None or observed.tzinfo is None or observed.utcoffset().total_seconds() != 0:
        return HostStatusEvidence(reason="Host Agent 원본 조회 완료 시각이 없습니다.", **base)
    age = (datetime.now(timezone.utc) - observed).total_seconds()
    if age < 0:
        return HostStatusEvidence(reason="Host Agent 원본 시각이 CORE 시각보다 미래입니다.", **base)
    state = EvidenceState.DELAYED if age > HOST_STATUS_STALE_AFTER_S else EvidenceState.FRESH
    return HostStatusEvidence(evidence=state, observed_at=reply.observed_at,
                              age_s=round(age, 1),
                              reason="Host Agent 원본 조회가 지연되었습니다." if state is EvidenceState.DELAYED
                              else "Host Agent 원본 조회 완료 시각을 확인했습니다.", **base)
