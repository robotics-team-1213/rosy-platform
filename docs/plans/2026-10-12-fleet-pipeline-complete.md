# Fleet 실행 파이프라인 완성 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fleet의 모든 실행 진입점을 기존 실행 소유자에 연결하고, law → 후보 → 실행 직전 승인 → 전달 → 접수/결과 대조 → 종결 또는 이유 있는 미해결 상태를 검증한 뒤 로컬 main에 머지한다.

**Architecture:** Task, Mission/Cell Job, trip, formation, signals, 자동 복구의 기존 상태기계와 원장을 유지한다. 공통 엔진으로 옮기지 않고 실제 누락 지점에서 기존 계약을 집행한다. CORE/Arm의 최종 실행 권한, policy 기본 비활성화, 모델의 advisory 경계를 보존한다.

**Tech Stack:** Python, asyncio, SQLite, 기존 Fleet/CORE 프로토콜, 원격 pytest, repository harness.

## 완료 기준

- 실행 경로 목록마다 입력·law·후보·최종 검사·실행 owner·readback·종결·시험을 연결한다. 멈춤 요청은 후보 판단 실패로 차단하지 않는다.
- 후보 생성 뒤 소유권, 사람 점유, 활성 설정, 사건 또는 증거가 바뀌면 전달하지 않거나 기존 stop fence로 겹친 실행을 중단한다.
- `accepted: false` 또는 불완전한 응답으로 목표·lease·양보 성공을 만들지 않는다. 접수와 물리 완료를 구분한다.
- 모호한 전달 결과는 UNKNOWN/미해결로 유지하고 동일 시도를 자동 재전송하지 않는다. 상관관계가 검증된 최종 결과만 종결한다.
- 원격의 한 실행 owner가 오래 실행되거나 읽히지 않아도 다른 owner의 결과 대조가 굶지 않는다.
- 기존 허용/거절/취소/재시작 시험과 새 경계 시험을 통과하고 신규 실패 0개, 리뷰, 최신 main 통합 검사를 거쳐 머지한다.
- 배포·활성 현장 설정·시뮬레이터·실제 로봇 증거가 없으면 해당 계층을 완료로 표시하지 않는다. 소프트웨어 목표는 SOURCE/원격 검증/로컬 머지까지다.

## 경로 점검 표

| 경로 | 기존 연결 | 우선 점검 |
|---|---|---|
| stuck/stalled/pose_lost | D-674 pipeline, loop, Outcomes/ProblemLog | 앞선 머지의 경계 시험 유지 |
| operator/policy navigation Task | task_service, task_scheduler, task_results, DriveCancelFence | policy 증거/활성 여부를 발행 시점에 재검사 |
| console/intent/lane route/traffic bay | console.goal, GoalLeases, trip_guard | await 이후 trip/formation 소유권 및 명시적 receipt; 양보 상태를 접수 후 기록 |
| Mission/OMX | MissionService, MissionDispatcher, Action/goal evidence 원장 | 안정적 attempt, 재시작 GetAction, 여러 owner의 readback 순서 |
| Cell Job | StepJobDispatcher, step 원장 | submit 한 번, 같은 attempt readback, UNKNOWN 점유 보존 |
| trip/교차로/traffic authority | TripRunner, TrafficService, trip lease, _after_send | 실행 전 소유권과 종료 겹침, 지도 변경, 접수와 도착 구분 |
| formation/relay | FormationSession arm/relay/watch/hold | 재개 전 제약, 부분 무장 롤백, 참조 유실 HOLD |
| signals | SignalConsole, phase/service/watch | 의도·장치 상태·관측 교차 검증; 안전 인터록으로 오인하지 않음 |
| cancel/E-stop/line OFF | 기존 fanout/stop fence | 부분 실패·불명 응답 보존; 물리 정지로 승격하지 않음 |

## Task 1: 발행 전 검사와 receipt 경계

**Files:** `operations/fleet/fleet/server/{task_service,console,goal_lease,trip_guard}.py`; 기존 `operations/fleet/test/{test_task_service_policy_evidence,test_goal_lease,test_server_console,test_trip_runner}.py`.

1. 정책 접수 후 증거 만료/비활성화, 상태 await 중 trip/formation 진입, 거절/불완전 receipt가 목표 또는 lease로 기록되는 회귀를 추가한다.
2. 테스트만 커밋한 뒤 `python tools/remote/remote_pytest.py --log-dir X:/DevTemp/<session>/logs/red -- <해당 시험 경로>`로 RED를 확인한다. `test/known_failures.py`로 새 실패임을 확인한다.
3. 기존 검사/오류/원장을 재사용해 발행 직전 조건을 검사한다. 거절은 기존 contract 오류 또는 명시적 negative acknowledgement로 보존하며 모호한 응답은 UNKNOWN 경로로 보낸다.
4. 구현 커밋 후 같은 원격 시험을 돌려 GREEN을 확인한다.

## Task 2: 모든 owner의 결과 대조

**Files:** `operations/fleet/fleet/server/{mission_dispatcher,mission_service,mission_store,step_dispatcher}.py`; 기존 `operations/fleet/test/{test_mission_dispatcher,test_step_dispatcher}.py`.

1. 여러 workcell의 RUNNING/불명/readback 재시도 상태에서 각 attempt가 실제로 대조되는지 시험한다. 같은 attempt의 submit 횟수는 1이어야 한다.
2. 누락이 재현되면 기존 원장 선택을 가장 작은 방법으로 수정한다. 새 전역 실행기, 결과를 조작하는 timestamp, 미검증 상태의 자원 해제는 추가하지 않는다.
3. 이미 검증된 기능은 새 구현 없이 기존 회귀 결과와 경로 표에 근거를 연결한다.

## Task 3: 계약과 완료 증거

**Files:** `docs/reference/fleet-rulebook.md`, 이 계획, 관련 ADR 및 `docs/reference/ROSY ADR Log.md`, `operations/fleet/logs.md`, `docs/logs.md`, 생성 index 및 필요한 구조 판정.

1. API/프로토콜을 새로 만들지 않는다. 기존 계약 집행을 넘어선 결정이 필요할 때만 ADR 번호를 `tools/harness/adr_reserve.py`로 선점한다.
2. 경로별 실제 연결과 시험을 규칙집에 기록하고 런타임 opt-in 및 현장 검증의 남은 항목을 명시한다.
3. 변경된 소스의 영향 범위를 원격으로 검사하고 모든 로그를 known_failures와 비교한다. 구조 예산을 넘기면 기존 책임 경계로 분리하고 독립 검토한다.
4. 리뷰 후 `python tools/land.py --tests auto`로 최신 main의 통합 검증과 fast-forward 머지를 끝낸다. 푸시/배포/실제 구동은 수행하지 않는다.

## 실행 결과

- D-678로 기존 실행 owner의 최종 승인·receipt·readback 계약을 고정했다. Task policy는 실제 owner 호출 직전에 재검사한다. Console은 단일 로봇의 goal/bay 파이프라인과 follower 무장 경합을 제한하며, stop generation을 queue·교통 후처리까지 유지한다. 늦거나 불명인 bay 응답과 mover stop이 겹치면 보상 취소한다.
- trip 시작 중 정지는 live trip/lease로 전환하지 않는다. formation의 마지막 무장 응답도 STOPPED를 되살리지 않는다. Mission은 모든 RUNNING/불명 owner를 순환 대조하며 동일 attempt를 재전송하지 않는다.
- Cell Job·signals·자동 복구·cancel의 기존 계약과 시험을 통합 규칙집의 경로별 표로 연결했다. 별도 엔진/정책 언어/자동 활성화는 추가하지 않았다.
- 원격 RED에서 admission/receipt, readback, stop, 최종 리뷰의 경합을 재현한 뒤 GREEN으로 검증했다. 최종 source `25c036ae8`의 navigation/traffic/trip/Task policy/formation 회귀는 종료 코드 0, known_failures 신규 0/기존 0이다. 전체 영향 범위·최신 main 통합은 착지 도구의 별도 최종 gate다.
- 증거: 세션 `X:/DevTemp/projects/rosy-platform/2026-10-12--032529--fleet-pipeline-complete--04dc41/`의 원격 로그와 최종 검증 기록. 현장 revision/overlay, 실제 다중 로봇 정지·양보·재시작·도착, 시뮬레이터 및 배포 gate는 이 변경으로 완료되지 않는다.

최종 리뷰 추가 경계: 접수 이후 route/trust cancel의 4xx, observe 중 roster 변경, bay admission 거절은 mover의 확정 실패가 아니다. source `38f51c4c2`의 전체 post-acceptance catch와 원격 158 PASS/NEW 0으로 Task UNKNOWN/점유/단일 전송을 확인했다. 독립 재판정은 Fleet 53355/Console 1325이며 기존 허용량과 분리 의무를 유지한다.

통합 추가: cancel-all 경합 사유와 trip UI label 누락을 영향 gate에서 발견해 수정했다. 보상 cancel 409에서도 Task UNKNOWN/점유를 유지하며 source `5f3f033a8`의 원격 147 PASS/NEW 0으로 확인했다. 일반 전송 오류와 asyncio cancellation은 기존 분류를 유지한다. 최종 착지 검사는 최신 main/HEAD로 다시 실행한다.
