# Rosy Pilot OMX-AI Gazebo Practice Implementation Plan

**진행 상태 (2026-10-01):** 시뮬레이션 전용 API·조종권·단일 owner 연결·Pilot 관절/그리퍼 화면과 브라우저 계약 시험을 구현했다. [Gazebo 실행 검증](../validation/pilot-omx-gazebo-2026-10-01/README.md)에서 관절·그리퍼 goal과 취소 readback을 관측했다. 그리퍼 정밀 도달, 카메라, 시연 기록, lease 만료·브라우저 이탈·재시작의 실제 회복 시험은 남았다. 현재 경로는 `/api/v1/sim/omx`, schema는 `core_common.protocol.omx_sim`이다. 아래 목록은 최초 범위와 남은 게이트를 보존한다.

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rosy Pilot에서 OMX-AI 고정 작업대를 선택해 Gazebo 팔·그리퍼를 제한된 조작으로 연습하고, 카메라·관절 readback과 시연 기록을 확인한다.

**Architecture:** [D-390](../adr/D-390-pilot-omx-simulation-practice-boundary.md). OMX 시뮬레이션 호스트가 Pilot 자산과 인증된 장치 API를 같은 origin에서 제공한다. HTTP 경계는 workcell별 단일 `RosArmCommandRuntime`에 명령을 전달하고 ROS goal 상태를 readback한다. Pinky CORE의 주행 계약과 OMX 실물 프로필은 그대로 둔다.

**Tech Stack:** ROS 2 Jazzy, Gazebo Harmonic, 고정 ROBOTIS `open_manipulator` source lock, `ros2_control`/`FollowJointTrajectory`, Python/FastAPI, vanilla ES modules, pytest/Node/Playwright. Windows에서는 ROS-free 계약·브라우저 시험을 실행하고 Gazebo 실행은 Linux amd64 워크스테이션에서 한다.

---

## 현재 확인한 구현 차이

| 경계 | 현행 | 이번 계획의 변경 |
|---|---|---|
| 대상 선택 | `app.js`가 `pinky_core`만 등록, `connect.js`·`drive.js`도 직접 참조 | origin의 identity/capability를 읽어 `pinky_core` 또는 `omx_sim`을 선택 |
| 명령 세션 | `link.js`가 `/ws/state`와 `/api/v1/teleop`의 속도 명령에 결합 | 연결·운전석 상태를 공통으로, 명령 codec/transport/취소는 드라이버별로 분리 |
| OMX 제어 | `RosArmCommandRuntime`는 로컬 ROS action client; Fleet UDS는 의미적 Action 전용 | 시뮬레이션 전용 인증 HTTP API를 로컬 owner에 붙임. Fleet UDS는 확장하지 않음 |
| 영상 | Pilot `vision.js`는 Pinky 전방 프레임 경로, OMX는 `Image`/`CameraInfo` 페어 게이트만 있음 | Gazebo 작업대 카메라 → fresh frame → 인증 미리보기. 영상 부재와 지연 표시 |
| 기록 | Pilot의 브라우저 카메라 클립은 OMX 관절·명령 증거와 결속되지 않음 | 로컬 세션 manifest에 시간·goal·상태·영상 출처를 함께 기록 |

## 경계와 선행 조건

- 이 계획의 실행 프로필은 `omx_sim`이다. `src/products/omx/profile/config/omx.disabled.yaml`을 활성화하지 않는다. 시뮬레이터에는 serial/camera 실장치 grant가 없어야 한다.
- 본 문서에 적은 `/api/v1/sim/omx/...` 경로는 **구현할 후보 계약**이며 현재 제공되는 API가 아니다. Task 1에서 API Reference와 `core_common.protocol.schemas`를 같은 변경으로 확정한다. Pinky의 `/api/v1`을 뜻하지 않는다.
- D-386의 비동기 ROS goal 수락/신선한 상태 결속이 미완료면 명령 경로는 HOLD한다. `ActionApi`의 Fleet grant를 브라우저 토큰으로 바꾸거나 우회하지 않는다.
- 시뮬레이션 카메라의 `CameraInfo`와 source identity는 명시된 sim 전용 보정 revision으로만 수용한다. 실물 보정으로 승격하지 않는다.
- 학습용 기록은 이 계획에서는 **시연 원본**이다. LeRobot 포맷 변환·모델 학습·정책 실행은 포함하지 않는다. 교육용 튜토리얼 영상은 별도 정적 콘텐츠 슬롯만 마련한다.

## Task 1 — 시뮬레이션 API·상태 계약 고정

**Files:** Modify `docs/reference/ROSY API & Protocol Reference.md`, `src/contracts/foundation/core_common/protocol/omx_sim.py`; create `src/contracts/foundation/test/test_omx_sim_pilot_contract.py`(실제 foundation test 위치를 확인해 그 디렉터리에 배치).

1. 기존 API 버전·envelope·오류 규칙과 `D-18`을 읽고, sim 전용 경로를 정의한다: target/capability read, code pairing·whoami, 단일 운전석 획득/갱신/반납, arm goal 제출/조회/취소, state, camera status/frame, record start/stop/manifest. 경로 접두사는 `/api/v1/sim/omx`로 고정한다.
2. typed schema와 계약 테스트를 먼저 작성한다. 모든 요청은 `instance_id`, session/seat identity, monotonically increasing request id, 유효기간을 검증한다. 명령은 joint 이름·방향/목표·최대 이동·속도·시간 제한을 갖고, gripper는 별도 허용 범위를 갖는다. 응답 상태는 `LOCAL_ACCEPTED`, `ROS_ACCEPTED`, `RUNNING`, `SUCCEEDED`, `REJECTED`, `CANCEL_REQUESTED`, `CANCELED`, `UNKNOWN_HOLD`를 혼동하지 않는다. 버전·중복·늦은 요청과 권한 거부를 테스트한다.
3. 시험을 실패시킨 뒤 최소 schema·reference를 함께 추가하고 다시 통과시킨다. API Reference의 MINOR/변경 이력을 저장소 규칙대로 갱신한다. `python -B -X utf8 -m pytest src/contracts/foundation/test/test_omx_sim_pilot_contract.py -q -p no:cacheprovider`를 기준으로 한다.

## Task 2 — 시뮬레이션 호스트의 HTTP/인증·운전석

**Files:** Create `src/products/omx/adapter/omx_adapter/pilot_sim_api.py`, `pilot_sim_session.py`, `src/products/omx/adapter/test/test_pilot_sim_api.py`; modify `src/products/omx/adapter/setup.py`, `package.xml` as required for the host entrypoint. Reuse the installed `src/hmi/pilot` asset package through a read-only static mount.

1. FastAPI `TestClient`로 `/pilot`과 허용된 정적 자산 제공, 미등록 자산 404, 익명 명령 401, viewer 명령 403, 다른 운전석 409, 만료 lease 재사용 409, 잘못된 instance 404/409, 중복 request id idempotent readback, 달라진 payload의 같은 id 충돌을 먼저 시험한다. 브라우저 토큰은 헤더로만 받는다.
2. 시뮬레이션 호스트가 발급한 짧은 수명의 일회용 pairing code와 회수 가능한 bearer token을 구현한다. pairing code는 호스트의 로컬 화면/CLI로만 출력하고 소스·URL·로그에 쓰지 않는다. 한 workcell의 운전석 하나를 서버가 소유하며, lease 만료·명시적 반납·서버 재시작 시 새 명령을 닫는다.
3. `pilot_sim_api`는 인증·schema·seat를 확인하고 로컬 runtime facade를 호출한다. ROS 객체나 Fleet UDS를 HTTP 핸들러가 직접 조작하지 않는다. 시험 통과 후 `python -B -X utf8 -m pytest src/products/omx/adapter/test/test_pilot_sim_api.py -q -p no:cacheprovider`를 실행한다.

## Task 3 — OMX 로컬 명령 owner와 Gazebo 결속

**Files:** Create `src/products/omx/adapter/omx_adapter/pilot_sim_runtime.py`, `src/products/omx/adapter/test/test_pilot_sim_runtime.py`; modify `deploy/robot/omx/probe_vendor_owner_sim.sh` 또는 별도 `deploy/robot/omx/probe_pilot_sim.sh`, 필요 시 고정 vendor patch/launch; modify `src/products/omx/adapter/omx_adapter/ros_runtime.py` only for a minimal callback/receipt seam.

1. fake action client로 `LOCAL_ACCEPTED`와 ROS goal acceptance가 분리됨을 시험한다. goal 거절·late accept·취소 ACK 뒤 실제 terminal result·owner restart·stale joint state·controller inactive·새로운 명령의 직전 state sequence 재사용을 모두 HOLD로 검증한다(D-386). 손을 뗄 때에는 제한된 목표를 취소하고 실제 정지 readback 전까지 다음 목표를 거절한다.
2. 브라우저 `jog` 요청을 최신 관절 상태 기준의 짧은, 제한된 trajectory goal로 변환한다. 시뮬레이션 프로필의 관절/그리퍼 경계는 고정 vendor URDF와 controller 설정에서 명시적으로 가져와 검증한다. 동시에 leader direct topic·MoveIt·Pilot이 writer가 되지 않도록 owner admission과 graph 점검을 둔다.
3. Linux amd64의 고정 Gazebo 이미지에서 서버 controller `active` 확인 후 no-op → 관절 이동 → gripper → 정확한 goal cancel/readback을 실행한다. `ROS_DOMAIN_ID`와 `/clock`, workcell namespace, 한 writer, 종료 시 남은 goal 0을 기록한다. Windows host 시험만으로 ROS-SIM GO를 주지 않는다.

## Task 4 — Pilot 공통부에서 Pinky 전용 결합 분리

**Files:** Modify `src/hmi/pilot/app.js`, `screens/connect.js`, `link.js`, `client.js`, `drivers/registry.js`; add/modify `src/hmi/pilot/test/test_drivers.py`, `test_link.py`, `test_pilot_browser.py`.

1. 가짜 Pinky/OMX origin 시험을 먼저 추가한다. identity/capability가 없거나 `sim=false`, arm capability가 없으면 OMX 조종 화면에 진입할 수 없어야 한다. Pinky는 현행 `/api/v1/teleop`·hold-to-drive·카메라 경로를 그대로 써야 한다.
2. `connect.js`의 `DRIVER_KIND`와 `drive.js`의 직접 `pinky_core` 참조를 화면 라우팅에서 제거한다. `link.js`의 socket/backoff/hidden/lease 역할과 `{linear, angular}` 전송 루프를 분리한다. Pinky adapter가 기존 전송 루프를 호출하고 OMX adapter는 goal·cancel/status 경로를 쓴다. 한 탭에서 Pinky/OMX origin을 섞거나 이전 token을 재사용하지 않도록 origin별 sessionStorage 키·token 회수를 검증한다.
3. 정적 자산 등록이 깨지지 않도록 `src/runtime/api_web/core_api_web/api/app.py`, `src/hmi/pilot/CMakeLists.txt`, 서비스 워커 allowlist/cache 버전, `src/runtime/api_web/test/test_pilot_route.py`를 필요한 범위에서 갱신한다. `src/hmi/pilot/test`와 route 시험을 실행한다.

## Task 5 — OMX 팔 화면과 입력

**Files:** Create `src/hmi/pilot/drivers/omx_sim.js`, `screens/arm.js`, `screens/arm-view.js`, `test/test_omx_sim.py`; modify `src/hmi/pilot/index.html`, `styles.css`, `app.js`, `CMakeLists.txt`, `src/runtime/api_web/core_api_web/api/app.py` asset allowlist.

1. 관절별 선택, 한 번에 한 축, 명시적 누름/놓음, 그리퍼 열기/닫기, 취소·HOLD 상태, 관절 readback·목표/실제 차이, 카메라 지연 표시를 가짜 API로 브라우저 시험한다. 여러 포인터, 탭 숨김, 네트워크 단절, 401/403/409/5xx, stale state에서 새 goal이 발행되지 않아야 한다.
2. ARM capability의 실제 joint 목록·한도만 렌더링한다. 명령 횟수를 브라우저 100 ms 타이머에 종속하지 않고 goal 진행/종료와 lease로 제한한다. 소프트웨어 취소와 물리 정지 문구를 구분한다.
3. 태블릿 가로 화면의 영상·상태·조작부를 확인하고 키보드/게임패드 입력은 명시적으로 매핑된 조그만 허용한다. 동작 중 컨트롤이 영상을 가리지 않게 한다.

## Task 6 — Gazebo 작업대 카메라와 연습 기록

**Files:** Add Gazebo workcell camera world/launch under `src/sim/gz_sim/` or locked OMX sim overlay; create `src/products/omx/adapter/omx_adapter/pilot_sim_camera.py`, `pilot_sim_recording.py` and focused tests; modify `src/hmi/pilot/vision.js` to accept driver-provided status/frame paths or add a small OMX preview adapter.

1. 카메라 `Image`/`CameraInfo` 페어, `/clock`, 프레임 순서·나이, source identity, sim calibration revision, 잘못된/결손 프레임 거부를 시험한다. `RosCameraStreamRuntime`의 검증 결과만 API에 노출한다. 영상 전송은 첫 단계에서 인증된 최신 JPEG pull로 시작하고 실제 fps/지연을 측정한다.
2. record start/stop과 session manifest를 구현한다. 각 frame/goal/state/gripper event에 같은 sim clock·wall receipt, model/source revision, goal ID를 기록하고, 프레임 누락·시계 역행·상태 누락은 `incomplete`로 표시한다. 세션 파일·스크래치는 X: 또는 Linux 호스트의 저장소 밖 작업 디렉터리로 보낸다. 클립만 저장한 것을 AI 학습 완료로 표시하지 않는다.
3. 교육용 튜토리얼 영상은 동작 API와 분리된 정적 콘텐츠 manifest로만 등록한다. 실제 콘텐츠가 없으면 화면은 빈 상태를 명확히 보여 준다.

## Task 7 — 종단 검증과 배포 경계

**Files:** Create `docs/validation/pilot-omx-gazebo-<실행일>/README.md` only after actual run; update `src/hmi/pilot/{logs.md,progress.md}`, `src/products/omx/adapter/{logs.md,progress.md}`, `src/sim/gz_sim/{logs.md,progress.md}` when their gates truly move; update `deploy/robot/omx/README.md` for reproducible sim launch.

1. Windows/host: 계약, OMX adapter, Pilot, API route, architecture 시험을 실행한다. 실패·skip을 따로 기록한다. `python tools/harness/rosy_harness.py lint`를 실행한다.
2. Linux amd64: locked image/commit, Gazebo process, `/clock`, controller active, API identity/capability, Pilot 조그·그리퍼, goal accept/result, 취소, 브라우저 이탈, lease 만료, 카메라 결손, owner 재시작을 화면과 ROS readback 양쪽에서 확인한다. 관측한 fps·명령/영상 지연을 숫자로 남긴다.
3. 설치 자산 해시·이미지 ID를 기록하고 `Pilot SOURCE`, `ROS-SIM`, `ARTIFACT`, `DEVICE`, `FIELD`를 각각 판정한다. 실물 장치·물리 정지 증거가 없으면 DEVICE/FIELD는 HOLD/PARKED다. 검증 결과에 맞춰서만 `progress.md`를 갱신하고 harness `generate`를 실행한다.

## 완료 조건

Pilot에서 `omx_sim`을 선택해 제한된 관절·그리퍼 명령을 낼 수 있고, ROS goal의 수락과 실제 완료를 구분해 표시하며, 명령 이탈·취소·재시작에 HOLD/readback이 작동하고, 카메라·동작 기록의 출처가 검증된다. 같은 테스트에서 Pinky 주행이 회귀하지 않아야 한다. 이 완료는 OMX 실물 조종의 승인이나 AI 학습 성능을 뜻하지 않는다.
