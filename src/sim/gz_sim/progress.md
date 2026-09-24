---
module: gz_sim
logical_modules: [M03, M07]
owner: SIM
last_verified: { commit: "uncommitted", date: 2026-09-21 }
gates:
  SOURCE:
    state: GO
    evidence: "exact-map route, adaptive speed/recovery, launch/install contracts와 world-to-map 시험 통과 (2026-09-21)"
    cmd: "python -m pytest src/sim/gz_sim/test -q"
  LOCAL:
    state: GO
    evidence: "host 계약과 ROS Jazzy 컨테이너 package build/test 통과; D-151 semantic derived-world identity와 synthetic-camera closed loop PASS; Gazebo 실제 실행은 ROS-SIM 증거"
    cmd: "colcon build --symlink-install --packages-select description core_common gz_sim"
  ROS-SIM:
    state: GO
    evidence: "Gazebo Harmonic final_22 단일 로봇 exact v2 live SLAM: 52/52, 13.754679 m, reachable unknown/occupied 0%, collision false, CORE/Fleet same-run readback"
    cmd: "ros2 launch gz_sim gz_multi.launch.py robots:=1 prefix:=rosy world_name:=map_260905.world mode:=slam headless:=true core:=true"
  ARTIFACT:
    state: N/A
  DEVICE:
    state: N/A
  FIELD:
    state: N/A
adrs: [D-4, D-33, D-49, D-79, D-114, D-115, D-117, D-118, D-120, D-151, D-152, D-199]
plans:
  - docs/plans/2026-09-08-swarm-formation-slice-design.md
  - docs/plans/2026-09-08-swarm-formation-slice.md
  - docs/plans/2026-09-08-swarm-formation-slice-results.md
  - docs/plans/2026-09-15-module-harness-design.md
  - docs/plans/2026-09-21-semantic-road-control-design.md
  - docs/plans/2026-09-21-semantic-road-control.md
  - docs/plans/2026-09-21-camera-preview-dashboard-design.md
  - docs/plans/2026-09-21-camera-preview-dashboard.md
---
## 지금 상태

- `gz_multi.launch.py`로 N대 네임스페이스 로봇을 띄운다. 도메인 하나 + ros_gz_bridge (D-114). `domain_bridge` 없음.
- `mode:=nav` 는 spawn 좌표를 `{ns}/initialpose` 로 심는다 (D-115). odom (0,0) 을 관제 pose 로 쓰지 않는다.
- `world_to_map.py`가 박스 충돌체에서 정답 점유 격자를 만든다. Gazebo 없이 Windows에서 돈다.
- aarch64 CMake는 `return()` — Pi 이미지에 Gazebo를 싣지 않는다.
- 단일 로봇 exact-map live SLAM은 ROS-SIM GO다. 다중 로봇 동시 mapping은 이 증거 범위 밖이다.

## 다음 gate

1. 다중 로봇이 필요할 때 `gz_multi robots:=2 mode:=nav core:=true`를 별도 동시성/port 격리 gate로 실행한다.
2. ARTIFACT/DEVICE는 이 패키지가 로봇 이미지에 없으므로 N/A.

## 현재 유효한 금지사항

- aarch64 `return()`을 고치지 않는다.
- 이 패키지를 로봇 이미지에 넣지 않는다.

## 2026-09-21 semantic-road derived-world status

- 기존 exact-map ROS-SIM GO와 별도로 차선·정지선·횡단보도·신호등을 가진 `map_260905_traffic.world`와 preview를 생성했다.
- semantic identity와 host camera closed loop는 PASS지만 이 변경에서 새 Gazebo camera/ROS graph를 실행하지 않았다. 따라서 기존 mapping ROS-SIM 증거를 semantic perception 증거로 대체하지 않는다.
- `semantic_road_dashboard.launch.py`는 실제 Gazebo camera를 `camera/front`로 opt-in 연결하고 dashboard까지 기동한다. launch 계약은 통과했지만 이 Windows 세션의 screenshot source는 정직하게 `HOST-SIM`이며 실제 `GAZEBO` frame 증거는 HOLD다.
