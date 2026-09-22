---
module: description
logical_modules: [M06, M07]
owner: 로봇 통합
last_verified: { commit: "uncommitted", date: 2026-09-21 }
gates:
  SOURCE:
    state: GO
    evidence: "URDF surface 및 sim collision geometry 계약 통과 (2026-09-21); 물리 description의 상세 mesh는 보존"
    cmd: "python -m pytest src/sim/description/test -q"
  LOCAL:
    state: GO
    evidence: "ROS Jazzy 컨테이너에서 xacro 렌더와 primitive collision 계약 통과"
    cmd: "docker exec rosy-map-runtime-work bash -lc 'source /opt/ros/jazzy/setup.bash && python3 -m pytest /ws/src/src/sim/description/test -q'"
  ROS-SIM:
    state: GO
    evidence: "Gazebo Harmonic final_22: exact v2 world 52/52, 13.754679 m, collision overlap false, minimum body margin 0.021789 m; model-pose odom과 wheel diagnostic odom 분리"
    cmd: "ros2 launch gz_sim gz_multi.launch.py robots:=1 world_name:=map_260905.world mode:=slam headless:=true core:=true"
  ARTIFACT:
    state: HOLD
    blocker: "io 이미지에 포함된다(deploy/image/ 빌더 `COPY src/description`, `--packages-select`에 포함; meshes는 `RUN mkdir -p`로 빈 폴더만 생성). 서명 manifest·OCI archive·immutable registry digest 발행 전"
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
- `deploy/image/ 빌더`의 io-build 단계가 `description`을 복사·빌드한다. 단 `.dockerignore`가 `src/description/meshes/**`를 build context에서 제외하고, Dockerfile이 `RUN mkdir -p src/description/meshes`로 빈 폴더만 만든다 — meshes 자체는 device 이미지에 실리지 않는다.
- Gazebo는 `rosy_gz.urdf.xacro`를 쓴다. `left_wheel_joint`/`right_wheel_joint` 이름은 `bringup`과 맞춰야 한다.

## 다음 gate

1. 서명된 native ARM64 artifact 발행 후 Pi readback(ARTIFACT → DEVICE), deploy/core와 동일 체인.
2. 물리 Pinky Pro의 실제 직경·휠 slip·센서 외형을 실측해 simulation primitive와의 허용 오차를 닫는다.

## 현재 유효한 금지사항

- Gazebo 전용 플러그인/토픽을 `rosy_gz.urdf.xacro`에서 깨지 않는다.
- inertia helper는 `urdf/common/insert_inertia.urdf.xacro`에 유지한다.
- `left_wheel_joint`/`right_wheel_joint` 이름을 `bringup`과 어긋나게 바꾸지 않는다.
