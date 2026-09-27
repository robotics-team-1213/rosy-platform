# bringup logs

추가만 한다. 형식: [module harness 설계](../../docs/plans/2026-09-15-module-harness-design.md) §4.2.
2026-09-15 이전 이력은 [Device 검증 계획](../../docs/plans/2026-09-13-rosy-os-device-validation-implementation-plan.md)과 `git log -- src/bringup`를 본다.

## 2026-09-15 · uncommitted · docs(harness): start the bringup harness record
- 변경: `progress.md`, `logs.md` 추가
- 증거: `python -m pytest test/test_motor_control.py test/test_bringup_motor_contracts.py test/test_dynamixel_driver_safety.py src/bringup/test/test_command_deadman.py src/bringup/test/test_pinky_pro_adapter.py -q` 77 passed (2026-09-15 Windows, 미커밋 WIP 포함 작업 트리); `python -m pytest test/test_bringup_motor_contracts.py -q` 5 passed
- gate 변화: 없음. SOURCE/LOCAL GO, ROS-SIM/ARTIFACT/DEVICE HOLD, FIELD PARKED를 처음 기록
- 결정: D-61 Proposed
- 교훈: 없음

## 2026-09-16 · uncommitted · docs(harness): record the bringup source rerun count
- 변경: 위 항목의 `test_bringup_motor_contracts.py` 5 passed는 오기다. `progress.md` SOURCE 증거와 `cmd`(`python3`)를 정정
- 증거: `python3 -m pytest test/test_bringup_motor_contracts.py -q` 9 passed; LOCAL 5개 파일 77 passed (2026-09-16 재실행)
- gate 변화: 없음
- 결정: 없음
- 교훈: 없음

## 2026-09-24 · uncommitted · feat(bringup): rosylib battery, ADC flock and no-motion mode (D-192)
- 변경: `rosylib/`(Rosy 소유 `Battery`, `LED`는 명시적 ImportError), `battery_publisher` 버스 실패 시 미발행, `dynamixel_driver.initialize_motors(enable_torque=False)`, 노드 `drive_enabled` 파라미터와 launch 인자
- 증거: `python -m pytest src/hardware/bringup/test test/test_rosylib_battery_curve.py test/test_dynamixel_driver_safety.py test/test_bringup_motor_contracts.py -q` 통과(2026-09-24 Windows)
- gate 변화: 없음. DEVICE는 D-192 실기 수용 확인 전까지 HOLD
- 결정: D-192 Proposed
- 교훈: 무동작은 발행자가 아니라 액추에이터에서 보장한다

## 2026-09-24 · uncommitted · fix(bringup): D-192 review — read-only drive flag, battery bus retry, behaviour tests
- 변경: `drive_enabled`를 `ParameterDescriptor(read_only=True)`로, `battery_publisher`가 버스 부재·읽기 실패 뒤 타이머에서 다시 연다(그동안 미발행). `test/ros_stubs.py`로 stub rclpy 위에서 `Rosy` 노드와 발행자를 실제로 돌리는 시험, settle 순서를 기록하는 rosylib 시험
- 증거: `python -m pytest src/hardware/bringup/test -q` 통과(2026-09-24 Windows)
- gate 변화: 없음
- 결정: D-192 Proposed
- 교훈: 안전 성질은 소스 문자열이 아니라 가짜 버스 위의 실행으로 고정한다

## 2026-09-25 · uncommitted · refactor(devices): move bringup under src/devices/pinky_pro/bringup (D-231)

- 변경: src/devices/pinky_pro/bringup로 이동, 동작 변경 없음 (D-231)
- 증거: 이 커밋의 장치 시험
- gate 변화: 없음
- 결정: D-231
- 교훈: 없음
