---
module: core
logical_modules: [M03, M04, M06, M07, M11, M12, M13]
owner: CORE
last_verified: { commit: "uncommitted", date: 2026-09-22 }
gates:
  SOURCE:
    state: GO
    evidence: "모듈 경계·흡수 소유권 계약 시험 통과 (2026-09-15, core suite와 test/ suite)"
    cmd: "python3 -m pytest src/core/test/test_module_criteria.py test/test_control_absorption_package.py -q"
  LOCAL:
    state: GO
    evidence: "1054 passed, 12 skipped (2026-09-22 Windows). D-162 scene context additive 수용(translate road_evidence, RoadEvidence 선택 필드, ros_bridge sensor snapshot) 포함 — D-137/D-151/D-152 회귀 없음"
    cmd: "PYTHONPATH=src/core:src python3 -m pytest src/core/test -q"
  ROS-SIM:
    state: GO
    evidence: "2026-09-22 WSL Jazzy 재실행(581741e, cmd_vel_cycle·safety.watchdog·감사 로그 compaction 이후 트리): /cmd_vel Publisher count 1(node core), teleop 0.1→송신 중단 약 0.5 s 뒤 0 + safety.watchdog 감사 기록, logs/audit {events, log}, /metrics rosy_audit_* — docs/validation/ros-sim-core-2026-09-22b. SIGTERM 종료 1/6 회 rclpy context 경합 traceback(exit 1), logs.md 후속"
    cmd: "docs/validation/ros-sim-core-2026-09-22b/README.md 절차 — colcon build --packages-up-to core && ros2 run core core + road/observation 프로브 + teleop→워치독 프로브"
  ARTIFACT:
    state: HOLD
    blocker: "ARM64 개발 후보만 존재. 서명 manifest와 immutable digest 발행 전"
  DEVICE:
    state: HOLD
    blocker: "Pi bench Device 설치와 device-readback.sh --json 증거 없음. G4 viewport·보정 상태기계 미실행"
  FIELD:
    state: PARKED
adrs: [D-1, D-2, D-8, D-18, D-23, D-32, D-38, D-42, D-47, D-58, D-60, D-72, D-75, D-77, D-82, D-119, D-121, D-122, D-123, D-124, D-144, D-151, D-152, D-155, D-156, D-157, D-158, D-159, D-162, D-182, D-184]
plans:
  - docs/plans/2026-09-06-module-split-criteria.md
  - docs/plans/2026-09-13-control-safety-boundary.md
  - docs/plans/2026-09-13-rosy-os-device-validation-implementation-plan.md
  - docs/plans/2026-09-15-navigation-swarm-split-design.md
  - docs/plans/2026-09-15-module-harness-design.md
  - docs/plans/2026-09-17-interface-design-implementation-design.md
  - docs/plans/2026-09-21-hardware-mapping-g5-design.md
  - docs/plans/2026-09-21-hardware-mapping-g5.md
  - docs/plans/2026-09-21-semantic-road-control-design.md
  - docs/plans/2026-09-21-semantic-road-control.md
  - docs/plans/2026-09-21-camera-preview-dashboard-design.md
  - docs/plans/2026-09-21-camera-preview-dashboard.md
  - docs/plans/2026-09-22-scene-context-road-design.md
  - docs/plans/2026-09-22-scene-context-road.md
---
## 지금 상태

- 외부 API의 유일한 gateway이고 최종 `cmd_vel`의 유일한 발행자다(D-2, D-38).
- 운용자 콘솔은 `/dashboard`다(D-77). 증거 4상태와 capability 4상태가 HOST 계약 시험으로 산다. G4 DEVICE는 HOLD.
- 흡수된 Control sensor adapter는 기본 비활성이다(D-47).
- 실물 구동 판정은 없다. 이동은 ARTIFACT/DEVICE 이후에만 승격한다.

## 다음 gate

1. ROS Jazzy에서 부트 스모크로 ROS-SIM 복원 — 완료(2026-09-22, docs/validation/ros-sim-core-2026-09-22b, cmd_vel_cycle·감사 로그 compaction 이후 트리).
2. 서명된 native ARM64 artifact 발행 후 Pi readback(ARTIFACT → DEVICE).

## 현재 유효한 금지사항

- API·Nav2·흡수 Control 어디서도 `cmd_vel`을 CORE 밖에서 발행하지 않는다.
- Fleet은 `cmd_vel` 소스가 아니다.
- Pinky+OMX 합성 Asset은 v1이 아니다(D-55, D-71).

## 2026-09-21 supervised traffic-policy status

- CORE는 road evidence를 ROS-free policy로 평가하고 차선 주행 후보를 Command Manager 직전의 원자적 traffic gate에서 제한한다.
- stale/conflict/scene mismatch는 `HOLD`와 zero command다. 정책은 `DISABLED`, `MONITOR_ONLY`, `ENFORCED`로 분리되며 기본값은 `DISABLED`다.
- 관제 stage/apply는 fresh zero velocity 또는 E-stop, `IDLE`/`EMERGENCY`, line-follow OFF를 요구한다. simulation signal은 simulation runtime과 capability가 모두 있어야 한다.
- LOCAL `1005 passed, 11 skipped`; 실제 Chromium stage→apply `1 passed`. 실제 ROS bridge graph와 물리 주행은 여전히 ROS-SIM/DEVICE/FIELD HOLD다.

## 2026-09-21 bounded camera preview status

- Viewer 인증 status/JPEG API는 최대 512000 bytes의 최신 1장만 제공하고 2초 stale이면 404다. JPEG는 CORE에서 디코딩·재인코딩하지 않는다(D-152).
- 대시보드는 지도 위에서 source·해상도·지연과 overlay frame을 표시한다. HOST-SIM Chromium 증거는 통과했지만 실제 Gazebo/Pinky frame readback은 각각 ROS-SIM/DEVICE HOLD다.
