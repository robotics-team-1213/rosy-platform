## 2026-09-22 · uncommitted · chore: update ARTIFACT blocker to Native Image Builder (D-164)

- 변경: deploy/robot/Dockerfile 의존성을 Native Pi Image Builder로 일괄 변경
- 증거: D-161, D-164
- gate 변화: 없음


# description logs

추가만 한다. 형식: [module harness 설계](../../docs/plans/2026-09-15-module-harness-design.md) §4.2.
2026-09-15 이전 이력은 `git log -- src/description`를 본다.

## 2026-09-15 · uncommitted · docs(harness): start the description harness record
- 변경: `progress.md`, `logs.md` 추가
- 증거: `python3 -m pytest test/test_robot_runtime.py::test_runtime_builds_distinct_targets_from_shared_dockerfile -q` 1 passed; LOCAL은 미실행 — `src/description`에 `test/` 디렉터리가 없어 host-runnable 대상이 없음 (2026-09-15 Windows)
- gate 변화: 없음(신규 기록). SOURCE GO, LOCAL HOLD, ROS-SIM N/A, ARTIFACT/DEVICE HOLD(io 이미지에 포함, Device 계획과 동일 blocker), FIELD N/A
- 결정: D-61 Proposed
- 교훈: 없음

## 2026-09-16 · uncommitted · docs(harness): hold unrendered description in ROS-SIM
- 변경: 리뷰 반영. ROS-SIM을 HOLD로, `last_verified.commit`을 `uncommitted`로(SOURCE 시험이 미커밋 WIP가 있는 `deploy/robot/Dockerfile`을 읽음)
- 증거: `python -m pytest test/test_robot_runtime.py::test_runtime_builds_distinct_targets_from_shared_dockerfile -q` 1 passed (2026-09-16 재실행). ROS 렌더 자체는 미실행
- gate 변화: ROS-SIM N/A→HOLD (URDF는 robot_state_publisher·Gazebo가 소비하므로 적용 대상이지만 미검증)
- 결정: 없음
- 교훈: 없음

## 2026-09-16 · uncommitted · docs(harness): stop counting the meshes dockerignore check as source evidence
- 변경: 2차 리뷰 반영. SOURCE를 HOLD로(인용 시험은 `.dockerignore` meshes 제외만 확인하고 URDF·io-build 포함을 단언하지 않음), FIELD를 PARKED로(io 이미지에 실리는 패키지)
- 증거: 미실행 — 기록 정정만. 인용 시험 내용은 `test/test_robot_runtime.py`에서 직접 확인
- gate 변화: SOURCE GO→HOLD, FIELD N/A→PARKED
- 결정: 없음
- 교훈: 없음

## 2026-09-21 · uncommitted · fix(sim): use stable primitive drive collisions

- 변경: 시뮬레이션 바퀴 충돌체를 축 방향 cylinder로 바꾸고 종방향 마찰과 횡방향 scrub을 분리했다. DART가 지원하지 못한 mesh collision은 sim 렌더에서 primitive로 유지하고, 물리 모델의 상세 mesh는 그대로 보존했다. SLAM용 odom은 Gazebo model pose, wheel odom은 진단 토픽으로 분리했다.
- 증거: ROS Jazzy 컨테이너에서 xacro 렌더 및 관련 description/gz_sim 시험 통과. `final_22` 실제 주행 52/52, sampled collision overlap `false`, 최소 본체 여유 `0.021789 m`.
- gate 변화: ROS-SIM HOLD→GO(단일 로봇 exact-map collision/odom 범위). ARTIFACT/DEVICE/FIELD는 변동 없음.
- 결정: 시뮬레이션 정답 odom과 바퀴 적분 odom을 한 토픽에 경쟁시키지 않는다.
- 교훈: 구형 mesh collision과 과도한 등방 마찰은 로드 성공 여부뿐 아니라 좁은 공간 회전과 SLAM 궤적까지 왜곡한다.
