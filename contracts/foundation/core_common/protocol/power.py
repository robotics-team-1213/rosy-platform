"""Power wire models (PWR-001~005, D-440). Re-exported by `schemas.py`; import them from there."""

from __future__ import annotations

import enum
from typing import Optional

from pydantic import BaseModel, Field


class PowerMode(str, enum.Enum):
    """센서·디스플레이 듀티 사이클 모드. 모터 안전 경로와 무관하다."""

    ACTIVE = "ACTIVE"      # 상시 — 활동 중이거나 깨어 있음
    IDLE = "IDLE"          # 저속 샘플링, LCD 디밍
    STANDBY = "STANDBY"    # 최저 샘플링, LCD 소등


class PresenceState(str, enum.Enum):
    """초음파 근접 판정 결과 (표시 전용 — 장애물 회피는 Nav2 담당)."""

    NONE = "none"
    NEAR = "near"          # near_m 이내 접근
    CONTACT = "contact"    # contact_m 이내 — 접촉으로 간주


class DevicePowerState(BaseModel):
    """기기별 전원 정책 상태 (D-24 개정 + 기기별 전원 정책 ADR, 2026-10-04)."""

    name: str
    level: str = "on"               # on | reduced | off
    ready: bool = True              # 출력을 신뢰할 수 있는가 (wake_ready_s 경과 + 어댑터 보고)
    managed: bool = False           # 정책이 실제로 이 기기를 움직이는가 (벤치 스위치)
    required_for_motion: bool = False


class PowerStatus(BaseModel):
    mode: PowerMode = PowerMode.ACTIVE
    presence: PresenceState = PresenceState.NONE
    info_visible: bool = False
    sample_rate_hz: float = 20.0
    last_wake_reason: Optional[str] = None
    idle_seconds: float = 0.0
    lidar_spinning: bool = True     # PWR-005 LiDAR 모터 회전 의도
    lidar_ready: bool = True        # 스핀업 완료 — 스캔을 신뢰할 수 있는가
    devices: list[DevicePowerState] = Field(default_factory=list)   # 선언된 기기만
    motion_ready: bool = True       # required_for_motion 기기가 모두 준비됨 (아니면 cmd_vel 0)
