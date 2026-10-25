---
module: rasptank_metal
logical_modules: []
owner: 로봇 통합
last_verified: {commit: "eb616252ea", date: 2026-10-25}
gates:
  SOURCE:
    state: GO
    evidence: "eb616252ea 승인 원격 호스트의 설정·capability·TaskKind·기종 결속 결합 회귀 통과. 설정 전용이며 드라이버/실행 지원 아님"
    cmd: "python tools/remote/remote_pytest.py -- middleware/devices/rasptank/profile/test middleware/core/gateway/test/test_core_node_robot_paths.py -q"
  LOCAL:
    state: GO
    evidence: "승인 원격 source 계약 실행, 결합213 PASS/NEW0. native ament 설치 검증과 구분"
    cmd: "python tools/remote/remote_pytest.py -- middleware/devices/rasptank/profile/test contracts/foundation/test/test_robot_selection.py -q"
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
