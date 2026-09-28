# ER 2 의미적 조작과 Fleet Mission 구현 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 모델·운영자가 같은 의미적 조작 후보를 제출하고, Fleet이 작업 순서와 목표를 관리하며, OMX 로컬 미들웨어와 ROS가 검증된 동작을 실행하고 독립 증거로 결과를 판정할 수 있게 한다.

**Architecture:** D-327의 대상 resolve/Device Action을 고정 OMX 작업대에서 모델 없이 먼저 닫는다. D-328의 Fleet Mission/Step 원장과 목표 predicate를 그 위에 연결한 다음 ER 2를 실행권 없는 후보 생산자로 붙인다. 장치 취소·안전 stop·물리 readback은 모델/Fleet 세션과 독립이다.

**Tech Stack:** Python 3.12, FastAPI/Pydantic, SQLite WAL, ROS 2 Jazzy `FollowJointTrajectory`/`ros2_control`, OMX adapter, pytest, 선택적 MoveIt 2, 별도 게이트의 Isaac Sim. ER 2 표준/streaming API는 후순위 어댑터다.

---

## 기준선·범위·착수 규칙

- 계약: [D-327](../adr/D-327-semantic-manipulation-actions-and-device-adapters.md), [D-328](../adr/D-328-model-proposed-missions-and-independent-goal-evidence.md), [D-308](../adr/D-308-intent-and-device-action-interpretation-boundary.md), [D-307](../adr/D-307-final-action-outcome-and-stop-readback-evidence.md), [D-18](../adr/D-18-rosy-core.md). [사용자 제공 실험 대조](2026-09-29-er2-isaac-sim-architecture-assessment.md)는 사례이며 장치 수용 증거가 아니다.
- 현재 `src/products/omx/profile/config/omx.disabled.yaml`은 `enabled: false`다. `omx_adapter`는 카메라 pair와 arm trajectory 단일 submitter 후보를 갖지만 그리퍼/물체 보유·배치 검증 및 원격 Device Action API가 없다. `src/site/fleet/fleet/server/task_service.py`는 Pinky navigation task만 영속화하고 policy dispatch는 닫혀 있다. `/api/fleet/do`의 `steps`는 Mission DAG가 아니다.
- 이 계획의 첫 실제 작업은 **고정 OMX의 알려진 블록→트레이 `PICK_PLACE`**다. 단독 `PICK`/`PLACE`, Pinky+OMX 운반, 다중 장치, ER 2 자동 dispatch는 아래 출구를 통과하기 전까지 capability로 광고하지 않는다. 현재 Pinky API/`TaskKind`를 OMX용으로 재사용하지 않는다.
- 각 단계는 새 격리 worktree와 최신 `main`의 HEAD·dirty path 비교 후 시작한다. API 경로·wire enum·envelope이 바뀌는 커밋은 `docs/reference/ROSY API & Protocol Reference.md`, `src/contracts/foundation/core_common/protocol/schemas.py`, 생산자/소비자 시험을 함께 바꾼다. 제안 경로를 이미 존재하는 API로 설명하지 않는다.
- SOURCE/LOCAL/ROS-SIM, ARTIFACT, DEVICE, FIELD를 별도 기록한다. 모델이나 시뮬레이션 통과로 `omx.enabled`를 켜지 않는다. 실제 팔·모터 동작은 장치 인벤토리, 독립 정지와 현장 입회·수용 절차를 갖춘 별도 DEVICE 세션에서만 한다.

## 작업 0. 실제 장치·배포·제어 경계 재확인

**Files:** Review `src/products/omx/adapter/omx_adapter/{command_owner,ros_runtime,camera_contract,ros_camera_runtime,profile}.py`, `src/products/omx/profile/config/omx.disabled.yaml`, `deploy/omx/`, `docs/adr/D-273-omx-camera-stream-and-arm-control-order.md`, `docs/adr/D-282-per-hardware-ros-ownership-and-control-boundaries.md`, `docs/adr/D-299-omx-lerobot-development-and-command-ownership.md`; Create `docs/validation/<omx-action-baseline-YYYY-MM-DD>/README.md` when actual evidence exists.

1. 현재 checkout의 OMX-F/L 모델·revision, gripper, driver, serial owner, camera, calibration, 정지·하중 readback의 확인 상태를 항목별로 기록한다. 미확인 정보는 빈 값과 HOLD 사유로 남긴다.
2. 실물 inventory가 없어도 SOURCE 단계는 진행하되, vendor sim의 joint/그리퍼 인터페이스와 실제 설치 closure를 혼동하지 않는다. 현재 `command_owner.py`가 단일 trajectory를 받을 수 있다는 사실을 gripper/stop 수용으로 승격하지 않는다.
3. 기존 OMX LeRobot 계획의 오래된 `src/devices/...` 경로와 현행 `src/products/omx/...`를 비교해 후속 구현 참조 경로를 확정한다. 서명 이미지·native payload·장치 readback의 부족분을 작업별 gate로 넘긴다.
4. **Exit:** 어떤 코드와 장치가 arm/gripper 최종 writer인지, 어떤 관측이 없는지 표로 설명할 수 있다. owner 또는 정지 경로가 불명확하면 실행 코드 착수를 중단한다.

## 작업 1. 모델 없는 selector·관측 계약

**Files:** Create `src/products/omx/adapter/omx_adapter/target_evidence.py`, `src/products/omx/adapter/test/test_omx_target_evidence.py`; Modify `src/products/omx/adapter/omx_adapter/camera_contract.py` only if existing pair metadata lacks a required field.

1. **실패 시험:** 같은 프레임의 명시된 object ID, label/관계, point/bbox가 단일 물체로 resolve되는 경우와 다중 후보·stale frame·crop 역변환 누락·카메라/보정 revision 불일치·대상 이동을 거절하는 경우를 합성 fixture로 작성한다. 텍스트만으로 물체 ID를 영속 생성하는 경로는 거절한다.
2. `python -m pytest src/products/omx/adapter/test/test_omx_target_evidence.py -q`로 먼저 실패를 확인한다.
3. 원본 observation ID·프레임 digest·촬영 시각·source/optical frame·transform·calibration/TF revision·selector provenance를 묶는 ROS-free 타입과 resolver를 최소 구현한다. point는 후보로만 저장하며 깊이/작업면/자세를 독립 검증하기 전 pose로 올리지 않는다.
4. 같은 시험과 기존 `test_omx_camera_contract.py`를 통과시켜 경로만 stage/commit한다. **Exit:** 모델 입력 없이 운영자 selector로 정확히 한 대상 또는 명시적 거절을 돌려준다.

## 작업 2. OMX 로컬 `PICK_PLACE` transaction과 결과 증거

**Files:** Create `src/products/omx/adapter/omx_adapter/{pick_place_transaction,gripper_contract}.py`, `src/products/omx/adapter/test/{test_omx_pick_place_transaction,test_omx_gripper_contract}.py`; Modify `src/products/omx/adapter/omx_adapter/{command_owner,ros_runtime}.py` only for 검증된 arm/gripper adapter 연결.

1. **실패 시험:** stale joint/scene, 중복 writer, grip 미확인, 물체 미보유, 배치 영역 외 release, cancel 중 하중 보유, driver 결과 누락, 늦은 성공, 재시작 후 불명확한 물체 상태를 fake action/clock으로 재현한다. `ACCEPTED`, 최종 Action 결과, 물체 보유, 실제 정지를 서로 다른 기록으로 검사한다.
2. 새 시험을 실행해 실패를 확인한다. ROS 2 의존 시험은 별도 invocation으로 분리한다.
3. rule-based 첫 fixture에서 접근→grasp→grip_verified→transfer→release→placement_verified의 상태와 로컬 owner/lease를 구현한다. 실제 grasp pose·속도·payload·충돌 한계는 vendor/실측 근거 없이는 상수로 발명하지 않는다. MoveIt Task Constructor는 이 transaction의 내부 planner 후보이며 필수 선행 라이브러리로 강제하지 않는다.
4. `python -m pytest src/products/omx/adapter/test/ -q`와 vendor ROS-SIM focused test를 실행하고 해당 경로만 commit한다. **Exit:** rule-based SIM 결과와 원본 driver/readback을 연결할 수 있으나 `omx.enabled: false`와 원격 API HOLD는 유지한다.

## 작업 3. OMX Device Action API·취소·정지 계약

**Files:** Modify `docs/reference/ROSY API & Protocol Reference.md`, `src/contracts/foundation/core_common/protocol/schemas.py`; Create `src/products/omx/adapter/omx_adapter/{action_api,action_store}.py`, `src/products/omx/adapter/test/{test_omx_action_api,test_omx_action_store}.py`; Review `src/products/omx/adapter/omx_adapter/cli.py`, deployment unit/entrypoint under `deploy/omx/`.

1. **계약 결정:** D-18에 따라 실제 producer/consumer 및 host placement를 먼저 정하고 API 경로·principal·workcell identity·capability/version·`request_key`·기한·observation/config revision·`action_id`/`attempt_id`·상태/결과를 API Ref와 schema에서 함께 고정한다. 같은 key/같은 본문은 같은 Action, 같은 key/다른 본문은 충돌이다. timeout 뒤 무조건 재발행하지 않는다.
2. **실패 시험:** 인증 실패, disabled capability, stale observation, direct ROS 우회, 중복 요청, 취소 ACK 뒤 잔류 운동, HTTP 200 뒤 최종 결과 부재, 재시작 뒤 중복 실행을 검사한다. 공개 status 조회는 권위 있는 로컬 event/driver 시각을 포함한다.
3. 로컬 Action API를 transaction owner에만 연결한다. 새 명령 차단·일반 cancel·fault HOLD·독립 E-stop/readback을 별도 경로/상태로 구현한다. HTTP API process와 ROS owner를 별도 프로세스로 둘 경우 단일 writer/재시작/IPC 계약을 이 작업에서 시험한다. **실물 E-stop 회로나 안전 한계는 소프트웨어 API로 대체하지 않는다.**
4. API Ref·schema·생산자/소비자 시험을 같은 commit으로 묶고 `python -m pytest src/products/omx/adapter/test/ src/runtime/gateway/test/test_protocol_schemas.py -q`를 실행한다. **Exit:** 모델 없는 운영자 요청의 접수·조회·취소·최종 결과는 SIM에서 닫히고 물리 정지는 여전히 DEVICE 증거가 필요하다.

## 작업 4. Fleet 단일 Step Mission과 독립 목표 predicate

**Files:** Create `src/site/fleet/fleet/server/{mission_store,mission_service,goal_evidence}.py`, `src/site/fleet/test/{test_mission_store,test_mission_service,test_goal_evidence}.py`; Modify `src/site/fleet/fleet/server/app.py`, API Ref/schema when actual wire is introduced.

1. **실패 시험:** 장치 `PICK_PLACE` 성공/목적지 물체 부재, 모델 “완료”/물리 실패, 센서 충돌, 관측 stale, 최종 Action 결과 불명, 부분 실행 후 HTTP 오류를 각각 별도 상태로 기대한다. 목표 predicate는 Mission 접수 전에 저장하고 이후 모델 문구가 이를 바꾸지 못하게 한다.
2. 기존 `FleetTaskService`의 navigation task를 회귀 기준으로 유지하며 별도 Mission/Step 원장을 최소 구현한다. Action/attempt 이벤트를 append-only로 연결하고 동일 event ID 중복·지연·재시작을 시험한다. 카메라 원본은 Fleet DB에 넣지 않고 출처·digest/파생 관측만 둔다.
3. `python -m pytest src/site/fleet/test/test_mission_store.py src/site/fleet/test/test_mission_service.py src/site/fleet/test/test_goal_evidence.py src/site/fleet/test/test_task_service.py -q`를 통과시켜 commit한다. **Exit:** 장치 Action 성공을 사이트 목표 성공으로 자동 승격하지 않는다.

## 작업 5. 병렬 Step·인계·재계획 경계

**Files:** Modify `src/site/fleet/fleet/server/{mission_store,mission_service,task_scheduler}.py`; Create `src/site/fleet/test/{test_mission_dag,test_mission_handoff,test_mission_replan}.py`.

1. **실패 시험:** 두 독립 Step의 병렬 dispatch, 같은 장치/공유 구역 중복 예약 거부, 한 Step 실패 뒤 join 대기, 적재 실패 중 base 출발 금지, 운반 도착 후 하중 부재 시 하역 금지, 같은 물체의 중복 pick, 늦은 ACK 뒤 무조건 재시도를 거절한다.
2. Fleet에 DAG dependency와 예약/인계 predicate를 추가한다. 물리 보유·적재 상태가 불명확하면 재계획 후보를 보류하고 이전 attempt와 새 attempt를 분리한다. Pinky+OMX 실제 운반은 D-55의 footprint/하중·정지 연동과 DEVICE/FIELD 검증 전까지 실행 capability가 아니다.
3. `python -m pytest src/site/fleet/test/test_mission_dag.py src/site/fleet/test/test_mission_handoff.py src/site/fleet/test/test_mission_replan.py src/site/fleet/test/ -q`를 실행해 commit한다. **Exit:** 두 장치의 독립 작업과 의존 인계를 SIM에서 구별하고 한 장치의 수락을 전체 완료로 표시하지 않는다.

## 작업 6. ER 2 제안 어댑터와 모델 없는 비교 기준

**Files:** Create `src/site/fleet/fleet/ai/{__init__.py,candidate.py,er2_standard.py,er2_streaming.py}` 및 `src/site/fleet/test/{test_ai_candidate,test_er2_standard,test_er2_streaming}.py`; Modify `src/site/fleet/fleet/server/mission_service.py` only to consume validated candidates.

1. 사람/규칙/ER 2가 같은 typed 후보를 만들고 모델이 쓴 principal·workcell 권한·직접 `move`/gripper 명령이 실행되지 않는 실패 시험을 쓴다. 모델 tool-call ID와 Mission/Step/Action/attempt ID를 분리해 중복·세션 재연결·늦은 결과를 검증한다.
2. 표준 ER 2와 streaming ER 2의 다른 응답/도구 프로토콜을 별도 adapter로 파싱한다. streaming 물리 tool의 `BLOCKING` 의미는 모델 응답 대기이며 Fleet 병렬 scheduler가 아님을 시험한다. 미인증 모델 제안을 자동 제출하지 않는다.
3. 동일한 고정 fixture와 실패 주입에서 사람/규칙/ER 2의 대상 resolve, 재관찰, 잘못된 완료, 지연을 비교한다. `POLICY_DISPATCH_ENABLED=False`를 유지하고 모델 추가로 정지 경로를 바꾸지 않는다. 네트워크 credential은 비공개 설정에 둔다.
4. `python -m pytest src/site/fleet/test/test_ai_candidate.py src/site/fleet/test/test_er2_standard.py src/site/fleet/test/test_er2_streaming.py -q`로 확인해 commit한다. **Exit:** 모델이 없어도 같은 Mission을 수행할 수 있고 모델이 없어져도 Action/목표 결과가 남는다.

## 작업 7. 시뮬레이션·산출물·실물 출구

**Files:** Add targeted fixture/test under `src/sim/isaac_sim/` only after its separately integrated D-322 path is verified; update `docs/validation/<topic-YYYY-MM-DD>/`, `deploy/omx/` release records, product progress/logs. Do not edit active Isaac WIP in another worktree.

1. ROS-SIM에서 정상, 물체 이동, 파지 실패, 그리퍼만 성공, 트레이 밖 배치, 모델 거짓 완료, 통신 단절, cancel 후 잔류 운동, 장치 재시작을 재현한다. fixture에는 관측 oracle과 원시 이벤트 시각을 보존한다. Franka/Spot 데모 숫자를 ROSY 통과 기준으로 복사하지 않는다.
2. ARTIFACT에서 실제 OMX native payload의 package closure, vendor driver/ROS 버전, 서명·digest·설치 대상을 확인한다. SOURCE의 synthetic gripper나 Isaac import만으로 ARTIFACT/DEVICE를 GO로 바꾸지 않는다.
3. DEVICE에서 장치별 독립 정지, driver/관절·그리퍼·물체 readback, 물체 낙하 위험, 정지 시간과 재개 절차를 감독 하에 측정한다. 그 전에는 원격 물리 Action과 단독 `PICK`/`PLACE`를 광고하지 않는다. FIELD 인계·운반은 별도 승인/실측이다.
4. 현장 측정으로 gate를 올릴 때만 각 모듈 `progress.md`와 append-only `logs.md`를 갱신하고 harness generate/test를 실행한다. 특정 gate 실패 시 해당 capability만 disabled로 롤백하고 이미 발행된 Action의 로컬 결과/readback을 확인한다.

## 전체 검증과 계획의 경계

- 문서/계약 단계: `python -m pytest test/test_network_topology_contracts.py test/test_harness_contracts.py -q`; `python tools/harness/rosy_harness.py lint`.
- 구현 단계: 위 작업별 focused test 뒤 `python -m pytest src/runtime/gateway/test/ src/site/fleet/test/ src/products/omx/adapter/test/ test/ -q`를 순차 실행한다. ROS가 필요한 시험은 Jazzy 환경에서 별도 실행한다. 같은 이름의 시험 파일이 충돌하는 패키지 집합은 별도 invocation으로 나눈다.
- 이 계획을 작성하고 커밋하는 것만으로 API·ROS action·모델 호출이 구현되거나 실물 로봇이 움직이지 않는다. 작업 0의 장치 정보 또는 D-18의 API/schema 동시 계약이 없으면 후속 실행을 진행하지 않는다.
