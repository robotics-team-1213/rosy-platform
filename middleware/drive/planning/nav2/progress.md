---
module: navigation
logical_modules: [M06, M07, M11]
owner: NAV
last_verified: { commit: "83db3b1da4", date: 2026-10-17 }
gates:
  SOURCE:
    state: HOLD
    blocker: "native AMCL/static은 검증했지만 CORE 연결·운영 failed-config 정리·FULL CI 미완료. branch safety exception ancestry guard 1 FAIL(이번 변경 이전 cb19bf69f도 재현, 현재 main은 PASS)"
    evidence: "00945893a5 원격 9대상 207 PASS/1 FAIL/0 SKIP/NEW 1. 상세 station-native-map-static-2026-10-17/result.md"
    cmd: "python tools/remote/remote_pytest.py --sha 00945893a5 --log-dir C:/DevTemp/station-charge/native-map-static-source-guards-00945893a -- test/test_harness_contracts.py test/architecture/test_module_structure.py test/architecture/test_safety_separation.py test/test_safety_review.py test/test_nav2_hardware_slice.py test/test_nav2_profile_limits.py test/test_nav2_bandwidth_contracts.py test/test_footprint_profiles.py contracts/ros_idl/test/test_srv_surface.py -q"
  LOCAL:
    state: GO
    evidence: "83db3b1da4 승인 AI 시험 PC: 같은 SHA interfaces/navigation opt-in 생성·compile/link 및 실제 gtest grid6+AMCL10+static14=30 PASS/0 FAIL/0 SKIP, 설치 standalone 초기 graph/정상 종료 PASS. native slice만 수용, CORE/장치 검증 아님"
    cmd: "python tools/remote/remote_sim.py --sha 83db3b1da4 --minutes 45 --log-dir C:/DevTemp/station-charge/native-map-static-83db3b1da4-attempt-1 cmd -- bash middleware/drive/planning/nav2/test/validate_native_static.sh"
  ROS-SIM:
    state: HOLD
    blocker: "실제 AMCL/static native/DDS와 설치 초기 graph는 검증했다. 전체 Nav2/CORE 운행·charging cycle·station relocation 검증은 남아 있다"
  ARTIFACT:
    state: HOLD
    blocker: "ARM64 로봇 이미지에 포함되나(Dockerfile/compose) 서명 manifest와 immutable digest 발행 전"
  DEVICE:
    state: HOLD
    blocker: "Pi bench Device 설치와 device-readback.sh --json 증거 없음"
  FIELD:
    state: PARKED
adrs: [D-2, D-3, D-4, D-40, D-54, D-58, D-144, D-182, D-184, D-783]
plans:
  - docs/plans/2026-10-17-native-map-adoption.md
  - docs/plans/2026-09-13-rosy-os-device-validation-implementation-plan.md
  - docs/plans/2026-09-15-module-harness-design.md
  - docs/plans/2026-09-21-hardware-mapping-g5-design.md
  - docs/plans/2026-09-21-hardware-mapping-g5.md
---
## 지금 상태

- Nav2와 SLAM Toolbox의 launch/config/맵. Flask UI는 D-3로 `core` FastAPI에 완전히 대체되어 삭제됐다.
- 패키지 전용 pytest는 없고 repo 루트 `test/`가 launch/policy 계약을 검사한다. D-783의 native gtest와 원격 검증 script는 `test/`에 추가했다.
- Nav2 `velocity_smoother` 출력은 `nav_cmd_vel`로 remap되어 CommandManager가 최종 `cmd_vel`을 소유한다(D-2).
- `profile_limits.py`는 Device 모션 상한의 launch-time guard다 — hardware launch override로 우회하지 않는다.
- 기본 OFF native opt-in은 원본 canonical helper와 실제 standalone AMCL/전역 StaticLayer의 채택·적용 readback을 제공한다. [검증 기록](../../../../docs/validation/station-native-map-static-2026-10-17/result.md)은 setup/정리 실패·진단·실제30건·기존 branch guard 실패·실기 미확인을 구분한다. CORE 권한 연결과 운영 failed-config 정리는 아직 남아 있다.

## 다음 gate

1. 실제 native readback을 CORE immutable parent/final writer 거절에 연결하고 운영 failed-config 정리까지 검증한다.
2. branch safety 이력 검사 실패를 착지 전에 해결하고 FULL CI·전체 lifecycle/relocation 검증을 수행한다.
3. 서명된 ARM64 artifact 발행 후 Pi readback(ARTIFACT → DEVICE).

## 현재 유효한 금지사항

- `gz_bringup_launch.xml`은 `bringup_launch.xml`을 include한다 — 로봇용 Nav2 XML을 fork하지 않는다.
- `profile_limits`는 더 높은 hardware launch override로 우회하지 않는다(D-54).
- TF/param 정책은 `launch/`가 아니라 `navigation.*`에 둔다.
- mapper `scan_topic`의 절대/네임스페이스 여부를 `gz_multi.launch.py`와 별도로 가정하지 않는다.
