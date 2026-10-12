"""Canonical swarm wire message family; schemas preserves public exports."""
from __future__ import annotations

import enum
from typing import Literal, Optional
from uuid import UUID
from pydantic import BaseModel, Field


class SwarmRole(str, enum.Enum):
    NONE = "none"
    LEADER = "leader"
    FOLLOWER = "follower"

class SwarmStatus(BaseModel):
    """상태 스냅샷 additive 필드 (SWM-006)."""

    role: SwarmRole = SwarmRole.NONE
    formation: Optional[str] = None
    active: bool = False

class SwarmReferenceSource(str, enum.Enum):
    """D-21 분산 진화 훅: 참조 pose 스트림 소스 (SWM-007)."""

    FLEET = "fleet"  # 기본 — Fleet 릴레이 (API Ref §7.8)
    PEER = "peer"    # 예약 — 로봇 간 P2P (재검토 트리거 발생 시 구현)

class SwarmFollowParams(BaseModel):
    """POST /api/v1/swarm/follow payload (SWM-002)."""

    target_robot_id: str
    distance: float = 0.5          # 종방향 유지 거리 (m)
    lateral: float = 0.0           # 측방 오프셋 (m)
    max_speed: float = 0.15        # m/s (SAF-004 상한과 별개 추가 제약)
    stream_timeout_ms: int = 1000  # pose 스트림 단절 판정 (SWM-004)
    source: SwarmReferenceSource = SwarmReferenceSource.FLEET  # v1.2 additive
    #: v1 additive. 대형 멤버를 robots.yaml 순서로. 비어 있으면 승계를 하지 않는다.
    members: list[str] = Field(default_factory=list)
    #: D-559 additive. trail = replay the leader's driven path `distance` behind (lateral 0).
    mode: Literal["offset", "trail"] = "offset"
    correlation_id: str | None = Field(default=None, min_length=1, max_length=128)
    expected_boot_id: UUID | None = None
    expected_owner_generation: int | None = Field(default=None, ge=0, strict=True)
