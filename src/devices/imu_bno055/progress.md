---
module: imu_bno055
logical_modules: [M02, M06]
owner: 장치
last_verified: { commit: "dc89264", date: 2026-09-17 }
gates:
  SOURCE:
    state: GO
    evidence: "3 passed (2026-09-16 재실행) — config 기본값 reset_on_start=false, launch 인자, package.xml 의존성·CMake aarch64 게이트를 패키지 파일에서 직접 단언하는 계약 시험"
    cmd: "python3 -m pytest src/imu_bno055/test/test_package_contract.py -q"
  LOCAL:
    state: GO
    evidence: "3 passed (2026-09-15 Windows, 미커밋 WIP 포함 작업 트리) — config 기본값(reset_on_start=false), launch 인자, package.xml 의존성/CMake aarch64 게이트를 고정하는 ROS-free 계약 시험. `test_driver_faults.py`는 BNO055_TEST_EXECUTABLE 미설정으로 10개 전부 self-skip이며 증거로 세지 않음"
    cmd: "python3 -m pytest src/imu_bno055/test/test_package_contract.py -q"
  ROS-SIM:
    state: HOLD
    blocker: "C++ 드라이버 노드(rclcpp)가 있음. ROS 2 Jazzy 컨테이너 재실행 필요, 미실행"
  ARTIFACT:
    state: HOLD
    blocker: "hardware 프로필이 이미지에 배선되지 않았다(core/io 이미지 제외는 test/test_nav2_hardware_slice.py::test_io_image_packages_nav2_without_slam_or_aux_drivers가 고정). 실물 드라이버 빌드·주입 버스 실행 시험도 Linux ARM64 ROS 환경 필요"
  DEVICE:
    state: PARKED
  FIELD:
    state: PARKED
adrs: [D-56, D-57]
plans:
  - docs/plans/2026-09-12-rosy-os-module-evaluation-maintenance-design.md
  - docs/plans/2026-09-15-module-harness-design.md
---
## 지금 상태

- C++ BNO055 IMU 드라이버 노드. `RealtimePublisher<sensor_msgs::msg::Imu>`로 `imu_raw`를 발행한다. 기본 `/dev/i2c-0`, `0x28`, 100 Hz, `frame_id=imu_link`.
- 작업 트리에 미커밋 변경이 크다: `config/`, `launch/`, `src/bno055_device.{cpp,hpp}`, `src/imu_sample.hpp`, `test/` 신규 추가와 `CMakeLists.txt`/`package.xml`/`main_node.cpp`/`AGENTS.md` 수정. LOCAL·SOURCE 증거는 이 작업 트리 기준이다.
- `SYS_TRIGGER` reset은 `reset_on_start:=true`일 때만 실행되며 기본은 비활성이다(AGENTS.md 2026-09-14 갱신).
- `deploy/image/ 빌더`에는 core/io 두 이미지만 있고 imu_bno055를 포함하지 않는다. 드라이버 빌드는 CMake에서 aarch64로 게이트된다.

## 다음 gate

1. Linux ARM64 ROS 환경에서 드라이버를 빌드하고 `test_driver_faults.py`의 주입 버스 실행 시험을 `BNO055_TEST_EXECUTABLE`로 재실행한다.
2. ROS 2 Jazzy 컨테이너에서 노드 graph/parameter smoke를 실행해 ROS-SIM을 되돌린다.
3. hardware 프로필(D-56 optional IMU)이 `deploy/image/ 빌더`에 배선되면 ARTIFACT blocker를 서명 artifact 발행으로 바꾸고 DEVICE/FIELD를 PARKED에서 HOLD로 올린다.

## 현재 유효한 금지사항

- chip ID 미확인이나 초기화 타임아웃은 stage/register/errno 로그와 함께 nonzero exit로 처리한다(조용한 실패 금지).
- `reset_on_start` 기본값을 false에서 바꾸지 않는다 — 응답 중인 칩을 재시작 사이에 보존하는 계약이다.

## 2026-09-20 health evidence status

- `sensors/imu/status` now includes freshness, sample/error counts, four calibration components, self-test, system status/error, and temperature.
- Health validity requires a fresh sample, fusion system status, zero system error, and passing self-test bits. It does not require magnetometer calibration in IMUPLUS mode.
- Covariance is no longer hard-coded to `0.01`. The three standard-deviation parameters default to `0.0`, producing ROS all-zero unknown covariance, and configured positive values are squared onto the diagonal.
- Host verification: `4 passed, 10 skipped`.
- ARTIFACT HOLD: no Linux ARM64 C++ build in this Windows run.
- DEVICE HOLD: no injected executable or live BNO055 register readback.
- FIELD HOLD: sensor evidence has not been correlated with physical stop and trajectory measurements.
