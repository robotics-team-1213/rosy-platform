# 사이트 Fleet 작업 스케줄링 구현 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fleet이 수동 목표 요청을 영속적으로 대기·배정·추적하고, 독립 worker 분리가 필요하다는 증거가 생길 때만 RabbitMQ를 사이트 내부 전달 계층으로 도입한다.

**Architecture:** SQLite `FleetTaskStore`가 작업과 이력의 권위 있는 원장이고 Fleet 스케줄러가 우선순위·로봇/자원 점유를 계산한다. CORE 명령은 기존 REST, 결과 관측은 기존 WSS 계약을 사용한다. 선택적 RabbitMQ는 outbox 뒤의 worker 전달만 맡는다.

**Tech Stack:** Python 3.12, FastAPI, SQLite WAL, pytest, Docker Compose, 기존 CORE REST/WSS; RabbitMQ는 후속 조건부 단계.

---

## 기준선, 범위, 착수 조건

- 근거: [D-271](../adr/D-271-site-fleet-task-scheduling-and-broker.md), [상세 설계](2026-09-26-site-task-scheduling-and-broker-design.md), D-12/D-59/D-170/D-177/D-267/D-268/D-269, [API Ref §10.8](../reference/ROSY%20API%20%26%20Protocol%20Reference.md), [Ubuntu 현장 계획](2026-09-26-ubuntu-site-fleet-vision-workflow.md).
- 현재 `FleetTaskService.submit_navigation()`은 저장 직후 CORE REST를 호출한다. `FleetConsole.goal()`은 경로 충돌 시 자체 메모리 `_queued`를 쓸 수 있고, 그때 반환하는 `accepted: true, queued: true`를 task service는 `ACCEPTED`로 저장한다. `_run_traffic()`은 대기 목표를 재발행하지만 task ID를 받지 않는다. 이 불일치를 먼저 재현한다.
- 초기 구현 대상은 **구조화된 수동 navigation**이다. `source=policy`는 D-268이 Proposed인 동안 항상 `HOLD`; 새 물체 이동/집기 verb, 팔/Pinky 카메라, 자연어 직접 실행, CORE 최종 결과 단정은 대상이 아니다. `COMPLETED`는 D-170/D-177 활성화와 검증된 결과 연결 후에만 사용한다.
- 코드는 새 전용 worktree에서 시작한다. 실행 시 `main`, D-271 브랜치, 다른 세션의 변경 경로를 다시 확인하고, D-271을 안전하게 통합한 커밋을 기준으로 한다. 현재 `main`의 `docs/index.md`·`docs/logs.md` 및 Fleet 파일은 다른 작업의 WIP이므로 명시 경로만 stage하고 덮어쓰지 않는다.
- 각 task는 실패하는 시험 → 최소 구현 → 같은 시험 통과 → 해당 범위 회귀 → 명시 경로 commit 순서다. 로컬 합성 시험을 DEVICE/FIELD 증거로 승격하지 않는다.

## 작업 0: 상태·우선순위·권한 계약 고정

**Files:** Modify `docs/reference/ROSY API & Protocol Reference.md`, `src/contracts/foundation/core_common/protocol/schemas.py`, `src/site/fleet/test/test_task_contract_docs.py`, `src/site/fleet/test/test_task_api.py`; review `docs/adr/D-170-prt-004-deferred-until-central-fleet.md`, `docs/adr/D-177-prt-004-activation-design.md`, `docs/adr/D-268-policy-eligible-vision-evidence-for-fleet-tasks.md`.

1. 기존 `/api/fleet/robots/{robot_id}/goal`, `/api/fleet/do`, `/api/fleet/tasks/{task_id}` 응답과 `accepted` 의미의 계약 시험을 추가한다. `accepted: true`는 CORE receipt일 때만 참이며 **대기열 접수/완료와 다름**을 확인한다.
2. 공개 task 상태에 `QUEUED`를 추가하고 `REQUESTED → QUEUED → ACCEPTED|UNKNOWN|FAILED|HOLD`, `QUEUED → CANCELED|EXPIRED`의 의미를 API Ref와 공유 schema에 함께 기록한다. 대기 작업 취소는 `POST /api/fleet/tasks/{task_id}/cancel`을 제안하고, **발행 전 작업만** 취소하는 계약을 먼저 고정한다. 발행 후 로봇 cancel은 기존 CORE 경로의 별도 동작이다. 내부 예약/lease는 공개 상태로 추가하지 않는다. 기존 고객이 인식하지 못할 enum 확대이므로 API Ref의 호환성/버전 규칙에 맞춰 additive 범위를 검토하고 계약 시험으로 고정한다. `COMPLETED`는 아직 실제 결과와 묶지 않는다.
3. 우선순위는 서버 내부의 `operator > accepted-policy > background`로 고정한다. 외부 요청의 임의 `priority` 필드는 거절하고, 현재 공유 토큰의 actor는 `site-console`로 기록한다. 사용자별 RBAC가 필요한 현장 공개는 D-267의 별도 인증 게이트를 선행한다.
4. `python -m pytest src/site/fleet/test/test_task_contract_docs.py src/site/fleet/test/test_task_api.py -q`로 실패와 통과를 확인하고 계약 파일만 commit한다. PRT Envelope 또는 CORE REST 경로를 새로 바꾸지 않는다.

**Gate:** API Ref·schema·시험이 일치하지 않으면 저장소 migration이나 웹 변경을 시작하지 않는다.

## 작업 1: SQLite 영속 대기열과 원자 점유

**Files:** Modify `src/site/fleet/fleet/server/task_store.py`, `src/site/fleet/test/test_task_store.py`; create `src/site/fleet/fleet/server/task_scheduler.py`, `src/site/fleet/test/test_task_scheduler.py`.

1. 임시 SQLite DB와 가짜 시계로 `(priority_class, created_at, task_id)` 정렬, 동일 로봇 중복 예약 차단, 만료/취소/재시작 동작의 실패 시험을 쓴다. 스케줄러는 monotonic 시간으로 대기 길이를 측정하고 DB에는 UTC 시각을 기록한다.
2. 기존 DB를 유지한 채 idempotent migration으로 큐 메타데이터(등급, 만료, 예약 대상/lease, dispatch phase)와 명령 시도 ID/순번을 추가한다. 작업 생성과 이력 추가, 적격 작업 선택과 자원 예약을 각각 한 SQLite transaction으로 처리한다. SQLite `BEGIN IMMEDIATE` 경합 시 중복 claim이 발생하지 않게 한다.
3. 프로세스가 **명령 발행 전** 죽은 것을 증명할 수 있는 행만 안전하게 다시 대기시키고, 발행 시작 또는 여부 불명 행은 `UNKNOWN`으로 보존한다. 기존 `recover_interrupted_requests()`가 모든 `REQUESTED`를 `UNKNOWN`으로 옮기는 동작은 새 단계 정보를 기준으로 확장하며, 기존 DB의 불명확한 행은 자동 재발행하지 않는다.
4. `python -m pytest src/site/fleet/test/test_task_store.py src/site/fleet/test/test_task_scheduler.py -q`로 확인하고 store/scheduler/시험만 commit한다.

**Gate:** 같은 DB를 보는 동시 dispatcher 두 개가 한 task 또는 한 로봇 자원을 동시에 claim하지 않아야 한다.

## 작업 2: 작업 접수와 단일 dispatcher

**Files:** Modify `src/site/fleet/fleet/server/task_service.py`, `src/site/fleet/fleet/server/app.py`, `src/site/fleet/fleet/cli.py`, `src/site/fleet/test/test_task_service.py`, `src/site/fleet/test/test_task_api.py`.

1. 수동 요청은 먼저 `QUEUED` task ID를 돌려주고, idle robot만 dispatcher가 한 번 호출하는 실패 시험을 쓴다. 같은 actor/key 재전송은 동일 task를 반환하며 새 worker를 깨워도 두 번째 CORE 명령은 없어야 한다. `policy` 요청은 같은 검증기를 통과하되 계속 `HOLD`다.
2. `FleetTaskService`를 접수와 실행으로 분리한다. `create_app()` 수명주기에 단일 dispatcher를 연결하고 `--tasks-db`가 없는 로컬 구성의 기존 경로는 명시적 호환 경로로 유지한다. 외부 공개 구성에서는 task DB와 인증이 없으면 기동을 거부한다.
3. 명시적 거절은 `FAILED`, HTTP 5xx/timeout/프로세스 중단처럼 발행 여부가 모호하면 `UNKNOWN`이다. 메시지 전달 실패와 CORE의 작업 완료는 별개다. task가 대기할 때 API 최상위 `accepted`는 false 또는 별도의 `queued` 표기를 사용하되 작업 접수 성공은 task ID로 표현한다(작업 0의 계약을 따른다).
4. `python -m pytest src/site/fleet/test/test_task_service.py src/site/fleet/test/test_task_api.py src/site/fleet/test/test_cli.py -q`로 검증하고 관련 코드·시험만 commit한다.

**Gate:** 작업을 기록하지 못하면 CORE에 명령을 보내지 않고, 기록 성공 직후 재시작해도 자동 중복 발행이 없다.

## 작업 3: 교통 대기열을 작업 ID와 연결

**Files:** Modify `src/site/fleet/fleet/server/console.py`, `src/site/fleet/fleet/server/task_service.py`, `src/site/fleet/fleet/server/task_scheduler.py`, `src/site/fleet/test/test_server_traffic.py`, `src/site/fleet/test/test_server_priority.py`, `src/site/fleet/test/test_task_service.py`.

1. 현재 `console.goal()`이 `queued: true`를 반환한 뒤 task 상태가 `ACCEPTED`가 되는 사례를 실패 시험으로 재현한다. `_run_traffic()`이 해제한 목표가 task 이력 없이 CORE에 내려가는 사례도 잡는다.
2. 경로 충돌 계산과 양보 순서는 보존하면서, 대기 목표에 task ID를 결합한다. 교통 대기 생성·해제·재배정·취소는 task scheduler/store의 상태 전이를 호출한다. 기존 console 메모리 `_queued`는 표시용 투영 또는 단기 계산 캐시로만 남긴다.
3. CORE에 목표를 먼저 보내 경로를 얻은 뒤 취소하는 기존 알고리즘의 레이스를 시험한다. 확정된 취소 후 재발행은 같은 task의 **서로 다른 명령 시도**로 기록한다. 취소 receipt가 모호하면 안전하게 `UNKNOWN`으로 보존하고 재발행하지 않는다. 실행 중 로봇을 높은 등급의 새 메시지만으로 선점하지 않는다.
4. `python -m pytest src/site/fleet/test/test_server_traffic.py src/site/fleet/test/test_server_priority.py src/site/fleet/test/test_task_service.py -q`와 Fleet 전체 `python -m pytest src/site/fleet/test/ -q`를 확인하고 관련 경로만 commit한다.

**Gate:** 재시작 뒤 대기 표시와 영속 task 상태가 일치한다. 한 명령 시도에는 CORE goal 호출이 최대 한 번이며, 확정 취소 없이 같은 task의 다음 시도를 만들지 않는다.

## 작업 4: 만료·취소·정지와 공정성

**Files:** Modify `src/site/fleet/fleet/server/task_scheduler.py`, `src/site/fleet/fleet/server/app.py`, `src/site/fleet/fleet/server/console.py`, `src/site/fleet/test/test_task_scheduler.py`, `src/site/fleet/test/test_task_api.py`, `src/site/fleet/test/test_server_app.py`.

1. 만료된 대기 작업이 발행되지 않음, 취소된 작업의 자원 해제, offline/busy의 명확한 대기 사유, 높은 등급 작업의 순서, 낮은 등급 기아 관찰을 가짜 시계 시험으로 쓴다. 대기 상한/aging 또는 할당량의 숫자는 실제 작업 시간·부하 측정값으로 별도 수용하기 전까지 설정 값으로만 둔다.
2. `stop`/`cancel` 요청을 일반 대기 작업 dispatcher와 분리하고, 해당 로봇의 **아직 발행하지 않은** 대기 작업을 취소/보류한다. CORE의 e-stop과 로컬 안전 경로를 바꾸지 않는다. 네트워크 실패를 즉시 정지 성공으로 표기하지 않는다.
3. `python -m pytest src/site/fleet/test/test_task_scheduler.py src/site/fleet/test/test_task_api.py src/site/fleet/test/test_server_app.py -q`로 검증하고 commit한다.

**Gate:** 일반 큐가 막혀 있어도 stop/cancel 코드 경로가 큐 소비를 기다리지 않으며, 로봇 측 안전 우선순위가 유지된다.

## 작업 5: 관제 표시와 운영 관측

**Files:** Modify `src/site/fleet/fleet/server/web/console.js`, `src/site/fleet/fleet/server/web/index.html`, `src/site/fleet/fleet/server/web/styles.css`, `src/site/fleet/fleet/server/app.py`, `test/test_fleet_console_browser.py`, `src/site/fleet/test/test_task_api.py`.

1. `QUEUED`를 오류/완료로 표시하지 않고 task ID, 순서/대기 사유, 취소 가능 여부, `UNKNOWN`의 수동 확인 필요를 보여 주는 실패 브라우저 시험을 쓴다. 기존 `console.js`의 `task.status !== "ACCEPTED"` 오류 처리 분기를 포함한다.
2. 인증된 task readback에만 queue 상태·사유·이력을 노출한다. 통계는 대기 수/age, claim 실패, `UNKNOWN`, 만료, dispatch receipt를 구분하고 원본 영상/토큰/요청 본문을 로그에 남기지 않는다. `COMPLETED`는 CORE final-result 연계 전 표시하지 않는다.
3. `python -m pytest src/site/fleet/test/test_task_api.py -q`와 기존 브라우저 harness 조건에 맞는 `test/test_fleet_console_browser.py` 목표 시나리오를 실행한다. 브라우저 실행 환경이 없으면 LOCAL UI 수용을 HOLD로 남기고 API 시험으로 대체하지 않는다. 검증 뒤 commit한다.

## 작업 6: SQLite 단계의 Docker 통합과 도입 판단

**Files:** Modify `deploy/site/README.md`, `docs/plans/2026-09-26-site-task-scheduling-and-broker-design.md`; create `test/test_site_task_queue_deploy.py`; use existing `deploy/site/compose.yaml` without RabbitMQ service.

1. Compose 설정 시험에서 task DB가 영속 volume에 있고 Fleet만 CORE REST 자격을 가지며 로봇/폰에 브로커 URL이 없음을 고정한다. Docker LOCAL에서 합성 CORE를 붙여 2건의 우선순위 작업, traffic wait→release, Fleet 재시작, 동일 key 재시도, timeout→`UNKNOWN`, stop 우회를 검증한다.
2. 접수→dispatch 지연 분포, SQLite lock 대기, queue depth/age, GPU worker 대기와 worker 재시작 시간을 측정한다. 운영자가 작업별 허용 지연·기아 상한을 시험 전에 기록하고, 측정과 복구 절차로 SQLite 단계가 충분한지 판정한다. 고정 숫자를 근거 없이 ADR에 추가하지 않는다.
3. `python -m pytest test/test_site_task_queue_deploy.py src/site/fleet/test/ -q`, `docker compose -f deploy/site/compose.yaml config --quiet`, 컨테이너 재시작/readback, `git diff --check`를 실행한다. Docker Desktop LOCAL 성공을 Ubuntu 호스트·GPU·실물 CORE 수용으로 표시하지 않는다. 결과와 운영 runbook을 commit한다.

**Gate A:** 단일 Fleet/worker가 지연·복구 기준을 만족하면 RabbitMQ 도입을 보류하고 SQLite 구성을 배포 후보로 만든다. 독립 worker의 실제 장애 전파·처리량·큐 관리 요구가 확인되면 작업 7로 간다.

## 작업 7: Gate A가 RabbitMQ를 요구할 때만 내부 브로커 추가

**Files:** Modify `deploy/site/compose.yaml`, `deploy/site/.env.example`, `deploy/site/README.md`, `deploy/site/requirements-fleet.txt`, `src/site/fleet/fleet/server/task_store.py`, `src/site/fleet/fleet/server/task_scheduler.py`, `src/site/fleet/fleet/server/app.py`, `src/site/fleet/fleet/cli.py`; create `src/site/fleet/fleet/server/task_broker.py`, `src/site/fleet/test/test_task_broker.py`, `test/test_site_task_broker_deploy.py`.

1. pinned RabbitMQ 이미지/라이브러리와 사이트 내부 전용 계정·volume·healthcheck·백업/복원 정책을 설계한다. 포트는 외부에 공개하지 않고 CORE/폰/브라우저는 기존 REST/WSS를 유지한다. 큐를 장비/자원별로 분리하며 `prefetch`, TTL, 최대 길이, 실패 보관, 우선순위 등급을 시험 벡터로 고정한다.
2. 작업 상태+outbox 행을 한 SQLite transaction에 쓰는 실패 시험을 만든다. publisher confirm 이전 crash, confirm 유실 후 중복 발행, worker ACK 이전 crash, 이미 CORE에 명령을 보냈을 가능성이 있는 redelivery를 각각 시험한다.
3. 브로커 실행 알림에는 `schema_version`, `message_id`, `task_id`, `attempt_id`, `expires_at`만 전달하고 worker가 원장의 최신 작업/예약을 검증한다. 같은 사이트 호스트 안의 worker는 Fleet 서비스가 DB를 읽도록 하고, 다른 PC의 worker가 필요하면 별도 인증된 Fleet 내부 작업 조회/claim API를 API Ref·schema·권한 시험과 함께 추가한다. SQLite 파일을 네트워크 공유하지 않는다. 안전한 기록/인수 이후 ACK하며, 물리 명령 발행 여부가 불명확하면 `UNKNOWN`으로 두고 자동 재하달하지 않는다. 교환·큐의 ACK를 CORE 완료로 번역하지 않는다. 원격 RTX 영상 worker의 원본 영상 전달은 별도 media 계약 전까지 이 단계에 포함하지 않는다.
4. `python -m pytest src/site/fleet/test/test_task_broker.py test/test_site_task_broker_deploy.py -q`와 Docker 브로커/worker 장애 주입, 전원 복귀 readback을 수행한다. 특정 RabbitMQ 버전의 우선순위·quorum 동작은 실제 pinned 버전으로 확인한다. 운영 복구와 broker 장애 알림까지 검증한 뒤 단독 commit한다.

**Gate B:** RabbitMQ LOCAL의 publish/consumer 안전성은 SITE/DEVICE 수용과 별개다. 단일 현장 PC의 quorum queue를 HA로 표기하지 않는다.

## 작업 8: 계약 추적·장비 수용·통합

**Files:** Modify `docs/reference/ROSY API & Protocol Reference.md`, `deploy/site/README.md`, `docs/progress.md`, `docs/logs.md`; generate `docs/index.md`; create dated evidence under `docs/validation/` only when 실제 측정값이 있다.

1. D-170/D-177 중앙 Fleet 시점에 `task_id ↔ correlation_id ↔ CORE ACK/final result`를 같은 변경으로 활성화한다. 해당 변경 전에는 receipt 이후 `RUNNING`/`COMPLETED`를 추정하지 않는다. PRT Envelope과 API Ref/schema는 D-18에 따라 함께 개정한다.
2. 승인된 Ubuntu 호스트에서 pinned 이미지 ID/해시, TLS/자격 증명, 전원 복귀/DB 복원, CORE 접속, 큐 backlog, 원격 stop 실패 표시를 확인한다. 실제 폰·CORE·팔/Pinky는 각 DEVICE/FIELD 절차와 권한을 별도로 요구한다. D-268 수용과 fresh policy evidence 검증 전에는 자동 이동/집기를 계속 `HOLD`한다.
3. 마지막 코드 변경 뒤 `python -m pytest src/site/fleet/test/ test/test_network_topology_contracts.py test/test_harness_contracts.py -q`, `python tools/harness/rosy_harness.py generate`, `python tools/harness/rosy_harness.py lint`, 관련 Docker LOCAL 시험을 재실행한다. 변경 경로와 원격/현장 증거를 대조한 뒤 명시 경로만 commit한다.
4. 로컬 `main` 병합 전 HEAD/ancestry와 경로 겹침을 재확인한다. 다른 세션의 WIP가 겹치면 억지 병합이나 광범위 stash 없이 격리 브랜치를 유지한다. 원격 push/CI·Ubuntu 배포·DEVICE/FIELD 수용은 각각 별도 결과로 보고한다.

## 최종 수용표

| 증거 | 충족 조건 | 현재 기준 |
|---|---|---|
| SOURCE | 상태/권한/우선순위·중복·복구·stop 계약 시험 | D-271 설계만 Accepted; 구현 미시작 |
| LOCAL | SQLite 스케줄러와 Docker 합성 CORE 왕복·재시작·UNKNOWN | 미실행 |
| RabbitMQ LOCAL | Gate A 필요 판정 후 outbox/confirm/ACK·장애 주입 | 조건부, 미도입 |
| SITE | 실제 Ubuntu PC의 복구/로그/백업/TLS/지연 | 미검증 |
| DEVICE/FIELD | 실제 CORE·폰 및 작업별 안전/신선도 | 미검증; 자동 실행 HOLD |

이 계획의 파일 경로는 D-271 전용 worktree의 현재 코드 기준이다. 실행 직전에 최신 `main`과 병합 상태를 확인하고 파일 이동·다른 작업의 변경을 반영한다.
# Implementation checkpoint (2026-09-26)

Tasks 0–6 have been implemented on `feat/site-task-scheduler`. Task 0–5 source,
contract, scheduler, API, traffic-queue, expiry/cancel, queue-position readback,
and console checks are covered by 485 Fleet tests (5 skipped) and 13 Chromium
browser tests. Task 6
passed Compose configuration validation, a Fleet image build, and a local
container/API/SQLite restart smoke test. The full Compose stack and a real CORE
were not exercised; SITE, Ubuntu, DEVICE, and FIELD acceptance remain open.

Gate A found no measured need for a separate worker or broker: the deployment
still has one Fleet dispatcher and one local SQLite writer. Task 7 is therefore
intentionally deferred; RabbitMQ is not added. Task 8's local evidence is in
[`2026-09-26-site-task-scheduler-local.md`](../validation/2026-09-26-site-task-scheduler-local.md).
The branch was integrated into local `main` at `4855b758`. Ubuntu/site deploy,
real CORE, device, GPU, and field acceptance remain open; current unrelated
dirty files in the main worktree were preserved.
