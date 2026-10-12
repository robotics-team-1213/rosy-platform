---
module: description
logical_modules: [M06, M07]
owner: 로봇 통합
last_verified: { commit: "uncommitted", date: 2026-09-21 }
gates:
  SOURCE:
    state: HOLD
    evidence: "2026-10-12 Gazebo 빔 위상 후보 독립 SOURCE 승인·새 원격 회귀 대기; 기존 URDF surface/물리 상세 mesh 계약과 구분"
    blocker: "새 위상 후보의 원격 GREEN 전; 독립 SOURCE 리뷰는 승인"
    cmd: "python tools/remote/remote_pytest.py --log-dir X:/DevTemp/pinky-description -- middleware/devices/pinky/description/test -q"
  LOCAL:
    state: GO
    evidence: "ROS Jazzy 컨테이너에서 xacro 렌더와 primitive collision 계약 통과"
    cmd: "docker exec rosy-map-runtime-work bash -lc 'source /opt/ros/jazzy/setup.bash && python3 -m pytest /ws/src/src/sim/description/test -q'"
  ROS-SIM:
    state: HOLD
    evidence: "새 빔 위상의 전체 동결 source/install 빌드와 실제 CORE 주행 대기; 기존 final_22 수용을 새 후보의 실행으로 대신하지 않음"
    blocker: "새 source/install 전체 빌드·readback과 원본 맵 CORE 주행 미실행"
    cmd: "ros2 launch gz_sim gz_multi.launch.py robots:=1 world_name:=map_260905.world mode:=slam headless:=true core:=true"
  ARTIFACT:
    state: HOLD
    blocker: "io 이미지에 포함된다(deploy/robot/pinky_pro/image/ 빌더 `COPY src/description`, `--packages-select`에 포함; meshes는 `RUN mkdir -p`로 빈 폴더만 생성). 서명 manifest·OCI archive·immutable registry digest 발행 전"
  DEVICE:
    state: HOLD
    blocker: "Pi OS Lite bench Device의 install-pi.sh 설치, verify-pi.sh, device-readback.sh --json 증거 없음"
  FIELD:
    state: PARKED
adrs: [D-4]
plans:
  - docs/plans/2026-09-12-rosy-os-module-evaluation-maintenance-design.md
  - docs/plans/2026-09-13-rosy-os-device-validation-implementation-plan.md
  - docs/plans/2026-09-15-module-harness-design.md
---
## 지금 상태

- 로봇 URDF/xacro, visual/collision meshes, RViz 모델 뷰. 첫 하드웨어는 Pinky Pro다. `namespace`/`frame_prefix`를 지원한다(D-4).
- 시뮬레이션 렌더는 DART 호환 primitive collision과 축 방향 wheel cylinder를 사용하고, 실제 description의 상세 collision mesh는 보존한다.
- `deploy/robot/pinky_pro/image/ 빌더`의 io-build 단계가 `description`을 복사·빌드한다. 단 `.dockerignore`가 `src/description/meshes/**`를 build context에서 제외하고, Dockerfile이 `RUN mkdir -p src/description/meshes`로 빈 폴더만 만든다 — meshes 자체는 device 이미지에 실리지 않는다.
- Gazebo는 `rosy_gz.urdf.xacro`를 쓴다. `left_wheel_joint`/`right_wheel_joint` 이름은 `bringup`과 맞춰야 한다.
- 2026-10-12 원본/반빔 정지 비교는 센서 경계 오차 개선을 지지하지만 회전 안전 거절은 남았다. 새 위상 후보의 SOURCE/ROS-SIM은 재검증 전 HOLD이며 지도 완주·실물 수용을 의미하지 않는다.

## 다음 gate

1. 서명된 native ARM64 artifact 발행 후 Pi readback(ARTIFACT → DEVICE), deploy/core와 동일 체인.
2. 물리 Pinky Pro의 실제 직경·휠 slip·센서 외형을 실측해 simulation primitive와의 허용 오차를 닫는다.

## 현재 유효한 금지사항

- Gazebo 전용 플러그인/토픽을 `rosy_gz.urdf.xacro`에서 깨지 않는다.
- inertia helper는 `urdf/common/insert_inertia.urdf.xacro`에 유지한다.
- `left_wheel_joint`/`right_wheel_joint` 이름을 `bringup`과 어긋나게 바꾸지 않는다.
