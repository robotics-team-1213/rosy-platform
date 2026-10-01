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

## 2026-09-30 · uncommitted · test(bringup): ADC 소유권 계약을 D-344 §12에 맞춰 갱신

- 변경: D-344 §12(lane-departure guard)의 rosy-io 배선이 `enable_ir`(기본 false, IfCondition 게이트, line_follow 이중 시작 경고 포함)로 랜딩됐는데 계약 시험이 구버전 단순 금지(`'ir_adc_node' not in code`)였다. 조사 결론: 버스 안전은 D-192 flock이 이미 소유(시험 docstring 자체가 ir_adc_node를 합법 판독기로 명시), 금지의 실제 의도는 토픽 배치 규칙 — D-344가 그 예외를 명시적으로 처방했다. 시험을 계약대로 갱신: 기본 false 선언·게이트가 실행 뒤에 있음·이중 시작 경고 문구를 단언.
- 증거: test_adc_ownership 3 passed; 변이 증명 — 조건을 다른 플래그로 바꾸면 적발, 기본값을 true로 바꾸면 적발 (2026-09-30 Windows).
- gate 변화: 없음.
- 결정: 없음.
- 교훈: "위반"이 잡히면 먼저 어떤 결정이 그 행위를 승인했는지 ADR을 뒤져라 — 이번 경우 계약 시험 자체가 결정보다 오래돼 있었다.

## 2026-10-01 · 79b7681a · feat(bringup): 승인된 바퀴 보정 레코드를 읽는다 (D-47 부록)
- 변경: `wheel_calibration.calibrated_wheels()` — 승인된 `wheel_odometry` 레코드가 있으면 그 반지름·간격, 없으면 파라미터(0.027/0.0961, 씨앗). bringup 이 쓴 값과 레코드 id·sha 또는 출처를 로그에 남긴다. core_common 이 이미지에 없으면 파라미터 그대로.
- 증거: `test_wheel_calibration.py` 2 passed, 기존 adapter/no-motion 시험 통과 (2026-10-01 Windows).
- gate 변화: SOURCE. 승인 레코드가 생기기 전까지 장치 동작 불변.

## 2026-10-01 · a103808b · fix(bringup): 비상식적 바퀴 레코드 거부 (H2)
- 변경: 승인된 wheel_odometry 레코드가 0.027/0.0961 ±10 % 밖이거나 bool·문자열이면 파라미터를 유지하고 이유를 로그한다.
- 증거: test_wheel_calibration.py 7 passed (2026-10-01 Windows).
- gate 변화: 없음.

## 2026-10-01 · feat/urdf-nominal-geometry · feat(bringup): 바퀴 기본값을 URDF NOMINAL로, launch 인자는 운영자 덮어쓰기 (D-397)
- 변경: `rosy_params.yaml`·`pinky_pro_adapter.yaml`·adapter `DEFAULTS`·노드 기본값 0.027/0.0961 → 0.028/0.0971. launch `wheel_radius`/`wheel_separation` 기본 0.0(없음) → `*_override` 파라미터, 양수는 승인 레코드를 이기고 NaN·음수는 버리고 경고.
- 증거: `test_wheel_calibration.py`(순서, 0·NaN·음수, 비현실 값 거부), `test/test_bringup_motor_contracts.py`.
- gate 변화: SOURCE/LOCAL. DEVICE HOLD — 레코드 없는 로봇은 오도메트리가 약 3.7 % 바뀐다. 8kcn·9dfk 레코드는 배포 전/함께 승인.
- 결정: D-397 Proposed.
