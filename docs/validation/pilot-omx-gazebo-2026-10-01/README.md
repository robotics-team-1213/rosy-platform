# Pilot OMX-AI Gazebo 실행 검증 · 2026-10-01

## 범위

[D-390](../../adr/D-390-pilot-omx-simulation-practice-boundary.md)의 개발용 OMX-F follower Gazebo 경로를 Windows Docker Desktop의 Linux amd64 컨테이너에서 실행했다. Pilot HTTP 서버와 `RosArmCommandRuntime`은 같은 컨테이너의 단일 `ArmCommandOwner`를 사용했다. 실물 로봇, ARM64/Pi 이미지, 카메라, 학습 데이터 생성은 이 검증에 포함되지 않는다.

## 재현 정보

- 정본 vendor 개발 이미지: `rosy-omx-workstation:native-action-only-local`, 로컬 이미지 ID `sha256:b47034e436119cea97c2922a1b4af9bd6596975ac8acbb4cece3a19d2fe1e9f0`.
- Pilot 계층: `deploy/robot/omx/Dockerfile.pilot`, 로컬 이미지 ID `sha256:e94662607c72a7cea83c9449178099c4c9476afab0519275ce0da82a88f3da9a`.
- 컨테이너: bridge network, `127.0.0.1:8088`만 publish, Docker device grant `[]`, 소스 `/repo` read-only. `ROS_DOMAIN_ID=75`, `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST`.
- 일회용 pairing code는 컨테이너 내부 0600 파일로만 제공했다. API와 Docker stdout에 코드·token을 기록하지 않았다.
- 실행 명령은 [OMX 개발 README](../../../deploy/robot/omx/README.md)의 Pilot 절을 따른다. 자동 probe는 `python deploy/robot/omx/probe_pilot_sim_http.py rosy-omx-pilot-sim`.

## 관측 결과

| 검사 | 결과 |
|---|---|
| ROS graph | `arm_controller`와 `joint_state_broadcaster`가 `active`; `/clock`, `/joint_states` 관측. 조회한 topic 목록에 `/leader/joint_trajectory` 없음. |
| Pilot 대상 | `/api/v1/sim/omx/target`가 `kind:omx_sim`, `simulation:true`, `joint1..5`, `gripper_joint_1`, `camera:false` 반환. |
| 팔 조그 | `joint1` +0.02 rad, 0.4 s 요청 → `LOCAL_ACCEPTED` → ROS goal ID 관측 → `SUCCEEDED`; 관절 readback 0.0000→0.0185 rad. |
| 그리퍼 조그 | `gripper_joint_1` +0.02 rad, 0.4 s 요청 → ROS goal ID 관측 → `SUCCEEDED`; 종료 직후 readback −0.0003→0.0087 rad. 이동은 관측했지만 요청값과의 오차 약 0.011 rad는 남는다. |
| 명시적 취소 | 별도 1 s goal → `CANCEL_REQUESTED` → ROS `CANCEL_ACK` → terminal status 5와 `CANCELED` readback. 취소 ACK만으로 물리 정지를 주장하지 않는다. |
| 사전 실패 회차 | 빠른 joint-state sequence에 HTTP의 완전 일치 검사가 충돌해 409가 났고, 실제 제공한 sequence의 제한된 유효 창으로 수정했다. ROS Jazzy의 NumPy UUID 형식이 기존 변환기에서 거부돼 수락 불명과 취소가 발생했고, 형식 지원 테스트와 변환기 수정 후 실제 goal ID를 확인했다. 2 s watchdog에서는 느린 Gazebo 그리퍼 goal이 취소돼 시뮬레이션 전용 8 s watchdog으로 재검증했다. |

## 호스트 검증

- OMX 어댑터·계약, Pilot 드라이버·연결·라우트, surface registry: **201 passed, 3 skipped**.
- harness 계약과 네트워크 토폴로지: **80 passed**. `rosy_harness.py lint`는 오류 0건, 기존 `last_verified` 관련 경고 23건이다.
- 렌더링한 OMX Pilot 브라우저의 pairing→조그 1건과 Pinky 기존 브라우저 gate 1건 통과.
- `git diff --check` 통과. 호스트 테스트와 브라우저 테스트는 위 Gazebo 실행 결과를 대체하지 않는다.

## 판정과 남은 게이트

Pilot → 인증/조종권 → 단일 OMX owner → Gazebo action → 관절 readback의 **ROS-SIM 조작 경로는 확인**했다. `SUCCEEDED`는 action server 결과이고 그리퍼 목표 위치의 정밀 도달은 확인하지 못했다. `camera:false`인 현 구성에는 학습용 영상·녹화가 없고, lease 만료·브라우저 이탈·owner 재시작의 실제 Gazebo 회복 시험은 남아 있다. 따라서 D-390 전체 범위와 실물 OMX 운용은 계속 HOLD다.
