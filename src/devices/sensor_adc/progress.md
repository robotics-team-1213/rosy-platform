---
module: sensor_adc
logical_modules: [M02]
owner: 장치
last_verified: { commit: "dc89264", date: 2026-09-17 }
gates:
  SOURCE:
    state: GO
    evidence: "test_adc_package_contract 2 passed (2026-09-17 Windows)"
    cmd: "python -m pytest src/sensor_adc/test/test_adc_package_contract.py -q"
  LOCAL:
    state: GO
    evidence: "동일. C++ 노드 빌드는 ROS-SIM/ARTIFACT"
    cmd: "python -m pytest src/sensor_adc/test/test_adc_package_contract.py -q"
  ROS-SIM:
    state: HOLD
    blocker: "C++ 노드(rclcpp)가 있음. ROS 2 Jazzy 컨테이너 재실행 필요, 미실행"
  ARTIFACT:
    state: HOLD
    blocker: "hardware 프로필이 이미지에 배선되지 않았다. core/io 이미지 제외는 test/test_nav2_hardware_slice.py::test_io_image_packages_nav2_without_slam_or_aux_drivers가 고정한다"
  DEVICE:
    state: PARKED
  FIELD:
    state: PARKED
adrs: [D-24, D-57]
plans:
  - docs/plans/2026-09-12-rosy-os-module-evaluation-maintenance-design.md
  - docs/plans/2026-09-15-module-harness-design.md
---
## 지금 상태

- C++ I2C ADC 노드. 채널 0–2 IR, 3 초음파, 4 배터리. `sensor_msgs/Range`, battery state를 발행하고 `power/mode` duty cycling(PWR-001)을 따르되 CORE 부재 시에도 느려지지 않는다.
- 모듈 경로는 clean이지만 SOURCE 증거 시험이 미커밋 WIP가 있는 `deploy/image/ 빌더`을 읽으므로 `last_verified`는 `uncommitted`다.
- 기본 `/dev/i2c-1`, `0x08`. `rate_active`/`rate_idle`/`rate_standby` = 20/5/2 Hz. 유효한 `power/mode` 수신 전까지 시작 rate를 유지한다.
- `deploy/image/ 빌더`에는 core/io 두 이미지만 있고 sensor_adc를 포함하지 않는다. wiringPi I2C는 Pi 전용 의존성이다.

## 다음 gate

1. Linux ARM64 ROS 환경에서 ament_lint를 colcon test로 실행해 LOCAL을 채운다.
2. ROS 2 Jazzy 컨테이너에서 노드 graph/parameter smoke를 실행해 ROS-SIM을 되돌린다.
3. 패키지 소스를 검사하는 host 계약 시험을 추가해 SOURCE를 채운다.
4. hardware 프로필이 `deploy/image/ 빌더`에 배선되면 ARTIFACT blocker를 서명 artifact 발행으로 바꾸고 DEVICE/FIELD를 PARKED에서 HOLD로 올린다.

## 현재 유효한 금지사항

- `power/mode` 정책 판단은 `core`가 소유한다. 이 노드는 구독만 하고 정책을 다시 구현하지 않는다.
- wiringPi I2C 의존을 x86/CI 빌드 경로에 끌어들이지 않는다(CMake가 aarch64로 게이트).
