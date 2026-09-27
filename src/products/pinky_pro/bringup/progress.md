---
module: bringup
logical_modules: [M02, M07, M11]
owner: BRINGUP
last_verified: { commit: "dc89264", date: 2026-09-17 }
gates:
  SOURCE:
    state: GO
    evidence: "모터 명령 경로 static 통합 계약 시험 통과 (2026-09-16 재실행, 9 passed — launch가 모든 모션 한계를 노드에 노출)"
    cmd: "python3 -m pytest test/test_bringup_motor_contracts.py -q"
  LOCAL:
    state: GO
    evidence: "77 passed (2026-09-15 Windows, 미커밋 WIP 포함 작업 트리). AGENTS.md 지정 4개 파일 + 신규 test_pinky_pro_adapter.py"
    cmd: "python3 -m pytest test/test_motor_control.py test/test_bringup_motor_contracts.py test/test_dynamixel_driver_safety.py src/bringup/test/test_command_deadman.py src/bringup/test/test_pinky_pro_adapter.py -q"
  ROS-SIM:
    state: HOLD
    blocker: "Dynamixel/LiDAR/battery publisher 노드의 ROS 2 Jazzy 실물 또는 컨테이너 재실행 증거 없음"
  ARTIFACT:
    state: HOLD
    blocker: "ARM64 로봇 이미지에 포함되나(Dockerfile/compose) 서명 manifest와 immutable digest 발행 전"
  DEVICE:
    state: HOLD
    blocker: "Pi bench Device 설치와 device-readback.sh --json 증거 없음. PinkyProAdapter의 실장치 SDK 구동 확인도 미실행"
  FIELD:
    state: PARKED
adrs: [D-14, D-22, D-57, D-58]
plans:
  - docs/plans/2026-09-13-rosy-os-device-validation-implementation-plan.md
  - docs/plans/2026-09-15-module-harness-design.md
---
## 지금 상태

- Dynamixel differential-drive, odometry/TF, 선택적 LiDAR/배터리 publisher, `core`와 독립된 driver-side `cmd_vel` deadman을 제공한다(D-22).
- 신규(미커밋) `PinkyProAdapter`는 ROS-free validation boundary다 — 전체 파라미터 매핑을 SDK 생성 전에 검증하고, 장치를 열거나 명령을 보내지 않는다(D-57: 보드·벤더 차이는 어댑터에 격리).
- 기본 시리얼 `/dev/ttyAMA4`, baud `1_000_000`, IDs `[1, 2]`(좌/우) — 강제 변환 금지. 드라이버가 RPM 한계와 32-bit encoder wrap을 CORE가 죽어도 강제한다.
- stale `cmd_vel` → `CommandDeadman`이 확인된 zero-RPM 정지로 처리한다.
- 작업 트리 미커밋 변경: `AGENTS.md` 2건, `config/rosy_params.yaml`, `launch/bringup_robot.launch.py`, `bringup.py`, 신규 `pinky_pro_adapter.py`(+`config/pinky_pro_adapter.yaml`+시험). LOCAL 증거는 이 작업 트리 기준이다.

## 다음 gate

1. WIP를 커밋하고 LOCAL을 커밋 기준으로 재실행해 `last_verified.commit`을 채운다.
2. ROS 2 Jazzy 실물 또는 컨테이너에서 Dynamixel/LiDAR/battery 노드를 재실행해 ROS-SIM을 채운다.
3. 서명된 ARM64 artifact 발행 후 Pi 설치+readback, `PinkyProAdapter`의 실장치 SDK 구동 확인(ARTIFACT → DEVICE).

## 현재 유효한 금지사항

- `motor_control.py`, `command_deadman.py`는 `rclpy` 없이 import 가능해야 한다(repo `test/`가 직접 사용).
- 기본 시리얼 포트·baud·모터 ID를 강제로 바꾸지 않는다.
- `PinkyProAdapter`는 완전한 매핑 검증 전에는 장치를 열거나 명령을 발행하지 않는다.
