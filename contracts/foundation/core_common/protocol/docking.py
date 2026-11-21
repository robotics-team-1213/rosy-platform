"""Canonical docking wire message family; schemas preserves public exports."""
from __future__ import annotations

import enum
from typing import Literal, Optional
from pydantic import BaseModel, Field

from core_common.protocol.localization import OdomPose


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


class DockAnchor(BaseModel):
    """The robot is SEATED in a bay at this instant, confirmed by the LiDAR reference scan (additive; DockingStatus.anchor, polled from the state snapshot keyed (dock_id, odom_pose.epoch, at); the event docking.anchor is for the log). A pair at an instant: Fleet binds its odom pose to the
    bay's site pose (position AND heading) and bridges by odom displacement, like any anchor; the camera track takes over afterwards. The odom frame it belongs to ends
    with a CORE restart (the status shows no anchor once `odom_pose.epoch` is no longer the current epoch)."""

    dock_id: str
    confirmation: Literal["lidar_reference"] = "lidar_reference"   # the stopped LiDAR scan matched the dock's reference scan. CORE publishes NO anchor otherwise (a charge contact alone could name the wrong bay)
    source: str                           # "docked": a docking sequence ended in DOCKED; "startup_probe": CORE found itself seated after a (re)start
    odom_pose: OdomPose                   # odom x, y, yaw, stamp (UTC s), epoch at that instant
    boot_id: str                          # the CORE process that recorded it
    map_id: Optional[str] = None
    map_generation: Optional[int] = None  # StateSnapshot.map_generation at that instant (null on a CORE without it): the SLAM map origin epoch the pair belongs to
    along_m: float                        # seat error against the reference scan: out of the stop face, + = short of the seated pose
    lateral_m: float
    heading_deg: float
    inliers: float
    margin: float
    at: float = 0.0                       # CORE wall clock (UTC s) when recorded
    age_s: float = 0.0                    # filled at read time


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
    anchor: Optional[DockAnchor] = None  # the newest seat anchor of this CORE run, hidden when its odom epoch ended (additive)
    last_event: Optional[str] = None  # the last retry / reseat / failure with its reason (additive diagnostic: a retry is not an error)
