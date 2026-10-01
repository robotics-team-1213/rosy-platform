## D-404 OMX 셋업·티칭 API는 시뮬레이션부터 D-390 seat와 제한 jog에 읽기 전용 TCP(FK) 조회를 더한다

**Status:** Proposed (2026-10-01, 경계·계약 결정; Rosy Cell 셋업 중계와 D-390 클라이언트 확장은 사용자 승인 2026-10-01). 시뮬레이션 장치 API(`/api/v1/sim/omx`)만 다룬다. 실물 OMX 장치·티칭 API, 리더 팔 티칭, 손으로 끌어 가르치기, Cartesian jog, DEVICE/FIELD 수용은 포함하지 않는다. 경로·필드·오류코드는 D-18에 따라 C5 구현 변경에서 API Reference·typed schema와 함께 확정한다.

## 배경

- **티칭 경로가 아직 없다.** D-399(Proposed) §5와 D-401(Proposed) §4는 팔 셋업·티칭을 장치 곁에서 하는 경로가 OMX 장치 API를 요구한다고 적고, 그 결정을 별도 ADR로 넘겼다. D-282(Proposed) §5는 OMX 원격 작업 API를 별도 계약 승인 전까지 제공하지 않는다. D-390(Accepted)은 시뮬레이션 전용 장치 API만 열었다.
- **현행 `pilot_sim_api.py`(D-390 구현).**
  - 인증: 운영자가 준 일회용 pairing code(8자 이상, 600 s 안에 1회)로 bearer token(1 h)을 발급한다. 지금은 프로세스 하나당 code 하나뿐이다.
  - 운전석: seat 하나, TTL 10 s, 갱신 가능하다. 반납하거나 만료되면 진행 중 목표를 취소한다.
  - jog: `OmxSimJog`. 관절 하나, `|delta_rad| ≤ 0.05`, `duration_s` 0.1–1.0, 만료 ≤ 6 s, `state_sequence`.
  - 명령은 모두 로컬 owner(표지 `pilot_sim`)를 거친다. `/state`는 관절 상태와 owner 상태를 읽는다.
  - TCP 포즈를 읽는 경로는 없다.
- **D-401 §2.** `cell.yaml`은 티칭한 원시 점(원점, x축 점, +y쪽 점)과 스테이션 포즈를 보관한다. §3에 따라 장치는 자신이 검증받은 셀과 해시가 다른 Job을 거절해야 한다. 장치가 "검증받은 셀"을 아는 방법은 아직 정의되지 않았다.

## 결정

1. **범위는 시뮬레이션이다.**
   - D-390의 시뮬레이션 identity(`simulation: true`)를 가진 인스턴스에만 적용한다.
   - 실물 OMX 장치 API는 계속 닫혀 있다. 근거는 D-282 §5, D-390 §5, D-336 §5다. 실물 티칭을 열려면 물리 정지, 인증, 지연을 계측하고 별도 ADR을 써야 한다.
2. **인증은 D-390 pairing이다.**
   - Rosy Cell 서버는 시뮬레이터 API의 클라이언트로 따로 pairing한다. 운영자가 시뮬레이터 호스트에서 발급한 일회용 code를 Rosy Cell 마법사에 입력한다.
   - token은 Rosy Cell 서버 메모리에만 둔다. 브라우저로 보내지 않고, URL·로그에 남기지 않는다(D-269 §2, Proposed).
   - Pilot과 Rosy Cell이 따로 pairing할 수 있도록, 시뮬레이터는 운영자 동작이 있을 때마다 클라이언트별 일회용 code를 새로 발급한다. 이는 현행 "프로세스당 code 하나"를 바꾸는 구현 항목이다. 공유 고정 비밀번호는 두지 않는다.
   - Rosy Cell 사용자는 Rosy Cell 자신의 운영자 로그인으로 인증한다. 중계는 로그인한 운영자 요청에만 한다.
3. **동작은 기존 seat와 제한 jog뿐이다.**
   - 쓰는 경로: seat 획득·갱신·반납, `POST /goals`(관절 jog, 그리퍼 관절 포함), 취소. Rosy Cell 화면의 누름 유지 입력을 Rosy Cell 서버가 같은 `OmxSimJog` 그대로 중계한다.
   - **seat 갱신에는 브라우저 생존 신호가 필요하다(D-390 §3).**
     - Rosy Cell 화면은 보이는 동안 1 s 간격으로 생존 신호를 보낸다.
     - Rosy Cell 서버는 신호를 받은 동안에만 `PUT seat`로 갱신한다. 신호가 두 번 연속 빠지거나 탭이 숨겨지면 즉시 `DELETE seat`를 보내 반납한다. 반납하면 진행 중 목표가 취소된다.
     - 생존 신호와 무관하게 갱신을 계속하는 것은 금지한다.
   - 그래도 중계가 끊기면 최대 jog 한 번(≤ 0.05 rad, ≤ 1 s)이 끝나고 seat가 10 s 안에 만료된다. 만료 때 진행 중 목표는 취소된다.
   - v1은 다음을 열지 않는다: 포즈 goto, Cartesian 이동, 궤적 업로드. 모든 jog는 같은 owner와 관절 한계를 거친다.
   - D-390 §1이 금지한 중계자는 Fleet과 Pinky CORE다. Rosy Cell 마법사는 D-399 §5의 "사람용 제품 클라이언트"로 장치 API를 쓴다. 다만 이 경로로 Job Step을 실행하지 않는다.
4. **읽기 전용 TCP 조회 `GET {PREFIX}/tcp`를 추가한다.**
   - bearer token은 필요하고 seat는 필요 없다.
   - 응답 필드:
     - `instance_id`, `state_sequence`, `joint_age_ms`, 사용한 관절 값
     - `frame: robot_base`, TCP `x, y, z`, `yaw`
     - 수직하향과의 각도 차 `tool_down_error_rad`
     - `kinematics_revision`
   - FK는 D-402 계획기와 같은 모듈과 같은 고정 URDF 값을 쓴다. 그래서 티칭한 점과 계획 입력이 한 기하를 공유한다.
   - 관절 상태가 없거나 owner 상한보다 오래되었으면 409를 낸다. 캐시 값은 돌려주지 않는다.
5. **Rosy Cell 마법사는 팔로워 FK를 점으로 저장한다.**
   - 기록 필드: `x, y, z, yaw`, `tool_down_error_rad`, `state_sequence`, `kinematics_revision`, `instance_id`, 티칭 시각.
   - 프레임 3점에는 xyz만 쓴다. 스테이션·공통 포즈는 `tool_down_error_rad`가 셀 설정 임계값 이하일 때만 받는다. 임계값은 코드 기본값이 아니라 설정에서 온다.
   - 셀에는 수직하향 `home` 포즈가 반드시 있어야 한다. 모든 transfer가 home에서 시작한다(D-402 §6).
   - **셀 schema를 `rosy_cell.cell/2`로 올린다(C5 작업).** `/2`는 `kinematics_revision`과 필수 `home`을 담는다. 두 값은 셀 해시에 들어가므로, URDF가 바뀌면 이전 셀과 그 셀로 만든 Job이 모두 해시 불일치로 무효가 된다(D-401 §3). 로더는 `/1`을 실행용으로 받지 않는다.
6. **장치가 셀을 수락한다.** D-403 §9의 해시 검사가 이 값을 쓴다.
   - seat를 가진 클라이언트가 `PUT {PREFIX}/cell`로 정규화한 `cell` 문서를 보낸다.
   - 장치는 D-401 §3 규칙(정규화 JSON의 sha256)으로 해시를 다시 계산한다. `kinematics_revision`이 자기 값과 같은지 확인한 뒤 owner 로컬 journal에 "수락한 셀"로 기록한다. `GET {PREFIX}/cell`로 다시 읽을 수 있다.
   - 미해결 Action이 있으면 교체를 거절한다. 교체한 뒤 옛 셀 해시로 발급된 grant는 셀 해시 검사(D-403 §9)에서 거절된다.
   - 수락한 셀은 D-403 §8의 단일 owner 프로세스 상태에 둔다. HTTP API와 UDS가 같은 값을 본다.
7. **Fleet 경로와 섞지 않는다.** seat가 잡혀 있는 동안 `CELL_TRANSFER`를 거절한다. `CELL_TRANSFER`가 끝나지 않은 동안에는 seat 획득을 거절한다(D-403 §10, D-330 §1).

## 검토한 대안

| 대안 | 판단 |
|---|---|
| 브라우저가 시뮬레이터 origin을 교차 출처로 직접 호출 | D-390의 같은 origin 모델에 CORS를 열어야 하고, token이 브라우저에 남는다. 채택하지 않는다. |
| Pilot에서 jog하고 Rosy Cell은 TCP만 읽음 | 경계는 단순하지만 화면 두 개를 오가야 하고, 저장할 때 seat 소유자가 다르다. 운영자가 원하면 같은 API로 할 수 있으며, 기본 경로로는 두지 않는다. |
| Cartesian jog(D-402 IK 사용) | 티칭이 쉬워지지만 IK 실패 처리와 속도 제한 계약이 더 필요하다. 후속으로 미룬다. |
| 실물에도 같은 API를 연다 | 물리 정지, 인증, 지연 증거가 없다(D-282 §5, D-390 §5). 채택하지 않는다. |

## 결과

- 시뮬레이션에서 셋업 마법사가 jog로 팔을 움직이고, FK 포즈를 저장하고, 셀을 장치에 수락시키는 데까지 한 경로로 이어진다.
- 실물 티칭과 실물 장치 API는 계속 닫혀 있다.

## 수용 기준과 증거 경계

- **SOURCE:**
  - 클라이언트별 pairing과 token 비노출
  - seat 만료 시 취소, 생존 신호가 없으면 갱신하지 않음
  - `cell/2` 로더(`home`, `kinematics_revision` 필수)
  - jog 한계
  - TCP 조회의 stale 거절과 FK 일치(D-402 시험 고정값)
  - 셀 수락의 해시 재계산, 미해결 Action 중 거절, seat와 `CELL_TRANSFER` 상호 배제
- **ROS-SIM:** C5/C6에서 고정 이미지 Gazebo로 프레임 3점과 스테이션을 티칭한다. FK 좌표와 Gazebo 모델 좌표의 오차를 측정한다.
- **DEVICE / FIELD:** 이 결정으로 승격하지 않는다.

**관련 결정:** [D-18](D-18-rosy-core.md), [D-269](D-269-device-server-contracts-and-ros-boundary.md), [D-282](D-282-per-hardware-ros-ownership-and-control-boundaries.md), [D-330](D-330-fleet-action-admission-stop-and-recovery.md), [D-336](D-336-fleet-omx-local-ipc-boundary.md), [D-390](D-390-pilot-omx-simulation-practice-boundary.md), [D-399](D-399-rosy-layered-architecture-site-plane-device-pipeline.md), [D-401](D-401-rosy-cell-application.md), [D-402](D-402-omx-motion-planner-v1-analytic-top-down-ik.md), [D-403](D-403-fleet-cell-job-route-cell-transfer.md)
