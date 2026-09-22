---
module: omx_adapter
owner: 장치
last_verified: { commit: "uncommitted", date: 2026-09-22 }
gates:
  SOURCE:
    state: GO
    evidence: "test_adapter_manifest + test_omx_profile 10 passed (2026-09-22 Windows)"
    cmd: "python -m pytest src/apps/omx_adapter/test -q"
  LOCAL:
    state: GO
    evidence: "동일. 비활성 프로필 CLI는 `{}`를 출력한다"
    cmd: "python -m pytest src/apps/omx_adapter/test -q"
  ROS-SIM:
    state: PARKED
  ARTIFACT:
    state: HOLD
    blocker: "deploy/image/required-ros-packages.txt에 포함되나 서명 manifest와 immutable digest 발행 전"
  DEVICE:
    state: PARKED
  FIELD:
    state: PARKED
adrs: [D-61, D-147, D-168]
plans:
  - docs/plans/2026-09-15-module-harness-design.md
---
## 지금 상태

- 모델 중립 OMX 프로필 검증기와 `ros2_control`/MoveIt 계약 생성기다. 기본 프로필은 비활성이며 CLI는 `{}`를 낸다.
- 2026-09-22 harness에 처음 등록했다(D-168 P2). 이전 이력은 `git log -- src/apps/omx_adapter`를 본다.
- ROS-SIM/DEVICE/FIELD는 OMX 모델·드라이버·장착·보정이 수용되기 전까지 PARKED다.

## 다음 gate

1. 측정된 드라이버가 선정되면 ROS-SIM을 PARKED에서 HOLD로 올리고 controller 계약 스모크를 정의한다.

## 현재 유효한 금지사항

- 시리얼 포트를 열거나 base `cmd_vel`을 발행하거나 CORE 안전을 우회하지 않는다.
- 비어 있지 않은 `ros2_control_contract()`는 물리 수용이 아니다.
