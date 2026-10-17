---
module: interfaces
logical_modules: [M02]
owner: 장치
last_verified: { commit: "8058c3676", date: 2026-10-17 }
gates:
  SOURCE:
    state: GO
    evidence: "f6ae71b14 원격 surface 6 PASS/0 SKIP/NEW 0. native adoption 아님; station-native-map-wire-2026-10-17/result.md"
    cmd: "python tools/remote/remote_pytest.py --sha f6ae71b14 --log-dir C:/DevTemp/station-charge/native-map-contract-green -- contracts/ros_idl/test/test_srv_surface.py -q"
  LOCAL:
    state: GO
    evidence: "8058c3676 AI 시험 PC: 같은 SHA rosidl 생성/provenance, Python 직렬화, C++ compile/link 및 CTest 1 PASS/0 SKIP. ARM64/장치 미검증"
    cmd: "python tools/remote/remote_sim.py --sha 8058c3676 --minutes 45 --log-dir C:/DevTemp/station-charge/native-map-wire-green cmd -- bash contracts/ros_idl/test/validate_map_adoption.sh"
  ROS-SIM:
    state: N/A
  ARTIFACT:
    state: HOLD
    blocker: "io 이미지에 포함된다(deploy/robot/pinky_pro/image/ 빌더 `COPY src/interfaces`, `--packages-select`에 포함). 서명 manifest·OCI archive·immutable registry digest 발행 전"
  DEVICE:
    state: HOLD
    blocker: "Pi OS Lite bench Device의 install-pi.sh 설치, verify-pi.sh, device-readback.sh --json 증거 없음"
  FIELD:
    state: PARKED
adrs: [D-783]
plans:
  - docs/plans/2026-10-17-native-map-adoption.md
  - docs/plans/2026-09-12-rosy-os-module-evaluation-maintenance-design.md
  - docs/plans/2026-09-13-rosy-os-device-validation-implementation-plan.md
  - docs/plans/2026-09-15-module-harness-design.md
---
## 지금 상태

- LED·lamp·brightness·LCD emotion용 custom ROS 2 서비스(rosidl 패키지): `Emotion.srv`, `SetLed.srv`, `SetBrightness.srv`, `SetLamp.srv`. `.srv` 변경 후 `colcon build --packages-select interfaces`와 의존 패키지 재빌드가 필요하다.
- 내부 읽기 전용 `MapAdoption.srv`를 추가했다(D-783). [검증 기록](../../docs/validation/station-native-map-wire-2026-10-17/result.md)은 surface/실제 생성·직렬화와 미구현 native producer·CORE admission을 구분한다. 시험 PC의 생성은 ARM64/장치 설치 증거가 아니다.
- REST/Fleet 계약은 여기 없다 — pydantic 스키마는 `core.protocol.schemas`가 유일 소스다(AGENTS.md).
- `deploy/robot/pinky_pro/image/ 빌더`의 io-build 단계가 `interfaces`를 복사·빌드한다. 이 모듈은 device에 실제로 배포된다.

## 다음 gate

1. 실제 AMCL/전역 StaticLayer producer와 CORE consumer를 같은 SHA의 생성 interface에 연결하고 native 적용·수명·거절 반례를 검증한다. interfaces 변경의 FULL CI는 별도로 남아 있다.
2. 서명된 native ARM64 artifact 발행 후 Pi readback(ARTIFACT → DEVICE), deploy/core와 동일 체인.

## 현재 유효한 금지사항

- REST/Fleet 계약을 이 패키지에 넣지 않는다 — `core.protocol.schemas`가 단일 소스다.
- 하드웨어 노드가 소비하는 request/response 필드는 안정적으로 유지한다(rename은 소비자 전원 동시 갱신 필요).
