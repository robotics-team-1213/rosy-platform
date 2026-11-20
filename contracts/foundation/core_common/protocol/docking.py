"""Canonical docking wire message family; schemas preserves public exports."""
from __future__ import annotations

import enum
from typing import Literal, Optional
from pydantic import BaseModel, Field


class DockState(str, enum.Enum):
    """도킹 상태 (DNC-003).

    계약이 명시한 DOCK/UNDOCK/CHARGING/DOCKED/DOCK_FAILED 을 다듬은 것이다.
    계약에는 "도크에 있지 않다"는 상태가 없는데 로봇은 대부분의 시간을 거기서
    보내고, 도킹이라는 *행위* 와 그 *결과* 가 한 이름에 섞여 있었다.
    enum 값 추가는 additive 이므로 문서의 MINOR 로 기록된다(PRT-006).
    """

    UNDOCKED = "UNDOCKED"        # 기본 — 도크에 있지 않고 가는 중도 아니다
    DOCKING = "DOCKING"          # 시퀀스 진행 중 (스테이징 주행 포함)
    DOCKED = "DOCKED"            # 접점은 물렸으나 충전은 미확인
    CHARGING = "CHARGING"        # 도크가 전류를 보고하고 전압이 떨어지지 않는다
    UNDOCKING = "UNDOCKING"      # 오도메트리만으로 후진 중
    DOCK_FAILED = "DOCK_FAILED"  # 재시도를 소진했다. 명령 전까지 종착이다

class SitePoseEvidence(BaseModel):
    """Fleet's evidence that the robot's map pose is a verified SITE pose (POST /docking/dock, optional, additive). CORE judges it (docking.site_pose.judge_site_pose,
    thresholds in DockingConfig). It verifies POSITION only: heading and the bay entry stay with the LiDAR reference scan. `at` is a record only (host clocks differ)."""

    anchor_source: str                            # "sighting" | "track" | "operator_pin" | "auto_locate" | "peer"; only sighting / track are accepted today
    identity_mode: Optional[str] = None           # "led" | "motion" | None
    anchor_age_s: float                           # age of the anchor on Fleet's side when sent (CORE uses this, never `at`)
    camera_residual_m: Optional[float] = None
    camera_residual_deg: Optional[float] = None
    map_id: str                                   # must equal the robot's map id
    at: float = 0.0                               # UTC seconds, record only


class DockingStatus(BaseModel):
    """상태 스냅샷 additive 필드 (DNC-002)."""

    state: DockState = DockState.UNDOCKED
    dock_id: Optional[str] = None
    phase: Optional[str] = None      # DOCKING 중의 내부 단계
    retries: int = 0
    error: Optional[str] = None
    charge_unconfirmed: bool = False  # DOCKED seat LiDAR-confirmed but no charge evidence: not CHARGING; Fleet shows it apart (additive)
    site_pose_verified: Optional[bool] = None  # CORE's judgement of the dock command's site_pose_evidence (additive); False = a reference-scan bay dock never stages on the map
    site_pose_refusal: Optional[str] = None    # why the evidence was not accepted (None when accepted or when no dock was commanded)
    last_event: Optional[str] = None  # the last retry / reseat / failure with its reason (additive diagnostic: a retry is not an error)
