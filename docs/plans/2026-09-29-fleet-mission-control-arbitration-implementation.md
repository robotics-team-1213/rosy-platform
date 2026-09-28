# Fleet Mission 발행·정지·복구 통합 구현 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 기존 Pinky navigation 작업과 신규 Fleet Mission이 한 장치의 발행 권한을 공유하고, 정지·장애·재시작 뒤 대기/진행 Action을 확인 없이 재발행하지 않게 한다.

**Architecture:** [D-330](../adr/D-330-fleet-action-admission-stop-and-recovery.md)의 Fleet 단일 claim과 stop generation을 현행 task 저장소에 먼저 연결한다. 사이트 정지 요청은 인증 후 감사 DB 장애와 독립적으로 전송하되, 장치 로컬 stop/readback 및 물리 E-stop과 구분한다. OMX Action은 driver 호출 전 의도를 기록하고 모호한 접수 결과를 HOLD한다. 이 계획은 [의미적 조작·Mission 계획](2026-09-29-er2-semantic-actions-mission-implementation.md)의 작업 3~5에 들어가기 위한 통합 선행 계획이다.

**Tech Stack:** Python 3.12, FastAPI/Pydantic, SQLite WAL, pytest; 장치 단계는 ROS 2 Jazzy action과 제품별 driver readback. 새 REST/ROS 계약은 실제 소비자와 D-18 절차에서 결정한다.

---

## 시작 조건과 변경 범위

- 최신 `main`과 관련 worktree의 HEAD/dirty 경로를 비교하고 격리 작업트리에서 단계별 구현한다. 현재 소스 근거는 `src/site/fleet/fleet/server/{app,task_store,task_scheduler,task_service,console}.py`, `src/products/omx/adapter/omx_adapter/{command_owner,ros_runtime}.py`다.
- 현행 `fleet_robot_reservations`는 `fleet_tasks(task_id)`에 외래키로 묶인다. 별도 Mission 예약 표를 먼저 운영하거나 이 표에 임의 Mission ID를 넣지 않는다. 기존 navigation API·작업 ID·history·D-316 결과 상관관계를 보존한다.
- 현재 `/api/fleet/estop`은 D-276의 명령 전 audit 쓰기가 실패하면 CORE 호출 전에 `503`이다. `console.estop_all()`의 HTTP 응답 수는 물리 정지 증거가 아니다. 전용 정지 경로 이외의 mutation audit 실패 규칙은 유지한다.
- `POLICY_DISPATCH_ENABLED=False`, OMX disabled, Mission/OMX 물리 capability HOLD를 유지한다. SOURCE/LOCAL 테스트와 ROS-SIM, ARTIFACT, DEVICE, FIELD를 별도 기록한다. 정량 stop 시간과 gripper 하중 기준은 실측·위험평가 없이 임의로 정하지 않는다.

## 작업 0. 기준선과 발행 경로 목록

**Files:** Review `src/site/fleet/fleet/server/{app,console,task_store,task_scheduler,task_service}.py`, `src/site/fleet/test/{test_task_api,test_task_store,test_task_scheduler,test_site_users}.py`, `docs/adr/{D-276,D-298,D-308,D-316,D-330}*.md`; create dated evidence only when an actual run exists under `docs/validation/`.

1. `git status --short`, `git log -1 --oneline`으로 기준 HEAD와 기존 수정 경로를 기록한다. `python -m pytest src/site/fleet/test/test_task_store.py src/site/fleet/test/test_task_scheduler.py src/site/fleet/test/test_task_api.py -q`를 실행하고 실패가 있으면 이후 변경과 분리한다.
2. `/api/fleet/robots/{robot_id}/goal`, `/api/fleet/do`, `/api/fleet/robots/{robot_id}/cancel`, `/api/fleet/estop`, background `_task_dispatch_loop`, CORE 직접 명령, OMX 로컬 submitter를 발행/정지 표로 그린다. 각각의 principal, 저장소, queue, reservation, device lease, 최종 writer를 적고 불명 경로는 HOLD로 둔다.
3. **Exit:** 어느 경로가 현재 `cancel_pending_task_queue()`를 거치고 어느 경로가 장치 로컬 최종 writer를 우회할 수 있는지 코드 위치로 설명할 수 있다. 이 표가 없으면 공통 claim 구현을 시작하지 않는다.

## 작업 1. 기존 task를 보존하는 단일 Fleet claim

**Files:** Modify `src/site/fleet/fleet/server/{task_store,task_scheduler}.py`; create `src/site/fleet/fleet/server/dispatch_admission.py`, `src/site/fleet/test/test_dispatch_admission.py`; extend `src/site/fleet/test/{test_task_store,test_task_scheduler}.py`.

1. **실패 시험:** 기존 DB의 `fleet_robot_reservations`를 가진 task를 연 뒤 새 스키마로 재시작해 같은 robot claim을 보존한다. 두 worker의 동시 claim 중 하나만 성공하고, Mission 후보와 기존 task 후보가 같은 robot/resource를 동시에 잡지 못해야 한다. `UNKNOWN` attempt와 발행 후 ACK 누락은 lease 만료만으로 자원을 풀지 않는다.
2. 기존 `fleet_robot_reservations`를 소유자 종류·ID·generation을 명시한 공통 claim으로 한 트랜잭션 안에서 이관한다. `fleet_tasks` FK에 묶인 현행 task ID와 history는 유지한다. 새 Mission 소유자도 **같은 SQLite 연결/트랜잭션과 동일 UNIQUE resource key**를 사용하게 할 자리를 만든다. 장치·공유 구역 자원의 canonical identity와 예약 해제 조건을 별도 typed 함수로 둔다.
3. `FleetTaskScheduler.claim_next()`를 공통 admission에 연결하고 기존 navigation 동작을 회귀 시험한다. claim 저장 실패/중복은 dispatch 금지, 이미 발행된 Action 결과 불명은 조정 대기다. SOURCE 코드에만 이 단계의 새 스키마를 두고 Mission dispatch는 열지 않는다.
4. 실행: `python -m pytest src/site/fleet/test/test_dispatch_admission.py src/site/fleet/test/test_task_store.py src/site/fleet/test/test_task_scheduler.py -q`; 기대: 신규 경합 반례와 기존 task 시험 통과. 해당 파일만 커밋한다.

## 작업 2. stop generation, 시작 차단, 명시적 재허가

**Files:** Modify `src/site/fleet/fleet/server/{task_store,task_service,task_scheduler,app}.py`; create `src/site/fleet/test/test_dispatch_stop_latch.py`; update `src/site/fleet/test/{test_task_service,test_task_api}.py`.

1. **실패 시험:** READY/QUEUED task와 미래 Mission Step이 있는 동안 stop generation을 올리면 새 claim이 없고, 진행 중 attempt는 자동 성공/실패로 바뀌지 않아야 한다. claim 뒤 송신 전 stop 경합, stop 직후의 늦은 ACK, 프로세스 재시작, lease 만료, DB 읽기 오류 뒤에도 대기 Step이 자동 발행되면 실패다.
2. Fleet 저장소에 단조 증가 stop generation과 dispatch permit을 기록한다. stop/claim 판정은 가능한 경우 같은 저장소 트랜잭션에서 한다. DB 상태가 불명/불가이면 dispatch를 닫는다. 프로세스 시작은 발행 금지로 두고 원장·장치 상태 조정과 operator의 명시적 재허가 없이는 worker가 일을 꺼내지 않게 한다. 재허가는 이전 generation을 덮어쓰지 않고 새 세대로 기록한다.
3. 정지 래치는 queued 작업의 발행 가능성을 막는 것이며, 이미 발행된 Action의 최종 결과·물리 정지를 가정하지 않는다. 네트워크 송신 직전 generation을 재확인하고, 장치 로컬 래치가 뒤늦은 요청을 거절하는 반례도 별도로 시험한다. `UNKNOWN`의 자원은 최종 결과/물체 상태 조정 전 유지한다. 기존 task와 신규 Mission이 같은 stop generation을 소비하도록 인터페이스를 만든다.
4. 실행: `python -m pytest src/site/fleet/test/test_dispatch_stop_latch.py src/site/fleet/test/test_task_service.py src/site/fleet/test/test_task_api.py -q`; 기대: 정지/재시작 반례와 navigation 회귀 통과. rearm의 실제 REST 경로가 필요해지는 커밋에는 API Reference·schema·양쪽 시험을 D-18에 따라 함께 넣는다.

**배포 조건:** 기본 발행 금지와 rearm 경로는 같은 활성화 단위로 배포한다. 기존 navigation task가 재시작 뒤 대기하게 되는 운영 변화를 콘솔에 표시하고, operator 재허가가 없으면 자동 dispatch가 재개되지 않도록 검증한다.

## 작업 3. 인증된 사이트 정지를 감사 DB 장애와 분리

**Files:** Modify `src/site/fleet/fleet/server/{app,site_users,console}.py` only as needed; create `src/site/fleet/test/test_site_stop_availability.py`; modify `src/site/fleet/test/{test_site_users,test_task_api}.py`; update `docs/reference/ROSY API & Protocol Reference.md` and `src/contracts/foundation/core_common/protocol/schemas.py` only when the wire response changes.

1. **실패 시험:** `begin_api_audit()`가 예외를 내도 인증된 operator의 전용 `/api/fleet/estop`은 발행을 먼저 차단하고 등록 장치에 정지 요청을 보낸다. viewer, policy-admin, 무자격 요청은 보내지 않는다. 일반 goal/do/rearm은 audit 실패 시 계속 거절한다. 한 장치 timeout과 한 장치 응답은 섞어 `stopped=all`로 표시하지 않는다.
2. 요청자 인증/role 검사와 D-276의 mutation pre-audit를 분리한다. 전용 stop은 audit 쓰기를 시도하되 실패가 fanout을 막지 않게 한다. audit 열화·대상별 전송/응답 불명을 서버 로그와 응답/후속 조정에 남긴다. 저장소 장애 때는 프로세스 내 dispatch를 즉시 막고, 재시작은 작업 2의 기본 금지 상태를 적용한다. 감사 내구성과 정지 가용성을 같은 성공으로 표시하지 않는다.
3. 기존 `do`의 순차 `steps`나 일반 cancel을 긴급 경로로 재정의하지 않는다. CORE 호출 실패·Fleet 네트워크 단절 시 최종 상태는 불명으로 보고 로컬 정지 경로를 따로 시험한다. 응답 필드가 바뀌면 API Reference·schema·생산자/소비자 시험을 한 커밋으로 묶는다.
4. 실행: `python -m pytest src/site/fleet/test/test_site_stop_availability.py src/site/fleet/test/test_site_users.py src/site/fleet/test/test_task_api.py -q`; 기대: audit 장애 중 stop 전송, 다른 mutation 거절, 권한 거절이 각각 검증됨.

## 작업 4. OMX Action의 발행 전 기록과 장애 조정

**Dependency:** [기존 계획](2026-09-29-er2-semantic-actions-mission-implementation.md)의 작업 0~3에서 실제 장치·driver·host/API 위치를 결정한 뒤 실행한다. 하드웨어 정보가 없으면 fake port 계약까지만 작성하고 장치 발행을 HOLD한다.

**Files:** Modify planned `src/products/omx/adapter/omx_adapter/{action_store,pick_place_transaction,command_owner,ros_runtime}.py` when present; create `src/products/omx/adapter/test/test_omx_action_crash_recovery.py`; update relevant adapter tests.

1. **실패 시험:** 영속 PREPARED 기록 전에는 ROS goal 전송이 없어야 한다. 전송 직후 goal ID 저장 전 프로세스를 죽이면 재시작 시 같은 `request_key`가 두 번째 goal을 보내지 않아야 한다. driver가 goal 조회나 이전 owner fencing을 지원하지 않으면 `UNKNOWN`/HOLD로 남아야 한다. 늦은 결과와 물체 보유 불명은 새 attempt의 성공 조건이 아니다.
2. 한 `action_id`/`attempt_id`/request digest/owner generation을 원장과 ROS/driver 요청에 연결한다. 장치가 제공하는 goal ID 조회·fencing 수단을 확인하고 가능한 경우 조정한다. 불가능하면 자동 재시도·자동 놓기·자동 재파지를 금지하고 운영자 복구로 보낸다. cancel ACK와 관절/그리퍼/하중 readback은 따로 기록한다.
3. `python -m pytest src/products/omx/adapter/test/test_omx_action_crash_recovery.py src/products/omx/adapter/test/test_omx_command_owner.py -q`와 제품별 ROS-SIM 시험을 분리 실행한다. **Exit:** fake driver에서는 중복 물리 발행이 없고, 실제 driver 증거 부재는 DEVICE HOLD로 남는다.

## 작업 5. Mission·직접 조작을 같은 발행 경계에 연결

**Dependency:** 기존 계획의 Mission/Step 원장과 장치 Action 결과 연결이 먼저 있어야 한다. 이 작업은 기존 계획 작업 4~5의 통합 게이트다.

**Files:** Modify planned `src/site/fleet/fleet/server/{mission_store,mission_service}.py`, existing `src/site/fleet/fleet/server/{app,console,task_scheduler}.py`; create `src/site/fleet/test/test_mission_dispatch_admission.py`, `src/site/fleet/test/test_mission_stop_recovery.py`.

1. **실패 시험:** 같은 Pinky를 향한 navigation task·Mission Step·직접 goal의 경합, OMX Action과 다른 작업의 같은 workcell/물체 경합, 공유 구역의 병렬 Step, 사이트 stop 중 새 Mission 제출과 해제 후 재발행을 시험한다. 직접 조작의 로컬 lease를 검증할 수 없는 장치에서는 Mission+직접 혼합을 거절한다.
2. Mission Step도 작업 1의 공통 claim과 작업 2의 stop generation을 사용한다. Fleet DB의 원자성은 장치 lease의 원자성을 대신하지 않으므로 CORE/OMX가 action/attempt/owner generation을 재검사한다. 세대 전달·장치 보존·기한/거절 규칙을 실제 장치 소비자와 함께 D-18 API Reference·schema·시험에서 정한다. 지연된 goal이 stop보다 늦게 도착하는 순서와 연결 단절 뒤 낡은 허가의 재사용을 거절해야 한다. stop/cancel은 queued Step을 억제하고 실행 중 Step의 로컬 결과/정지 readback을 조정한다. 성공 predicate는 Action ACK가 아닌 D-328의 독립 증거로 판정한다.
3. `python -m pytest src/site/fleet/test/test_mission_dispatch_admission.py src/site/fleet/test/test_mission_stop_recovery.py src/site/fleet/test/test_task_scheduler.py src/site/fleet/test/test_task_api.py -q`를 실행한다. **Exit:** 동일 자원 이중 발행, stop 뒤 재발행, 직접 조작 우회가 SOURCE/LOCAL에서 막힘을 보인다. 그 전까지 Mission dispatch capability를 disabled로 둔다.

## 작업 6. 시뮬레이션·설치·실물 출구

**Files:** Add focused fixtures under `src/sim/isaac_sim/` only after D-322의 실제 실행 환경 확인; update relevant `docs/validation/<topic-YYYY-MM-DD>/`, Fleet/OMX progress/logs and deployment records as evidence arises.

1. ROS-SIM에서 두 scheduler worker의 claim 경합, stop generation과 late ACK, Fleet restart, 감사 DB 장애, 네트워크 단절, driver 접수 후 crash, 물체 보유 불명, 직접 조작을 주입한다. 관측 oracle과 원시 이벤트 시각을 남기고 물리 정지로 표기하지 않는다.
2. ARTIFACT에서 실제 Fleet/CORE/OMX 설치 closure·서명/digest·설정 세대·단일 writer를 확인한다. DEVICE/FIELD에서 operator와 독립 정지 수단을 준비한 감독 세션으로 사이트 요청 도달률, CORE 래치, driver/관절/그리퍼·물체 readback, 측정된 정지와 재개 조건을 구분해 판정한다.
3. 어느 층에서든 감사 DB나 네트워크가 끊겨도 원격 정지가 항상 도달한다는 주장은 실측 전 금지한다. 실패하면 발행 capability를 disabled/HOLD로 되돌리고 진행 중 Action의 로컬 최종 결과와 물리 상태를 확인한다.

## 완료 판정과 선행 관계

- 이 문서의 완료는 코드/시험/장치 각 게이트의 실제 증거로만 선언한다. 문서 커밋은 D-330 구조 결정의 기록이며 기존 사이트 stop 가용성이나 OMX 기능 완성이 아니다.
- 작업 1~3은 신규 Mission 발행 활성화 **전** 완료해야 한다. 작업 4는 OMX 원격 Action 활성화 **전**, 작업 5는 다장치/병렬 Mission 활성화 **전** 완료해야 한다. D-326의 정책 자동 재발의 밸브는 이 계획으로 열리지 않는다.
- 스키마 이관과 기본 발행 금지는 한 번에 되돌릴 수 있는 코드 스위치로 취급하지 않는다. 업그레이드 전 기존 SQLite의 보존 사본과 버전, migration/역방향 읽기 시험을 남긴다. 롤백 중에도 stop generation·미확인 attempt·물리 상태가 조정되기 전에는 이전 binary의 자동 dispatch를 금지한다.
- 문서 변경 검증: `python -m pytest test/test_network_topology_contracts.py test/test_harness_contracts.py -q`; `python tools/harness/rosy_harness.py lint`. 코드 변경 검증은 작업별 focused test 뒤 기존 Fleet/CORE/OMX 회귀를 중복 basename 충돌 없이 별도 invocation으로 실행한다.

## Execution record (2026-09-29)

Implementation is being delivered in the isolated `feat/fleet-mission-control` worktree. This record distinguishes source behavior from physical/device acceptance.

| Work item | Result | Evidence / remaining gate |
|---|---|---|
| 0. Baseline and route inventory | Complete | `docs/validation/fleet-action-admission-2026-09-29/result.md` and `docs/validation/er2-omx-action-baseline-2026-09-29/README.md`; no device command was issued. |
| 1. Shared Fleet claims | Complete | Task scheduling and future `mission` / `direct_action` reservations share typed durable claims; callers cannot forge unresolved phases. |
| 2. Stop generation and explicit rearm | Complete for Fleet admission | Startup is closed; explicit rearm advances generation; stop prevents queued work from starting; operator status/action is exposed. Device-side generation consumption and independent physical stop remain unimplemented. |
| 3. Site stop/audit failure boundary | Complete for source behavior | Dedicated stop fanout remains best-effort across audit failure; ordinary mutation remains fail-closed. HTTP response is not physical stop proof. |
| 4. OMX Action attempt ledger | Complete as local durable ledger | Canonical request identity, attempt states, restart-to-UNKNOWN, no replay. Not wired to a physical driver/API. OMX profile remains disabled. |
| 5. Mission and direct-action boundary | Partial, dispatch disabled | Internal single-step `PICK_PLACE` proposal/admission/result/goal-evidence ledger uses the shared SQLite transaction and claims. Action SUCCEEDED is separate from goal confirmation; independent camera evidence is freshness-checked. No REST endpoint, scheduler executor, or ROS/device submission was added. |
| 6. Cross-layer simulation and fault injection | Not run | D-322 explicitly holds Isaac ROS-SIM on this Windows host; its required Ubuntu/Jazzy/Isaac 6.1 GPU environment is absent. Do not add Isaac fixtures until that path is actually verified. Existing SOURCE fault tests do not prove site/network/device stop timing. |

Verification on this worktree: Mission focused tests **15 passed**; full Fleet suite **578 passed, 5 skipped**; OMX adapter suite **72 passed, 3 skipped**; network topology and harness contract tests passed. Harness lint reports **0 errors, 18 freshness warnings**. `flake8` could not run because the executable is unavailable in this environment.

**Capability gate:** Fleet task dispatch remains subject to explicit operator rearm. Mission/semantic OMX physical dispatch remains disabled. Source tests do not establish REST contract approval, device-side stop-generation enforcement, independent hardware E-stop, selected device identity, camera/gripper calibration, ROS-SIM acceptance, or DEVICE/FIELD acceptance.

### Follow-up review (2026-09-29)

Review finding: when stop invalidated a pre-dispatch Mission claim, the generic Fleet stop path deleted the `CLAIMED` row but the internal Mission could remain `READY`. Although `start_step` already refused stale generations, the durable Mission status did not explain the refusal. Fixed `start_step` to atomically set `HOLD`, append `STEP_HELD_BEFORE_SUBMISSION`, and release any remaining Mission claims when the stop generation or resource claim is stale. A regression test failed before the fix and passes after it. Full Fleet suite rerun: **578 passed, 5 skipped**.

Integration finding: current main added a generation-checked dispatch-rearm confirmation, but its pinned native-dialog contract still allowed only two Fleet confirms. Kept the explicit confirmation and updated the contract to three; the web dialog contract now passes.

Integrated-main checks: Fleet **578 passed, 5 skipped**; OMX adapter **72 passed, 3 skipped**; HMI dashboard **14 passed, 32 skipped**; HMI web/dialog/Fleet browser suite **90 passed, 31 skipped**; network topology and harness contracts passed; harness lint **0 errors, 18 freshness warnings**. Browser-dependent skipped tests remain unaccepted.

Remote deployment is not yet evidenced. From clean merged source commit `3e2bf04652600d524d244929a4da95371e6dcc99`, an unsigned site candidate was built at `X:\DevTemp\rosy-site-candidate-3e2bf046`; archive, three image IDs/platforms, and all SBOM hashes were checked. An isolated Docker Desktop smoke started Fleet, Vision, and Caddy as healthy and returned HTTP 200 from local `/healthz`, then stopped the services. This local site-container run does not satisfy item 6 ROS-SIM.

Production activation remains HOLD: the site release procedure says the production signing key ID/public key are not selected or provisioned, and this checkout has no approved site host/TLS identity or operator configuration. The candidate is unsigned and was not transferred or activated. Mission/OMX actuator dispatch remains disabled.
