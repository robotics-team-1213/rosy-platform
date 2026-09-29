# ER 2 Mission·장치 Action 계약 연결 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Status:** Approved for sequential SOURCE/LOCAL implementation (2026-09-29, D-333/D-334). Each task's tests and contract updates are its merge gate. ROS-SIM, artifact, device and field acceptance remain separate evidence gates; this status does not activate OMX motion or model autonomy.

**Goal:** 운영자 또는 ER 2의 동일한 `PICK_PLACE` 후보를 승인된 Fleet Mission, OMX 로컬 Action, ROS 실행, 독립 목표 증거까지 추적 가능한 경로로 연결한다.

**Architecture:** [D-333](../adr/D-333-er2-mission-device-action-contract-closure.md)의 세 수락 경계, [D-334](../adr/D-334-er2-tool-and-progress-read-boundary.md)의 진행 조회 경계, [D-336](../adr/D-336-fleet-omx-local-ipc-boundary.md)의 co-located IPC 경계를 순서대로 연다. Fleet은 인증·Mission 원장·claim/stop generation을, OMX 로컬 owner는 Action 수락·ROS arm/gripper와 로컬 정지를, 등록된 관측 생산자는 목표 증거를 소유한다. 첫 범위는 고정 OMX 작업대의 operator 승인 `PICK_PLACE` 하나이며 ER 2는 후보 공급자다.

**Tech Stack:** Python 3.12, FastAPI/Pydantic, SQLite WAL, ROS 2 Jazzy, `FollowJointTrajectory`, 실제 장치의 검증된 gripper/driver 인터페이스, pytest. SOURCE/LOCAL Device Action transport는 D-336의 same-host UDS다. 실제 OMX host·장치 설치와 remote host transport는 HOLD다.

---

## 기준선과 범위

- 이미 있는 SOURCE: `src/site/fleet/fleet/ai/{candidate,er2_standard}.py`, `src/site/fleet/fleet/server/{mission_store,mission_service,goal_evidence}.py`, `src/products/omx/adapter/omx_adapter/{target_evidence,action_store,pick_place_transaction,gripper_contract,ros_runtime}.py`. 새 파일로 다시 만들지 않는다. 그 중 생산 route/runner 호출이 없는 부분을 연결한다.
- 전용 `/api/fleet/estop`은 감사·래치 기록 장애에도 인증된 정지 요청을 fanout하도록 구현돼 있다. `/api/fleet/do`의 `estop`은 일반 감사 gate와 순차 step을 거친다. 두 응답 모두 물리 정지의 영수증이 아니다. Fleet generation의 장치 측 fence, OMX 실제 stop/readback은 미완료다.
- 배포 소스는 개발/ROS-SIM workstation OCI, 비활성 profile, hardware shell이다. 필드 후보는 OMX별 native systemd owner다. 첫 SOURCE/LOCAL 연결은 같은 Linux host의 per-instance UDS로만 정의한다. Fleet과 OMX가 다른 host인 경우 remote API는 D-281/D-273 별도 결정 전 HOLD다. 채워진 host/device inventory는 아직 없다.
- 첫 범위 밖: 중앙 Fleet `/api/v1/fleet/missions` 구현, 단독 `PICK`/`PLACE`, 다장치 DAG, Pinky+OMX 이동, ER 2 streaming/연속 tool loop 및 `get_mission_status`·`request_observation`·`propose_replan` function declaration, 모델 자동 admission/replan, 생산용 이미지 전송. 범위 밖 기능을 현재 capability로 광고하지 않는다.
- 단계별 각 변경 전 `git status --short`, 현재 `main`과의 ancestry/파일 겹침을 확인한다. 다른 작업의 dirty 파일을 stage하지 않는다. `SOURCE/LOCAL`, `ROS-SIM`, `ARTIFACT`, `DEVICE`, `FIELD` 결과를 별도 기록한다.

## 작업 0. 배포 위치와 최종 writer를 확인한다

**Files:** Review `src/products/omx/adapter/README.md`, `src/products/omx/profile/config/omx.disabled.yaml`, `src/products/omx/adapter/omx_adapter/{command_owner,ros_runtime,profile}.py`, `deploy/`, `docs/adr/D-273-omx-camera-stream-and-arm-control-order.md`, `docs/adr/D-281-site-host-placement-and-omx-instance-isolation.md`, `docs/adr/D-282-per-hardware-ros-ownership-and-control-boundaries.md`, `docs/adr/D-299-omx-lerobot-development-and-command-ownership.md`, `docs/adr/D-330-fleet-action-admission-stop-and-recovery.md`, `docs/adr/D-336-fleet-omx-local-ipc-boundary.md`.

1. 배포 소스에서 workstation OCI shell, disabled profile, native per-workcell systemd 후보, ROS action/driver와 gripper source를 확인한다. 실제 host/장치 inventory가 없으면 field 설치 지점은 HOLD로 둔다.
2. 팔/그리퍼 command owner, 로컬 stop 입력, 최종 상태 readback, 재시작 시 driver goal 조회 가능 여부를 표로 적는다. 미확인 항목은 `HOLD`로 기록한다.
3. **Exit:** 첫 SOURCE/LOCAL transport는 co-located UDS, remote transport는 HOLD, 최종 Action journal과 ROS goal은 workcell별 native owner라는 계약으로 닫는다(D-336). 채워진 physical host/device inventory와 실물 serial/gripper/stop evidence가 없으므로 설치·field exit는 HOLD이며 source 결정을 실물 수용으로 표기하지 않는다.

## 작업 1. Mission·Device Action wire와 상태를 함께 고정한다

**Files:** Modify `docs/reference/ROSY API & Protocol Reference.md`, `src/contracts/foundation/core_common/protocol/schemas.py`; Test `src/runtime/gateway/test/test_protocol_schemas.py`, `src/site/fleet/test/test_mission_api.py`; Create `src/products/omx/adapter/test/test_omx_action_api.py` when device transport is chosen.

1. failing schema tests로 다음 불변식을 먼저 고정한다: server가 principal을 설정하고 client/model이 제출한 principal은 거절; caller 입력·관측·목표 digest와 `request_key`의 중복은 동일 ID, 다른 의미적 입력은 conflict; provider interaction/call ID나 새 발행 generation은 이 digest에 들어가지 않음; `proposal_id`, `mission_id`, `step_id`, `action_id`, `attempt_id`, provider call ID는 별개; 시간·generation·revision 누락은 거절.
2. Site Fleet 경로는 `POST /api/fleet/proposals`(미해결 후보 저장), `GET /api/fleet/proposals/{id}`, `POST /api/fleet/missions`(해결된 후보로 Mission 초안 생성), `GET /api/fleet/missions/{id}`(상태/증거), `POST /api/fleet/missions/{id}/admit`(명시적 operator 승인), `POST /api/fleet/missions/{id}/cancel`을 **신규 경로 제안**으로 검토한다. 중앙 Fleet의 기존 문서상 `/api/v1/fleet/missions`와 의미를 혼합하지 않는다. 실제 경로·HTTP 상태·Pydantic/schema/응답 표를 구현과 같은 커밋에서 API Reference에 확정한다.
3. Device Action transport는 D-336의 per-instance UDS로 고정한다. 필수 연산은 `SubmitAction`, `GetAction`, `CancelAction`, `StopLocal`, `GetStopState`다. `SubmitAction` envelope에는 `mission_id`, `step_id`, Fleet 발급 `action_id`/`attempt_id`, request digest, workcell/device identity, action kind, resolved source/destination evidence, capability/config revision, Fleet authority/epoch, `dispatch_generation`, grant expiry가 필요하다. peer UID와 socket path 권한을 검증하고, UDS StopLocal은 물리 E-stop/readback과 별도 사실로 반환한다. remote HTTP/device API는 이번 계약에 포함하지 않는다.
4. 각 API의 2xx/4xx/5xx·timeout·unknown ACK 의미와 취소/정지/readback의 별도 상태를 문서화한다. 예를 들어 acceptance 2xx는 물리 완료를 뜻하지 않고 timeout은 재시도 허가가 아니다. D-18대로 API Reference·schema·양쪽 소비자 시험이 함께 통과하지 않으면 새 wire를 노출하지 않는다.
5. Run: `python -m pytest src/runtime/gateway/test/test_protocol_schemas.py src/site/fleet/test/test_mission_api.py src/products/omx/adapter/test/test_omx_action_api.py -q` (생성한 파일부터 순차 포함). Expected: 누락·중복·권한·상태 사례 모두 통과. 해당 경로만 stage/commit한다.

## 작업 2. 같은 관측에 묶인 ER 2 selector를 해석한다

**Files:** Modify `src/site/fleet/fleet/ai/candidate.py`, `src/products/omx/adapter/omx_adapter/target_evidence.py`, `src/products/omx/adapter/omx_adapter/camera_contract.py` only where required; Create `src/site/fleet/fleet/ai/selector_bridge.py`, `src/site/fleet/test/test_selector_bridge.py`.

1. failing fixtures: `[y,x]=[575,664]`가 프레임 크기에 따라 `(x,y)`로 변환되는지; bbox 경계 0/1000, resize/crop/회전 역변환, 다른 프레임 digest, stale capture, 다른 camera/calibration/TF revision, 두 물체와 대상 이동은 거절되는지 검증한다.
2. provider 입력 이미지의 원본 프레임→모델 입력 변환 metadata를 후보 provenance에 추가한다. 이미지 크기만으로 crop/회전을 추정하지 않는다. 변환 불명은 `HOLD`다.
3. `TargetSelector`에는 원본 observation 픽셀을 넘기고 `resolve_target()`의 단일 물체 결과를 얻는다. 픽셀 선택 결과를 pose로 간주하지 않고 depth/작업면·grasp·충돌·도달성은 로컬 planner에 남긴다.
4. Run: `python -m pytest src/site/fleet/test/test_selector_bridge.py src/products/omx/adapter/test/test_omx_target_evidence.py -q`. Expected: 성공 및 모든 불일치 거절. 해당 경로만 stage/commit한다.

## 작업 3. operator 승인 Mission API를 실제 원장에 연결한다

**Files:** Create `src/site/fleet/fleet/server/proposal_store.py`; Modify `src/site/fleet/fleet/server/{app,mission_service,mission_store}.py`; Create/extend `src/site/fleet/test/{test_proposal_store,test_mission_api}.py`; update API Reference/schema from 작업 1 when wire changes.

1. failing end-to-end API test: 같은 요청의 create/read/admit와 저장된 후보 반환(provider 재호출 0회), 다른 digest 충돌, 모델 provenance 위조 principal 거절, operator 아닌 admission 및 개발용 기본 principal의 물리 admission 거절, 오래된 observation/capability revision 거절, generation 불일치, 기존 navigation claim과 동일 장치·공유 구역 경쟁을 시험한다.
2. `create_app`에 후보 저장소와 `MissionService`를 명시적으로 주입한다. 미해결 ER 2/운영자 후보는 별도 `ProposalStore`에 원본 이미지 bytes를 제외하고 필요한 출처·selector만 남긴다. 후보 metadata·지시문의 접근/보존 기간을 정한다. 단일 대상 해석이 성공한 경우만 현행 `MissionStore.create_proposal()`로 goal predicate가 있는 Mission 초안을 만든다. `AdmitMission`은 승인 주체와 불변 goal predicate/현재 관측을 검증한 뒤 공유 claim을 얻는다. `POLICY_DISPATCH_ENABLED=False`를 유지하고 admission과 물리 submission을 별도 처리한다.
3. `GET` 응답에 현재 상태, 상관 ID, unresolved/unknown 항목과 evidence 출처를 담되 이미지 bytes·API key는 포함하지 않는다. audit 실패 시 일반 mutation은 발행 전 거절한다.
4. Run: `python -m pytest src/site/fleet/test/test_proposal_store.py src/site/fleet/test/test_mission_api.py src/site/fleet/test/test_mission_store.py src/site/fleet/test/test_mission_service.py -q`. Expected: 후보 생성만으로 장치 호출 0회, 승인 때도 Action API 연결 전 물리 발행 0회. 해당 경로만 stage/commit한다.

## 작업 4. OMX 단일 owner의 Action API·ROS/그리퍼 runner를 연결한다

**Files:** Create `src/products/omx/adapter/omx_adapter/{action_api,action_runner}.py`; Modify `src/products/omx/adapter/omx_adapter/{action_store,pick_place_transaction,command_owner,ros_runtime}.py` only as verified; Test `src/products/omx/adapter/test/{test_omx_action_api,test_omx_action_runner}.py`.

1. failing test: 동일 action/attempt의 중복 submit은 goal 1회, 같은 ID의 다른 digest는 거절, `SUBMITTING` 영속화 전에 ROS goal 0회, driver 접수 뒤 저장 전 crash는 `UNKNOWN`/HOLD, restart는 자동 replay 0회. cancel ACK와 driver 결과가 다르면 완료를 선언하지 않는다.
2. `ActionStore.create_action()`과 `begin_submission()`의 자체 UUID 발급을 Fleet 발급 ID 수용 방식으로 바꾼다. 기존 로컬 Action row의 ID는 이관 중 그대로 보존하고 외부 ID 충돌·다른 digest 재사용을 거절한다. 작업 0의 확인된 ROS action/gripper port를 주입한다. `ActionStore`·`PickPlaceTransaction`·ROS arm/gripper readback을 하나의 로컬 owner 아래 연결하고 다른 프로세스/노드의 동시 최종 writer를 차단한다. 배포 unit/entrypoint는 실제 설치 경로에만 추가한다.
3. 물체 보유·해제·후퇴가 확인되지 않으면 `SUCCEEDED`를 만들지 않는다. 물체가 그리퍼에 남은 상태나 위치가 불명이면 HOLD로 두고 operator 복구를 요구한다.
4. Run: `python -m pytest src/products/omx/adapter/test/test_omx_action_api.py src/products/omx/adapter/test/test_omx_action_runner.py src/products/omx/adapter/test/test_omx_action_store.py src/products/omx/adapter/test/test_omx_pick_place_transaction.py -q`. Expected: 중복 물리 동작·자동 replay 0회. 해당 경로만 stage/commit한다.

## 작업 5. 정지 generation을 장치 최종 owner까지 전달한다

**Files:** Modify `src/site/fleet/fleet/server/{app,mission_service,mission_store,task_service}.py`, `src/products/omx/adapter/omx_adapter/{action_api,action_runner,action_store}.py`; update schema/API Reference together; Test `src/site/fleet/test/test_mission_stop_fence.py`, `src/products/omx/adapter/test/test_omx_stop_fence.py`.

1. 교차 순서 실패 시험: stop이 grant보다 먼저 장치에 도착하면 이전 generation은 거절; goal 접수 뒤 stop이면 새 goal 차단과 진행 중 goal local stop; Fleet/장치 재시작, 단절, grant 만료, clock 신뢰도 상실, 구 Fleet epoch, rearm 전 미확인 Action이 있으면 발행·자동 재개 0회.
2. 장치가 인증된 Fleet generation과 유효 기한을 영속 검증하고 local latch를 최종 ROS submit 바로 앞에서도 검사한다. 통신/lease 신선도가 없으면 새 goal을 거절한다. site stop 전송 미도달은 `UNKNOWN`으로 남기며 remote stop만으로 물리 정지 성공을 표시하지 않는다.
3. 전용 `/api/fleet/estop`의 감사 장애 fanout과 `/api/fleet/do`의 일반 감사 gate 차이를 직접 회귀 시험한다. 관제 긴급정지 표면은 전용 경로만 호출하고 로컬 stop/E-stop 경로를 독립적으로 검증한다.
4. Run: `python -m pytest src/site/fleet/test/test_mission_stop_fence.py src/products/omx/adapter/test/test_omx_stop_fence.py src/site/fleet/test/test_server_app.py -q`. Expected: stale 발행 거절 및 장애별 상태 구분. 해당 경로만 stage/commit한다.

## 작업 6. Fleet dispatcher와 장치 결과 조정을 연결한다

**Files:** Create `src/site/fleet/fleet/server/mission_dispatcher.py`, `src/site/fleet/test/test_mission_dispatcher.py`; Modify `src/site/fleet/fleet/server/{app,mission_service,mission_store}.py`; update API Reference/schema if the event or response wire changes.

1. failing test: operator가 승인한 Mission 한 건만 장치 API에 한 번 제출되고, 후보 생성만으로는 제출 0회; 기존 navigation task/직접 조작과 같은 claim에서는 동시 발행 0회; stop generation 불일치와 만료 grant는 제출 0회. timeout 또는 응답 손실 시 동일 Action을 자동 재전송하지 않고 `UNKNOWN`/HOLD로 남긴다.
2. Fleet 원장에 발행 의도와 Fleet 발급 `action_id`/`attempt_id`를 먼저 영속화한 뒤 단일 dispatcher가 OMX `SubmitAction`을 호출한다. 장치 수락과 ROS goal 접수는 별개 이벤트로 기록한다. 프로세스가 발행 의도 저장 후 네트워크 전송 전 죽어도 재시작 시 무조건 replay하지 않고 `GetAction`과 장치 readback으로 조정한다.
3. Action 결과 이벤트 또는 조회는 인증된 장치 identity, mission/step/action/attempt ID, request digest와 generation에 묶어 소비한다. 오래된 attempt와 중복 이벤트를 무시하고, `UNKNOWN` 또는 물체 보유 불명에서는 claim을 자동 해제하지 않는다. 일반 cancel 요청은 장치 cancel로 전달하되 stop/물리 결과와 별도로 기록한다.
4. Run: `python -m pytest src/site/fleet/test/test_mission_dispatcher.py src/site/fleet/test/test_mission_store.py src/site/fleet/test/test_mission_stop_fence.py -q`. Expected: 승인→장치 Action 수락→Fleet 결과 연결이 한 번만 발생하고 모호한 결과가 자동 재발행되지 않는다. 해당 경로만 stage/commit한다.

## 작업 7. 독립 goal 증거와 결과 상관관계를 닫는다

**Files:** Modify `src/site/fleet/fleet/server/{goal_evidence,mission_service,mission_store}.py`; Create `src/site/fleet/test/test_mission_goal_provenance.py`; update 실제 증거 producer/consumer 및 schema/API Reference.

1. failing tests: Action `SUCCEEDED`와 모델의 완료 문구만 있을 때 Mission 미완료; 모델 입력으로 쓴 작업 전 프레임 재사용, 등록되지 않은 `camera_observation` producer, 다른 프레임 digest, 오래된 관측, 다른 evaluator revision, 그리퍼 미해제, 잘못된 object/destination은 완료 거절.
2. 등록된 증거 생산자의 인증·관측 원본 digest·capture time·predicate/evaluator revision을 원장과 결합한다. Action/attempt와 gripper/arm readback이 승인된 Mission goal과 일치할 때만 완료한다.
3. 늦은 이전 attempt 결과·서로 충돌하는 관측·물체 보유 불명은 HOLD와 조정 이벤트로 남긴다. 새 attempt는 이전 물리 효과를 확인한 뒤 운영자가 열게 한다.
4. Run: `python -m pytest src/site/fleet/test/test_mission_goal_provenance.py src/site/fleet/test/test_goal_evidence.py -q`. Expected: 독립 관측 없는 `completed` 0회. 해당 경로만 stage/commit한다.

## 작업 8. 작업 중 진행 snapshot과 재연결 읽기를 제공한다

**Files:** Create `src/site/fleet/fleet/server/mission_progress.py`, `src/site/fleet/test/test_mission_progress.py`; Modify `src/site/fleet/fleet/server/{app,mission_service,mission_store}.py`; update `docs/reference/ROSY API & Protocol Reference.md` and `src/contracts/foundation/core_common/protocol/schemas.py` together.

1. failing tests: provider Interaction이 완료돼도 Action `RUNNING`이면 Mission 완료가 아님; Action `SUCCEEDED` 뒤 goal 증거 대기는 별도; stop 요청 뒤 장치/물리 readback 불명은 정지 완료가 아님; stale device 보고·늦은 이전 attempt 이벤트·중복 이벤트·다른 principal 조회는 거절 또는 `UNKNOWN`으로 표시한다.
2. `GET /api/fleet/missions/{id}`의 진행 snapshot에 Fleet Mission/Step, OMX Action, goal evidence, stop의 네 축을 source·마지막 event ID·observed time·revision·freshness·reason과 함께 투영한다. 현재 저장소에 없는 증거는 추정하지 않는다. 새 wire 필드·HTTP 상태는 schema/API Reference와 함께 확정한다. 숫자 진행률은 물리 근거가 없으면 내지 않는다.
3. 첫 범위에 Mission별 cursor 이벤트 조회를 반드시 포함한다. 목표 경로는 `GET /api/fleet/missions/{id}/events?after_event_id=...`이다. 이벤트 ID는 Fleet 원장 순서이며 장치 시각의 순서가 아니다. 권한·cursor 검증·limit·보존 기간·중복/누락·보존 범위 밖 cursor의 snapshot 재시작 응답을 schema·API Reference·생산자/소비자 시험에서 함께 확정한다. 화면은 재연결 때 snapshot을 먼저 읽고 cursor로 변경분을 합친다. 구독/WebSocket은 별도 후속 범위다.
4. 모델에 상태를 보여야 할 때 Fleet이 같은 snapshot의 민감정보를 줄인 principal/workcell 범위 버전을 입력으로 만들 수 있게 한다. 이 작업은 `get_mission_status` function declaration을 현행 ER 2 adapter에 추가하거나 provider tool-result loop를 여는 것이 아니다.
5. Run: `python -m pytest src/site/fleet/test/test_mission_progress.py src/site/fleet/test/test_mission_dispatcher.py src/site/fleet/test/test_mission_goal_provenance.py -q`. Expected: 진행·완료·정지·불명의 네 축이 구별되고, 단절/중복/누락/오래된 cursor 후 재연결에서도 늦은 이벤트가 상태를 되돌리지 않는다. 해당 경로만 stage/commit한다.

## 작업 9. ER 2를 후보 입력으로 연결하고 비모델 경로와 비교한다

**Files:** Modify `src/site/fleet/fleet/ai/{candidate,er2_standard}.py`, `src/site/fleet/fleet/server/app.py` or a dedicated proposal service; Test `src/site/fleet/test/{test_er2_standard,test_mission_ai_proposal}.py`; update deployment secret template and ignore rule only when a new secret kind is introduced.

1. operator/규칙 후보와 ER 2 후보가 동일 `CreateProposal` 검증을 통과하는 fixture를 만든다. 모델 `provider_call_id`를 `action_id`로 사용하거나 tool call을 바로 실행하면 실패해야 한다. 현재 provider 요청에는 `propose_pick_place` 하나만 선언되고 `get_mission_status`/`request_observation`/물리 tool이 없음을 고정한다.
2. 실제 카메라 이미지 전송 전에 provider 서비스 등급·데이터 처리, 허용 장면, 키 제한·주입/교체, traceback/log 마스킹, 호출 budget/rate limit을 문서와 배포 설정으로 검증한다. API key guide의 현재 key 종류/제한 조건을 해당 시점에 공식 문서에서 재확인한다.
3. provider timeout/다중 호출/형식 불일치 시 Mission/Action 0건. live provider 파일럿은 별도 승인된 데이터와 비용 상한에서만 실행하고 모델 정확도·지연을 고정 fixture와 구분 기록한다. 모델 없이도 동일 Mission이 실행 가능해야 한다.
4. Run: `python -m pytest src/site/fleet/test/test_er2_standard.py src/site/fleet/test/test_mission_ai_proposal.py -q`. Expected: 무승인 Mission 발행·장치 호출 0회. 해당 경로만 stage/commit한다.

## 작업 10. 실제 설치와 물리 수용을 별도 판정한다

**Files:** Add evidence only under `docs/validation/<omx-action-acceptance-YYYY-MM-DD>/`; update `src/products/omx/adapter/{progress,logs}.md`, `src/site/fleet/{progress,logs}.md`, `docs/{progress,logs}.md` when corresponding gate changes; run harness generator.

1. SOURCE/LOCAL: 관련 Fleet·OMX·protocol tests와 docs harness를 통과한다. 동일 파일명의 테스트 충돌은 패키지별 별도 invocation으로 분리한다.
2. ROS-SIM: stop/goal 교차, 통신 단절, late ACK, 재시작, grasp 실패, 물체 미배치, 증거 충돌을 재현한다. 실제 설치 산출물과 구분한다.
3. ARTIFACT: native package closure·driver/ROS 버전·서명/digest·설치 대상을 확인한다. DEVICE: 장치 identity, 단일 writer, 로컬 stop 및 독립 E-stop, 측정된 정지 latency, gripper/물체/arm readback을 현장 안전 절차 안에서 확인한다. FIELD는 작업대 위험과 감독/복구를 별도로 수용한다.
4. 실패 시 rollback은 조작 capability와 Mission dispatcher를 다시 닫고, 이미 제출된 Action의 결과·보유 상태를 장치에서 조정하는 것이다. Fleet 원장 삭제나 같은 요청 재발행으로 rollback하지 않는다.
5. Run: `python -m pytest test/test_network_topology_contracts.py test/test_harness_contracts.py -q`; `python tools/harness/rosy_harness.py lint`. Expected: 문서 계약 통과. `generate` 후 생성 index와 git diff를 확인한다. 해당 검증 범위만 stage/commit한다.

## 완료 기준

운영자 요청 한 건에 대해 `request_key → proposal_id → mission_id/step_id → action_id/attempt_id → driver goal ID → 독립 goal evidence`가 같은 프레임·장치·generation으로 추적되고, 중복·늦은 결과·정지·재시작에서도 물리 작업이 자동 재발행되지 않아야 SOURCE/LOCAL을 완료로 판정한다. ROS-SIM, 설치 산출물, 실물 동작과 물리 정지는 각각의 증거가 생길 때만 승격한다. 모델 후보만 시험한 결과로 OMX capability를 활성화하지 않는다.


## Execution record (2026-09-29)

- Task 0: complete. D-336 selects same-host per-instance UDS; remote host transport remains HOLD. Commit `463ccf12`.
- Task 1: complete. Added typed Device Action and Local Stop schemas plus API Reference v1.48 and failing-first contract tests. Commit `0e632b6f`; full foundation suite: 101 passed.
- Task 2: complete. Added normalized selector inverse mapping including crop, resize, and quarter-turn transforms. The bridge checks source frame provenance and emits pixel-level evidence using shared contract types; Fleet has no OMX package dependency. Full Fleet suite: 600 passed, 5 skipped.
- Version sequencing: D-268 occupies API Reference v1.48; this ER2 contract is v1.49.
- Task 3: complete for SOURCE/LOCAL. Added a 32 KiB metadata-only ProposalStore with 30-day expiry cleanup; separate proposal create/read, current-evidence resolution into an immutable Mission draft, and named-operator generation-checked admission/readback routes. Mission creation and proposal resolution now commit in one SQLite transaction; injected failure rolls both back and leaves the proposal retryable. Candidate free-text fields also have individual bounds. Resolver is injected and must recheck the current observation, capability, revisions, and unique object targets. All four stores share one SQLite database; proposal creation never calls the provider, admission rechecks evidence and claims workcell plus both objects atomically, and no Action/ROS submission is connected. API Reference v1.50. Verification: Fleet 653 passed/5 skipped; API web 70 passed/13 skipped; changed-path flake8 clean. Hardware-free resolver fixtures do not validate a live camera/evidence producer.
- Next checkpoint: Task 4, OMX Action API/runner. UDS listener, ROS-SIM, artifact, DEVICE, and FIELD remain separate and are not activated by SOURCE/LOCAL completion.
