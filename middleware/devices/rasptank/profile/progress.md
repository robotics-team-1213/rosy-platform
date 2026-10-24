---
module: rasptank_metal
logical_modules: []
owner: 로봇 통합
last_verified: {commit: "uncommitted", date: 2026-10-25}
gates:
  SOURCE:
    state: HOLD
    blocker: "설정 전용 후보. 원격 프로파일·capability 계약 시험 결과 미확인"
  LOCAL:
    state: HOLD
    blocker: "승인 시험 PC 자원 대기; 로컬 pytest로 대체하지 않음"
  ROS-SIM:
    state: HOLD
    blocker: "ament install/share와 ROS 실행 검증 미수행"
  ARTIFACT:
    state: HOLD
    blocker: "Pi 4 native payload와 서명된 ROSY 통합 이미지 없음"
  DEVICE:
    state: HOLD
    blocker: "기체 미도착. 모델 결속·I/O·전원·독립 정지·보정·실물 수용 미수행"
  FIELD:
    state: HOLD
    blocker: "현장 수용 미수행"
adrs: [D-14, D-161, D-856]
plans:
  - docs/plans/2026-10-25-rasptank-multi-robot-design.md
---

## 지금 상태

`robot.model` / `ROSY_ROBOT=rasptank_metal`이 선택할 소스 설정을 준비한다. 모든 물리 기능을 광고하지 않는 출발점이며, 설치·부팅·물리 정지 보장이 아니다. `profile.yaml`, `capabilities.yaml`, 필수 `core.yaml`만 제공하고 기존 CORE 코드는 바꾸지 않는다.

## 다음 확인

1. 원격 source selection·load_config·TaskKind 거절·descriptor 시험.
2. native ament package/share 설치와 제품 model/profile/capability 결속.
3. 실제 HAT 식별·단일 I/O owner·독립 정지와 관절/센서 보정.
4. 기능별 이미지·장치·현장 수용 후에만 해당 capability 변경.
