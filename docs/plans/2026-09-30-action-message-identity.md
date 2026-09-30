# Action / Message Identity Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 메시지 교환과 장치 실행의 식별 수명을 정리하고 producer/consumer의 상관관계·정지·완료 책임을 검증한다.

**Architecture:** D-369의 Fleet/장치/ROS/safety/verifier 책임을 따른다. PRT·REST·UDS의 wire를 유지하고 공통 의미와 실패 처리를 실제 경계 시험으로 검증한다. 새 범용 bus나 자동 재실행을 만들지 않는다.

**Tech Stack:** Python, Pydantic, SQLite, pytest. ROS 2 Jazzy 실기 검증은 별도.

[설계](2026-09-30-action-message-identity-design.md). 이번 범위는 Task 1 완료이며 Task 2–4는 미수행 후속 계획이다. provider/OMX 활성화와 실물 수용은 포함하지 않는다.

### Task 1: 현재 계약 정정과 Fleet–OMX JSON 경계 시험

**상태:** 완료. 결합·인접 suite 21 passed.

**Files:**
- Modify: `docs/reference/ROSY API & Protocol Reference.md` §10.12
- Modify: `src/contracts/foundation/core_common/protocol/schemas.py` — DeviceActionLookup docstring만
- Create: `test/test_fleet_omx_action_identity_contract.py`
- Modify: `CONCEPTS.md`, D-369, docs progress/log/index

1. 실제 SubmitAction/GetAction/CancelAction JSON 생산자와 소비자를 비교한다.
2. GetAction 요청은 action ID만 받고 응답에서 attempt를 검증한다는 계약을 명시한다.
3. Fleet transport의 socket만 메모리 JSON 왕복으로 대체하고 실제 OMX API/runner/store를 연결한다.
4. 같은 grant 중복 submit·반복 조회·취소가 같은 Action/attempt와 한 번의 driver submit을 유지하는지 시험한다.
5. 다른 attempt/Mission/step/generation/epoch/digest의 응답을 거절하고 terminal readback에서도 ID를 보존하는지 확인한다.

Run: `python -m pytest test/test_fleet_omx_action_identity_contract.py src/site/fleet/test/test_mission_dispatcher.py src/products/omx/adapter/test/test_omx_action_api.py -q -p no:cacheprovider`

Expected: 모두 통과. socket 인증·ROS·실물 수용은 별도다.

### Task 2: 응답 유실·재시작·늦은 결과의 상관관계

**상태:** 후속.

**Files:**
- Test: `test/test_fleet_omx_action_identity_contract.py`
- Inspect/modify if failing: `src/site/fleet/fleet/server/mission_dispatcher.py`, `local_action_transport.py`
- Inspect/modify if failing: `src/products/omx/adapter/omx_adapter/action_runner.py`, `action_store.py`
- Test: `src/site/fleet/test/test_mission_dispatcher.py`, `src/products/omx/adapter/test/test_omx_action_store.py`

1. 실제 API 접수 직후 응답 유실을 주입한다. Fleet을 같은 DB로 재구성하고 GetAction으로 조정하되 driver submit 수는 1이어야 한다.
2. 이전 attempt/세대의 결과, 중복 terminal 사건, 순서가 뒤바뀐 readback을 주입한다. 상태 퇴행·잘못된 claim 해제가 없어야 한다.
3. 4xx가 미실행을 확정하는 분기와 transport 후 불명을 비교한다. 재시도 허가를 잘못 내리는 실패만 최소 수정한다.
4. Task 1 명령과 `python -m pytest src/products/omx/adapter/test/test_omx_action_store.py -q`를 실행한다.

완료 조건: 같은 persisted grant를 조회해 조정하며 자동 새 Action/attempt 또는 driver 재발행이 없다. 기존 구현으로 충족하면 중복 구현을 추가하지 않는다.

### Task 3: 진행 상태와 stop 증거의 소비자 계약

**상태:** 후속.

**Files:**
- Inspect: `src/site/fleet/fleet/server/mission_progress.py`, `mission_store.py`, `local_stop_transport.py`
- Inspect: `src/contracts/foundation/core_common/protocol/schemas.py`
- Test: `src/site/fleet/test/test_mission_progress.py`, `src/site/fleet/test/test_local_stop_transport.py`
- Test: `src/products/omx/adapter/test/test_omx_stop_fence.py`

1. 실제 store→projection에서 provider/Mission/Action/goal/stop 축의 attempt와 신선도 연결을 시험한다.
2. cancel ACK, local latch, driver 정지, goal confirmation 중 한 사실만으로 다른 축이 성공하지 않는지 확인한다.
3. 없는 정보는 unknown/unavailable로 유지한다. 필드 추가가 필요하면 API Ref·schema·producer/consumer·UI를 함께 갱신하고 additive 버전을 올린다.
4. 위 세 test 파일을 실행한다. UI 변경이 있으면 stale/unknown/진행/완료 화면도 확인한다.

완료 조건: 미확인 증거를 완료로 표시하지 않고 stop 처리가 모델 tool이나 일반 작업 queue의 완료를 기다리지 않는다.

### Task 4: 선정 ROS/driver profile의 Action–goal 대응

**상태:** driver/gripper profile과 실장 환경이 필요하다.

**Files:**
- Inspect: `src/products/omx/adapter/omx_adapter/action_runner.py`, `action_store.py`
- Contract: `docs/reference/ROSY API & Protocol Reference.md` §10.12
- Test: 선정 driver의 ROS-SIM suite 및 phase/goal 대응 시험

1. 한 Action/attempt에 속하는 arm/gripper phase와 각 ROS goal UUID의 대응표를 작성한다. 현재 driver_goal_id 하나로 여러 goal을 덮어쓰지 않는다.
2. phase별 submit intent·goal ID·terminal·cancel 범위·재시작 조회 가능성을 실제 port와 정한다. 이력 store/schema 변경은 별도 검토한다.
3. ROS-SIM에서 늦은 feedback·재시작·cancel 경쟁을 검증하고 DEVICE에서 정지와 목표 증거를 각각 수용한다.

완료 조건: profile 하나의 생산자/소비자와 복구 근거가 있으며 ROS goal terminal, 독립 goal confirmation, 물리 stop을 구분한다.

### 실행 기록

- Task 1은 문구·type 설명과 결합 시험을 반영했다. wire/runtime 동작 변경 없음.
- 제어권 ADR 초안 D-362는 충돌을 피하여 D-369로 변경했다. D-362–D-368은 다른 작업의 번호다.
- 최종 quick gate + network 문서 계약 119 passed; harness lint 0 errors/기존 freshness warnings 12; 새 시험 flake8 및 diff check 통과. 자세한 기록은 docs/logs.md의 action/message 항목에 둔다.
