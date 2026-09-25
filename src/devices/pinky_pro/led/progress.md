---
module: led
logical_modules: [M02]
owner: 장치
last_verified: { commit: "dc89264", date: 2026-09-17 }
gates:
  SOURCE:
    state: GO
    evidence: "test_led_package_contract 2 passed (2026-09-17 Windows). exec_depend interfaces"
    cmd: "python -m pytest src/led/test/test_led_package_contract.py -q"
  LOCAL:
    state: GO
    evidence: "동일. ament linter는 이 호스트에 없어 증거로 세지 않는다"
    cmd: "python -m pytest src/led/test/test_led_package_contract.py -q"
  ROS-SIM:
    state: HOLD
    blocker: "rclpy 서비스 서버(set_led/set_brightness) 노드가 있음. ROS 2 Jazzy 컨테이너 재실행 필요, 미실행"
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

- Python LED 서비스 서버(`led_service_server`)로 `rosylib.LED`를 감싸며 `set_led`/`set_brightness` 서비스(`interfaces`)를 제공한다.
- 모듈 경로는 clean이지만 SOURCE 증거 시험이 미커밋 WIP가 있는 `deploy/image/ 빌더`을 읽으므로 `last_verified`는 `uncommitted`다.
- `test/`는 ament 3종 linter뿐이다. 2026-09-15 재현: `python -m pytest src/led/test/ -q` → 3 errors, `ModuleNotFoundError: No module named 'ament_copyright'`(flake8/pep257도 동일).
- `deploy/image/ 빌더`에는 core/io 두 이미지만 있고 led를 포함하지 않는다.

## 다음 gate

1. ROS 환경(colcon)에서 ament lint 3종을 재실행해 LOCAL을 채운다.
2. ROS 2 Jazzy 컨테이너에서 서비스 노드 graph/parameter smoke를 실행해 ROS-SIM을 되돌린다.
3. 패키지 소스를 검사하는 host 계약 시험을 추가해 SOURCE를 채운다.
4. hardware 프로필이 `deploy/image/ 빌더`에 배선되면 ARTIFACT blocker를 서명 artifact 발행으로 바꾸고 DEVICE/FIELD를 PARKED에서 HOLD로 올린다.

## 현재 유효한 금지사항

- CORE의 battery/LED 정책은 `ros_bridge`를 통해 `set_led`를 호출한다. CORE가 스트립을 직접 구동하지 않는다.
- `rosylib`는 이 repo 밖 하드웨어 헬퍼이며 여기서 재구현하지 않는다.
