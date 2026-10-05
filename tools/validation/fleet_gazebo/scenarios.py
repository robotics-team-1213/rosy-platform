"""D-426 Task 5 — 장애 주입 시나리오 정의 (ROS-free).

회차별 수용 행렬(계획 M01–M08)과 장애 주입(blackhole·재시작·역순)의
선언적 정의. runner(T6)가 이 정의를 읽어 실제 회차를 만들고, 판정은
probe(T2)·assertions(T3)가 내린다 — 이 모듈은 시나리오의 형태만 갖는다.

주입 규칙(계획 T5 항목 1·4):
- injector는 해당 run 소유 프로세스/프록시만 대상으로 한다(run_id 경계).
- REST-only·WS-only·둘 다 blackhole 은 별도 회차로 실행한다.
- shutdown 시험을 packet blackhole 증거로 쓰지 않는다.
- D-419 기본 STOP 은 마지막 허브 수신 후 timeout+timer 여유(5.0+0.2 s)안에
  정책 적용. 실제 정지(속도·감속)는 별도 측정 — 같은 시한으로 쓰지 않는다.
- 시뮬 profile: v_max 0.15 m/s, w_max 0.5 rad/s. 정책 적용 후 정지 ≤0.50 sim s,
  이동 ≤0.05 m, 회전 ≤0.25 rad. CORE kill 은 입력 만료 ≤0.30 monotonic s 뒤
  같은 정지 제한.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math

#: 시뮬 profile 상한(장치 프로필이 아니라 검증 회차의 상한).
SIM_PROFILE = {"v_max_mps": 0.15, "w_max_radps": 0.5}

#: D-419 기본 STOP 정책 적용 시한(마지막 허브 수신 후).
FLEET_LOSS_POLICY_WINDOW_S = 5.0 + 0.2

#: 정책 적용 뒤 실제 정지 제한(sim 시계).
STOP_LIMITS = {"stop_time_s": 0.50, "travel_m": 0.05, "rotation_rad": 0.25}

#: CORE kill 뒤 sim base watchdog 입력 만료(monotonic).
CORE_KILL_INPUT_EXPIRY_S = 0.30


@dataclass(frozen=True)
class Blackout:
    """run 소유 프로세스/프록시에만 적용하는 통신 차단."""

    kind: str            # "rest" | "ws" | "both"
    target: str          # "robot:rosy_01" | "fleet" ...
    scope: str = "run"   # run_id 경계 안에서만 적용

    def __post_init__(self) -> None:
        if self.kind not in ("rest", "ws", "both"):
            raise ValueError(f"unknown blackout kind: {self.kind}")
        if self.scope != "run":
            raise ValueError("the injector may only touch this run's processes")


@dataclass(frozen=True)
class Scenario:
    """M01–M08 회차 하나의 필수 단언과 주입."""

    scenario_id: str
    requires: tuple[str, ...]              # 필수 판정 이름(probe/assertions)
    blackouts: tuple[Blackout, ...] = field(default_factory=tuple)
    restarts: tuple[str, ...] = field(default_factory=tuple)   # "fleet" | "core:rosy_01"
    note: str = ""


def acceptance_matrix() -> list[Scenario]:
    """계획 §회차별 수용 행렬 M01–M08."""
    return [
        Scenario(
            "M01", requires=(
                "session.welcome", "dispatch-chain", "arrival", "standstill",
                "claimed-motion", "stranger-motion"),
            note="두 대 등록·개별 목표 — 다른 로봇 오작동 0"),
        Scenario(
            "M02", requires=(
                "session.welcome", "dispatch-chain", "segment-state",
                "standstill", "clearance", "contacts"),
            note="교차로 동시 접근 — 동시 점유 0, 대기점 정지, 출구 확인 후 진입"),
        Scenario(
            "M03", requires=(
                "clearance", "contacts", "arrival", "dispatch-chain"),
            note="좁은 통로 마주 접근 — 밖에서 대기, contact 0, footprint 여유"),
        Scenario(
            "M04", requires=("segment-state", "frame-consistency"),
            blackouts=(Blackout("ws", "robot:rosy_02"),),
            note="출구 장애물·위치 stale — 새 진입 금지, 불명 Task 자동 재생 0"),
        Scenario(
            "M05", requires=("pose-freshness", "standstill", "segment-state"),
            blackouts=(Blackout("rest", "robot:rosy_01"), Blackout("ws", "robot:rosy_02"),
                       Blackout("both", "fleet")),
            note="REST/WS/전체 blackhole — 점유 자동 해제 0(별도 회차로 실행)"),
        Scenario(
            "M06", requires=("dispatch-chain", "session.welcome"),
            restarts=("fleet", "core:rosy_01"),
            note="재시작·결과 역순 — 중복 부작용 0, 옛 결과로 새 Task 완료 0"),
        Scenario(
            "M07", requires=("dispatch-chain", "standstill"),
            note="취소/발행 경합·비상 정지 — 응답/실제 정지 분리"),
        Scenario(
            "M08", requires=("observation-rate", "frame-consistency"),
            note="pause/reset·관측 누락 — 잘못된 성공 0, 불명 회차 INCONCLUSIVE"),
    ]


def stop_policy_checks(*, last_hub_receipt_mono: float, policy_applied_mono: float,
                       stopped_at_mono: float, travel_m: float, rotation_rad: float):
    """D-419 정책 적용 시한과 실제 정지를 나눠 판정(같은 시한으로 쓰지 않는다)."""
    problems = []
    values = (last_hub_receipt_mono, policy_applied_mono, stopped_at_mono, travel_m, rotation_rad)
    if not all(type(value) in (int, float) and math.isfinite(value) and value >= 0 for value in values):
        return {'ok': False, 'problems': ['stop facts must be finite and nonnegative']}
    if not last_hub_receipt_mono <= policy_applied_mono <= stopped_at_mono:
        return {'ok': False, 'problems': ['stop timeline is reversed']}
    applied_after = policy_applied_mono - last_hub_receipt_mono
    if applied_after > FLEET_LOSS_POLICY_WINDOW_S:
        problems.append(
            f"policy applied {applied_after:.2f}s after last hub receipt "
            f"(window {FLEET_LOSS_POLICY_WINDOW_S}s)")
    stop_time = stopped_at_mono - policy_applied_mono
    if stop_time > STOP_LIMITS["stop_time_s"]:
        problems.append(f"stop took {stop_time:.2f}s > {STOP_LIMITS['stop_time_s']}s")
    if travel_m > STOP_LIMITS["travel_m"]:
        problems.append(f"traveled {travel_m:.3f}m > {STOP_LIMITS['travel_m']}m")
    if rotation_rad > STOP_LIMITS["rotation_rad"]:
        problems.append(
            f"rotated {rotation_rad:.3f}rad > {STOP_LIMITS['rotation_rad']}rad")
    return {"ok": not problems, "problems": problems}
