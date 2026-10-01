## D-390 Pilot의 OMX-AI 연습은 시뮬레이션 전용 장치 API를 거쳐 로컬 팔 명령 소유자에 연결한다

**Status:** Accepted (2026-10-01, 설계·실행 순서 결정). API·Pilot·Gazebo 통합 구현, ROS-SIM 수용, 실물 OMX 원격 조종, DEVICE/FIELD 수용은 포함하지 않는다.

## 배경과 확인한 차이

- D-323·D-366은 Pilot의 장치별 드라이버 확장점을 정했지만, 현행 `app.js`는 `pinky_core`만 등록하고 `connect.js`·`drive.js`는 그 종류를 직접 선택한다. `link.js`는 `/ws/state`와 `/api/v1/teleop`의 `{linear, angular}` 주행 명령을 한 상태 기계에 묶는다. `client.js`의 인증·capability 경로와 `vision.js`의 전방 카메라 경로도 Pinky CORE의 같은 origin을 전제한다. 따라서 드라이버 파일 하나만 추가해서 OMX 팔을 조종할 수 없다.
- ROBOTIS의 고정 OMX-AI 팔로워 Gazebo 그래프는 관절 액션·상태·취소를 보인 적이 있다([두 인스턴스 검증](../validation/omx-two-instance-ros-sim-2026-09-26/README.md)). 이는 Pilot 입력, 브라우저 인증, 영상, 명령 상실 시 정지, 실제 작업대 실행을 검증한 결과가 아니다.
- `omx_adapter.RosArmCommandRuntime`와 카메라 프레임 게이트는 로컬 소프트웨어 경계다. 현행 `ActionApi`의 UDS 작업은 Fleet의 의미적 Action·StopLocal용이며 브라우저의 관절 조그 API가 아니다. D-336의 동일 호스트 Fleet IPC를 Pilot에 그대로 개방할 수 없다. OMX 프로필은 `enabled: false`다.
- “학습영상”에는 조작법을 보여주는 교육 콘텐츠와 조작 시연을 기록한 데이터라는 두 요구가 있다. 영상만 저장해서 AI 학습용 시연 데이터라고 부를 수는 없다.

## 결정

1. 첫 수용 목표는 **OMX-AI 고정 작업대의 Gazebo 연습**이다. OMX 시뮬레이션 호스트의 별도 HTTP 장치 API가 Pilot 정적 자산을 같은 origin에서 제공한다. Pilot은 그 origin의 장치 식별·`simulation` 모드·capability를 읽어 OMX 화면을 연다. Pinky CORE를 OMX 명령·영상 프록시로 쓰지 않으며, Fleet도 브라우저 조그 중계자가 되지 않는다. 시뮬레이터 origin의 인증·단일 운전석은 Pinky 토큰을 신뢰하거나 복사하지 않고 별도 계약으로 정의한다.
2. Pilot 공통부에서는 연결/인증/운전석과 명령 전송을 분리한다. Pinky 드라이버의 주행 `{linear, angular}`·모드·정지 계약은 유지하고, OMX 드라이버와 팔 화면은 명시된 arm capability가 있을 때만 나타낸다. OMX 입력은 관절 조그·그리퍼 개폐·취소의 **시간·거리·속도 제한된 목표**다. `/api/v1/teleop`에 팔 명령을 끼워 넣거나 주행 스틱의 100 ms 전송 루프를 팔에 재사용하지 않는다. 실제 경로·메시지·오류코드·버전은 구현 전에 API Reference와 typed schema에 함께 확정한다(D-18).
3. 시뮬레이션 API는 요청 수락, ROS goal 수락, 동작 중, 완료, 취소 요청, 최종 취소를 별도로 표시한다(D-386). 관절 상태가 오래되었거나 컨트롤러가 비활성, 명령 owner가 불명확, 운전석이 만료된 경우 새 목표를 거절하고 HOLD한다. 브라우저 탭 종료·연결 손실은 해당 목표의 취소를 요청하고 재진입 전 readback을 요구한다. 브라우저의 요청 성공이나 취소 응답만으로 팔 정지를 단정하지 않는다. Gazebo 액션으로 가는 최종 writer는 workcell별 로컬 owner 하나다(D-282·D-369).
4. 카메라는 Gazebo 작업대의 source identity와 `/clock`을 포함한 시뮬레이션 시각으로부터 시작한다. 최신 프레임과 상태를 같은 origin의 인증 경로로 제공하고 프레임 나이·결손을 Pilot에 보인다. 조작 연습 기록은 원본 영상 또는 프레임과 관절 상태·명령·그리퍼 상태·goal ID·시각·시뮬레이터/모델/보정 버전을 함께 묶는다. 불완전한 묶음은 학습용 데이터로 표시하지 않는다. 조작법 교육 영상은 별도 정적 콘텐츠로 제공할 수 있다.
5. 시뮬레이션과 실물의 identity, capability, 배포 프로필을 분리한다. 이 ADR은 실물 프로필 `enabled: false`, D-336의 Fleet UDS, D-273의 실물 카메라·팔 수용 순서, D-299의 LeRobot 단일 시리얼 owner 경계를 바꾸지 않는다. 실물 Pilot 조종은 실제 장치 인증·정지·복구·카메라·시간 지연을 계측하고 별도 결정한 뒤에만 연다.

## 검토한 대안

| 대안 | 판단 |
|---|---|
| Pinky CORE가 OMX를 프록시 | CORE의 로봇별 권한·`cmd_vel` 소유와 OMX 로컬 팔 owner가 섞이고, Pinky가 없는 고정 작업대를 설명하지 못하므로 채택하지 않는다. |
| 브라우저가 ROS/DDS나 Fleet UDS에 직접 연결 | 브라우저 인증·명령 중재·최종 writer 경계를 우회하므로 채택하지 않는다. |
| 시뮬레이션 호스트의 장치 API와 기존 로컬 owner | Pilot의 같은 origin 모델과 OMX 단일 writer를 유지하며 실물 활성화와 분리할 수 있어 채택한다. |

## 수용 기준과 증거 경계

- **SOURCE:** 장치 종류 선택, capability 거부, lease 단일성·만료, 목표 제한, 중복/늦은 요청, 취소 상태 구분, 카메라 신선도, 기록 manifest 계약을 시험한다. Pinky 기존 브라우저 경로 회귀를 함께 본다.
- **ROS-SIM:** 고정된 ROBOTIS 버전의 Gazebo에서 Pilot 입력 → 로컬 owner → ROS 액션 → 관절·그리퍼 readback을 관찰한다. goal 거절, 늦은 수락, 브라우저 이탈, lease 만료, 카메라 결손, owner 재시작 후 HOLD를 시험하고 `/clock`·한 writer를 확인한다. 화면 영상의 fps·지연도 측정한다.
- **ARTIFACT:** OMX 시뮬레이션 호스트의 설치 자산·버전·재현 가능한 이미지 또는 패키지 식별자를 기록한다.
- **DEVICE/FIELD:** 이 결정으로 승격하지 않는다. 물리 정지·실물 팔·카메라·보정·복구 증거가 없는 동안 실물 운전 capability는 닫힌다.

**관련 결정:** [D-18](D-18-rosy-core.md), [D-273](D-273-omx-camera-stream-and-arm-control-order.md), [D-282](D-282-per-hardware-ros-ownership-and-control-boundaries.md), [D-299](D-299-omx-lerobot-development-and-command-ownership.md), [D-323](D-323-rosy-pilot-teleop-app.md), [D-336](D-336-fleet-omx-local-ipc-boundary.md), [D-366](D-366-pilot-multidevice-roadmap.md), [D-369](D-369-control-authority-and-stop-evidence.md), [D-386](D-386-omx-async-goal-acceptance-and-phase-state.md).

## 2026-10-01 부록: SIM 시연 원본과 LeRobot 오프라인 export

사용자가 시연 기록·LeRobot 데이터셋 연계를 우선했다. D-390의 단일 소유자와 SIM 전용 경계를 유지하며, 영상/과거 JointState/ROS 수락 UUID가 있는 절대 목표를 source stamp로 묶어 기록한다. 정확한 ROS 이름과 rad, gripper rad를 omx_sim_ros로 보존하고 native omx_follower 단위로 자동 변환하지 않는다. LeRobot 0.4.4를 별도 오프라인 환경에 고정하고 finalize 후 실제 reader 재독출을 요구한다. 불완전 기록은 export하지 않는다. 명령 성공과 운용자가 지정한 과제 결과를 구분한다. 저장 위치는 서버 설정만 받으며 원본/해시를 보존한다. 학습된 정책 실행·Hub 게시·실물 profile 활성화는 별도 결정이다.

근거와 실행 순서: [시연 설계·계획](../plans/2026-10-01-omx-demonstration-lerobot-design.md), [공식 예제 조사](../plans/2026-10-01-omx-lerobot-examples-research.md).
