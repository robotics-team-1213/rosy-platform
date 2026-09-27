---
module: lamp_control
logical_modules: [M02]
owner: 장치
last_verified: { commit: "dc89264", date: 2026-09-17 }
gates:
  SOURCE:
    state: GO
    evidence: "test_lamp_package_contract 1 passed (2026-09-17 Windows)"
    cmd: "python -m pytest src/lamp_control/test/test_lamp_package_contract.py -q"
  LOCAL:
    state: GO
    evidence: "동일. C++ 노드 빌드는 ROS-SIM/ARTIFACT"
    cmd: "python -m pytest src/lamp_control/test/test_lamp_package_contract.py -q"
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
adrs: [D-57]
plans:
  - docs/plans/2026-09-12-rosy-os-module-evaluation-maintenance-design.md
  - docs/plans/2026-09-15-module-harness-design.md
---
## 지금 상태

- C++ WS2811 lamp 드라이버. GPIO 19 / DMA 10에 8개 LED, `SetLamp` 서비스와 `ColorRGBA` 구독을 제공한다. Gazebo 대응은 `gz_sim/plugins/gz_lamp_control_plugin.cpp`.
- 모듈 경로는 clean이지만 SOURCE 증거 시험이 미커밋 WIP가 있는 `deploy/image/ 빌더`을 읽으므로 `last_verified`는 `uncommitted`다.
- Strip type `WS2811_STRIP_GRB`, 8 pixels — 개수/GPIO 변경은 하드웨어 계약이다.
- `deploy/image/ 빌더`에는 core/io 두 이미지만 있고 lamp_control을 포함하지 않는다. `rpi_ws281x`(`ws2811.h`)는 desktop에 없어 빌드되지 않는다.

## 다음 gate

1. Linux ARM64 ROS 환경에서 ament_lint를 colcon test로 실행해 LOCAL을 채운다.
2. ROS 2 Jazzy 컨테이너 또는 Gazebo 플러그인으로 시각 확인 후 ROS-SIM을 되돌린다.
3. 패키지 소스를 검사하는 host 계약 시험을 추가해 SOURCE를 채운다.
4. hardware 프로필이 `deploy/image/ 빌더`에 배선되면 ARTIFACT blocker를 서명 artifact 발행으로 바꾸고 DEVICE/FIELD를 PARKED에서 HOLD로 올린다.

## 현재 유효한 금지사항

- 픽셀 수/GPIO/DMA 채널을 하드웨어 변경 없이 바꾸지 않는다.
- `ws2811_init` 실패는 조용히 무시하지 않고 로그로 남긴다.
