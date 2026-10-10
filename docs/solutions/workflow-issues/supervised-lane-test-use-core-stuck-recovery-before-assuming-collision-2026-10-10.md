---
title: "현장 감독 차선 시험은 실제 막힘 근거와 관제 탈출 로직으로 처리한다"
date: 2026-10-10
category: workflow-issues
module: "CORE line follow and Fleet stuck recovery"
problem_type: workflow_issue
component: development_workflow
severity: high
root_cause: missing_validation
resolution_type: workflow_improvement
applies_when:
  - "an operator requests a supervised real robot lane-follow test"
  - "a nearest LiDAR return is used to assert a physical collision"
  - "a stationary robot already has CORE and Fleet stuck recovery"
tags: [line-follow, stuck-recovery, supervised-test, lidar, self-mask, fleet, d-407, d-574, d-614]
---

# 현장 감독 차선 시험은 실제 막힘 근거와 관제 탈출 로직으로 처리한다

## Context

2026-10-10 사용자는 두 로봇에 v2 drivable 모델을 적용하고 실제 차선추종 시험을 요청했으며 현장 감독 가능 상태를 확인했다. 모델 적용과 정지 추론은 확인했지만, 어시스턴트는 LiDAR 최단값을 실제 정면 벽으로 단정해 시험을 멈췄다. 원시 좌표를 읽은 결과 가까운 반환은 오른쪽 측면이었고, 정면 거리는 더 길었다. 측면 반환이 외부 물체인지 자체 반사인지는 확정되지 않았다. 이 확인 전에는 충돌 위치를 특정할 근거가 없었다.

사용자의 후속 요청은 "그걸 기록해두고 교훈에다가 관제에서 하면 너가 그걸 로직에 따라서 탈출하면 되잖아"였다. **현장 감독 차선 시험에서 정지 사유를 확인하고 관제의 기존 탈출 흐름을 끝까지 처리한다**는 실행 의도를 기록한다. 직전의 안전장치 전체 해제 요구는 구현하지 않았다. 이 문서는 안전장치 해제 승인이나 탈출 성공 증거가 아니다.

## Guidance

1. **충돌을 주장하려면 위치와 반사원을 먼저 확인한다.** 원시 LiDAR 각도·로봇 좌표·몸체 바깥 거리·표본 시각을 읽고 카메라와 비교한다. 중심 거리, 몸체 바깥 여유, 회전 반경을 구분한다. 자체 반사가 의심되면 검증된 좁은 self-mask 교정을 검토한다. 최단값 하나만으로 정면 벽이나 충돌을 단정하지 않는다.

2. **현장 감독 확인은 같은 세션에서 반복해서 묻지 않는다.** 이미 확인된 현장 감독과 주행 의도를 유지하고 장치 상태 변화나 새로운 물리 위험이 있을 때만 필요한 정보를 보충한다. 임시 시험 도구의 관측 결과와 설치된 차선추종 제어의 판단을 혼동하지 않는다.

3. **막히면 실제 CORE 상태에서 열린 막힘을 읽는다.** `middleware/core/services/core_features/line_follow/recovery/stuck_wiring.py`는 정해진 시간 동안 명령이 0인 상태를 `no_motion`과 원래 정지 사유로 보고한다. 보고 시간 설정과 해당 기능의 활성 여부를 확인한다. `line_follow.stuck`의 현재 식별자·원인·단계와 관제 응답을 기록한다. `OFF` 상태에서는 막힘 탈출 시험이 실행됐다고 말하지 않는다.

4. **관제 결정은 기존 계약으로 전달한다.** Fleet의 `POST /api/fleet/robots/{robot_id}/line-stuck/decision`과 CORE의 `POST /api/v1/line-follow/stuck/decision`을 사용한다. 재개와 후진 재시도는 각각 `RESUME`, `BACK_AND_RETRY`다. Fleet의 이동 결정에는 이름 있는 운영자가 필요하다. 현재 `stuck_id`를 전달하고 CORE 결과를 읽는다. 전송 타임아웃이면 먼저 상태를 다시 읽고, 오래된 식별자로 재시도하지 않는다.

5. **탈출은 승인만으로 완료되지 않는다.** `middleware/core/services/core_features/line_follow/recovery/stuck_recovery.py`의 `answer`는 식별자와 센서 조건을 다시 확인한다. `BACK_AND_RETRY`는 로컬 복구 활성·시도 예산·후방 근거를 검사하고, `RESUME`는 스캔 시각과 정지 거리를 검사한다. `YIELD` 회전의 `_TURN_CLEAR_M`은 몸체 회전 반경 바깥 0.02 m 여유다. 이 값은 몸체 반경을 2 cm로 바꾼다는 뜻이 아니며, D-574의 출발 절차와도 다른 판정이다. 거절 사유는 관제에 남기고 그 근거를 해결한다.

6. **현장 결과까지 닫는다.** 허용된 탈출에서 회복 단계, 실제 속도/이동, 새 차선 판단, 종료 정지를 관찰한다. E-Stop·통신 watchdog·CORE 몸체 정지는 유지한다. 복구가 거절되거나 끝나지 않으면 원인과 다음 조치를 기록한다. 관제 명령 수락을 실제 탈출 성공으로 보고하지 않는다.

## Verified scope

이번 세션에서 두 로봇의 설치된 `stuck_recovery.py`에 `no_motion`, `BACK_AND_RETRY`, `_TURN_CLEAR_M = 0.02`가 있음을 읽었다. 현재 소스의 API 계약과 거절 처리도 확인했다. 현장의 관제 운영자 세션, resolver 자격과 활성 설정, 막힘 응답 전달 및 실제 이동/탈출은 이번 기록 작업에서 검증하지 않았다. 기존 현장 확인을 새 실물 시험까지 자동으로 최신 상태라 간주하지 않는다.

공통 용어 `Lane stuck`과 `Stuck resolver`는 `CONCEPTS.md`에 이미 정의돼 있어 새 용어를 추가하지 않았다. 결정은 [D-614](../../adr/D-614-drivable-crop128-v2-immediate-paint.md), 장치 정지 추론은 [dry run 기록](../../validation/drivable-v2-dryrun-2026-10-10/result.md), 거리 해석 정정은 [거리 재검토](../../validation/drivable-v2-clearance-review-2026-10-10/result.md)를 따른다.

## When to apply

현장 감독자가 승인한 차선추종 시험에서 어시스턴트가 추정한 장애물 설명과 관제의 실제 막힘 상태가 다르거나, 기존 탈출 기능이 있는데도 정지 확인만 반복할 때 적용한다. 검증되지 않은 안전장치 제거·센서 광역 무시·몸체 기하 축소의 근거로 사용하지 않는다.
