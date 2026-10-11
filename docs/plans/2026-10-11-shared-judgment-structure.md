# Shared Judgment Responsibility Extraction Implementation Plan

후속 통합 순서와 책임·권한 계약은 [D-656 실행 계획](2026-10-11-responsibility-authority-orchestration.md)을 따른다. 이 문서의 단계별 source/시험 세부는 재사용하며 D-652 완료 범위와 후속 미착수 범위를 구별한다.

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 단일 셀·로봇·다중 로봇에서 공통 필요성 평가를 재사용하고 작업/자원 승인과 실제 결과를 기존 단일 owner에 연결한다.

**Architecture:** [D-648](../adr/D-648-shared-judgment-target-structure.md)와 [설계](2026-10-11-shared-judgment-structure-design.md)의 Situation assessment·Decision 후보·execution/site 규칙·Fleet 어댑터를 단계별로 분리한다. 기존 서비스/원장과 설치 경계를 유지하고 의미 추출 뒤 분산 배포 필요를 판단한다.

**Tech Stack:** 기존 Python·ROS-free 참조 형식·Fleet SQLite/httpx·static source holder mapping·원격 pytest. 신규 dependency와 범용 orchestration framework는 추가하지 않는다.

**Status:** 단계 0/1의 내부 shadow 구현은 [D-652](../adr/D-652-intervention-assessment-shadow.md) 범위로 진행한다. 공통 필요성 평가와 기존 CORE snapshot adapter만 수용하며 D-647/D-648 전체 구조, 단계 2~4, 외부 API와 현장 활성화는 Proposed/미완료다. [구현 및 검증 기록](../validation/intervention-assessment-2026-10-11.md)에 실제 소비자와 설치 closure를 기록한다.

사용자 선택(2026-10-11): 이번 병합은 판단·현장 연결·설치 책임부터 분리한다. 설치 구성의 실제 holder는 `tools/packaging/fleet_sources.py`; Fleet 메타데이터, source-layout 계산, site image COPY와 self-contained wheel/sdist를 함께 대조한다. 2/3단계 모델 도구 중재와 작업 규칙 이전은 이번 착지 범위에 넣지 않는다.

후속 진행(2026-10-11): 사용자의 이어서 처리 요청에 따라 [D-657](../adr/D-657-judgment-adapter-and-pure-execution-extraction.md)에서 단계 2와 단계 3 첫 계산 단위를 별도 수용했다. dispatcher는 `fleet.server.model_feedback_dispatch`, 순수 목표 검증과 진척 시각/step 상태 투영은 `rosy.execution.site.{goal_evidence,workflow}`로 분리한다. 전체 상태 전이/복구 및 단계 4를 완료로 집계하지 않는다. [실행 계획](2026-10-11-judgment-adapter-extraction.md)과 [검증 기록](../validation/judgment-adapter-extraction-2026-10-11.md)에서 이번 단위의 실제 증거를 확인한다.

## 0. 현재 소비자와 목표 책임 검수
Read: `operations/{world,situation,decision,execution,fleet}/AGENTS.md`, `rosy.decision` 하위 AGENTS, D-427/D-429/D-430/D-630/D-637, Proposed D-435/D-647/D-648.

1. 구현 착수 HEAD를 기록하고 `rg`로 assessment 입력 producer와 tool_dispatch·Mission/Job/claim·goal verifier의 실제 호출자/시험/fixture/config/export를 목록화한다. 설계의 사례표를 사람이 검수한다.
2. 순수 평가, 후보, 승인, 조치/목표 확인의 owner를 고정한다. 실제 도메인 predicate와 revision, 정상 sampling/보관과 평가 허용 한계를 정한다. 미담당 사건의 보류·담당 지정은 기존 사건 경로로 정한다.
3. 새 공통 평가의 내부 계약과 기존 facts/proposal의 구별을 확정한다. 공개 필드를 바꿀 필요가 있으면 API Reference·producer/consumer schema와 fixtures를 같은 단위로 갱신한다.
4. 초기 배포·필요 패키지 closure를 결정하고 구조 제안의 수용 여부를 기록한다. 수용 전에는 아래 소스 이동을 진행하지 않는다. 범위는 평가·어댑터·순수 규칙이며 새 Mission DB/실행기·모델 활성화가 아니다.

## 1. 공통 필요성 평가와 현재 사건 근거
Create: `operations/situation/rosy_situation/assessment.py`, `operations/situation/test/test_intervention_assessment.py`.
Modify: `operations/situation/rosy_situation/incidents/context.py`, 실제 Fleet assessment 호출 adapter; 필요 시 `fleet/stuck/reports.py`, `board.py`, `episodes.py`. Install candidate: `operations/fleet/setup.py`, `operations/fleet/fleet/_source_layout.py`의 기존 static holder와 self-contained sdist mapping, `test/test_remaining_platform_installed.py`. 기존 `rosy_situation` namespace를 같은 배포에 포함하고 `deploy/ai_pc/rosy-situation.service`의 별도 실행 위치와 credential은 유지한다. 최종 포함 파일/설치 closure는 단계 0에서 확정한다.

1. 신선 정상·유효 대기·처리 중·문 장애·Arm 실패·Mission 없는 관측·stale/상충·해소 뒤 오래된 권고 fixture와 fake clock을 작성·커밋한다. 도메인별 근거는 기존 producer에서 가져온다.
2. 커밋 HEAD의 실패를 원격 확인한 뒤 불변 입력과 필요성/사유·근거·유효기간 출력의 순수 함수를 최소 구현한다. normal·unknown·abstain을 합치지 않는다.
3. 기존 analyzer의 facts/제안과 ContextDraft 가설을 분리해 소비한다. 기존 transport를 fake로 주입해 비개입·보류가 mutating call을 생성하지 않음을 확인한다. 일반 상황평가가 CORE command를 직접 반환하지 않게 한다.
4. 당시/현재, 고정 초안 점수, 재관측 갱신과 사건 binding은 D-642의 회귀를 같이 검증한다. 정상 샘플링/평가 분모를 남긴다.
5. checkout 밖 설치에서 순수 assessment를 Fleet DB·HTTP·ROS 없이 import/호출하고 현재 Situation 서비스가 같은 판정을 소비하는지 검증한다. AI PC 설치/현장 활성화는 별도 receipt다.

Existing tests: `operations/situation/test/test_incident_context.py`, `test_analyzers.py`, `test_situation_service.py`, `operations/fleet/test/test_line_stuck_evidence.py`, `test_line_stuck_api.py`, `test_stuck_no_motion_fleet.py`. D-643의 정책·zero-command 관문을 함께 통과한다.

## 2. 원장 모델 도구 중재를 site 어댑터로 분류
Move proposed: `operations/decision/src/rosy/decision/tool_dispatch.py` → `operations/fleet/fleet/server/model_feedback_dispatch.py`.
Modify: 실제 dispatcher 생성/호출자, `operations/fleet/test/test_er2_tool_dispatch.py`, `test/test_remaining_platform_installed.py`, 양측 AGENTS·manifest·source/install mapping의 해당 항목.

1. 모든 import/export와 dispatcher의 조회/후보 쓰기·journal·fence 실패 사례를 현재 결과와 비교해 고정한다. 반환 reason code·기존 catalog/권한·동일 transaction은 바꾸지 않는다.
2. dispatcher만 어댑터 holder로 이전하고 후보/도구 계약·provider adapter는 Decision에 유지한다. 기존 타입과 주입 callback을 사용하며 얇은 범용 port framework나 옛 import shim은 추가하지 않는다.
3. Decision 핵심의 Fleet import 금지와 Fleet adapter의 기존 store 결속을 검사한다. source mapping·wheel/sdist 자산/entrypoint 검사는 현재 분리 위치에 맞게 함께 변경한다.
4. 원격 `test_er2_tool_dispatch.py`, `test_model_tool_call_journal.py`, `test_mission_ai_proposal.py`, `test_mission_feedback_loop.py`, `test_remaining_platform_installed.py`를 실행하고 known_failures와 비교한다. 설치된 tool dispatcher namespace의 변경은 내부 Python 소비자 변경이며 HTTP API를 신설하지 않는다.

## 3. 순수 작업 규칙과 목표 검증만 추출
Create proposed: `operations/execution/src/rosy/execution/site/workflow.py`, `goal_evidence.py`.
Modify: `operations/fleet/fleet/server/mission_service.py`, `mission_progress.py`, `step_dispatcher.py`, `goal_evidence.py` 및 실제 호출자·시험; execution wheel/설치와 manifest 항목은 바뀌는 범위만 갱신한다.

1. 먼저 구현 파일에서 pure 계산과 store/transport/auth를 구별한다. 계산만 추출할 첫 단위를 고르고 unit별 이름·시그니처·identity/patch 소비자·rollback 범위를 기록한다. MissionStore/CellJobStore/ProposalStore/dispatch claim은 옮기지 않는다.
2. source-neutral 정상/빈 입력/근거 부족/거절·재시작·경쟁·늦은 결과 회귀를 먼저 커밋·원격 실행한다. API 수락과 실제 terminal·목표 확인, 자연 해소를 구별한다.
3. 선택한 계산을 execution/site로 이동하고 기존 service 어댑터가 현재 store/claim transaction 안의 재검사를 유지하게 한다. 기존 장치 호출·재전송·stop/generation은 같은 경로에 남는다. 계산 추출로 Action 권한이나 복구 예산을 늘리지 않는다.
4. GoalEvidence 검증의 현재 frame/시각/provenance/predicate를 보존한다. Situation 권고나 모델 합의가 goal verifier를 대신하지 않게 한다. 공정 predicate의 의미와 실행 검증을 하나의 모듈로 합치지 않는다.
5. 실제 설치에서 execution과 Fleet 소비의 동일 계약 객체/결과를 확인한다. safety-tagged 의미·경로 변경이면 D-430 독립 리뷰와 trailer를 먼저 남긴다. 실패 시 자기 unit의 역이동/역패치만 수행하며 DB·동료 WIP는 변경하지 않는다.

Existing tests: `operations/fleet/test/test_mission_service.py`, `test_mission_store.py`, `test_mission_progress.py`, `test_mission_dispatcher.py`, `test_dispatch_admission.py`, `test_cell_job_recovery.py`, `test_cell_job_store.py`, `test/test_platform_item_pose.py`, `test/test_platform_cell_submission.py`, `test/test_structure_installed_packages.py`. 각 unit의 실제 소비자를 확인한 뒤 관련 invocation을 확정한다. 의미 전이는 전이표로, I/O/경쟁은 기존 integration suite로 검증하며 구현을 그대로 복제한 시험을 늘리지 않는다.

## 4. 중앙 처리·알림·화면·독립 수용 연결
Modify: 위 현재 사건/작업 어댑터와 D-644 원장·결과 기록. Create only in D-645 implementation: `operations/fleet/fleet/incidents/notifications.py`와 해당 설정/시험. Console은 `operations/ui/console`의 기존 화면과 D-646 계약을 따른다.

1. 권고 revision→owner 채택/보류→기존 조치 제출→수락/거절/불명→실제 목표/해소를 같은 원장으로 대조한다. 활성 Mission 없는 사건도 새 Mission을 자동 만들지 않고 같은 case owner로 처리한다.
2. 알림 outbox는 기존 사건 transaction에서 생성하고 normal 비개입 zero-send·dedupe·expiry·부분 실패·제한 retry·재시작을 시험한다. 발송·읽음·담당 접수·실제 종료를 구별한다.
3. Discord/Slack/Telegram의 발송과 인증 Console 인수·readback부터 검증한다. 채팅 내 callback은 D-645의 서명/auth/actor·nonce/expiry·세대 관문 뒤에만 수행한다.
4. 단일 셀/로봇/다중 로봇·관측-only/비개입/상충 사례의 독립 평가와 정상 분모를 고정한다. SOURCE·설치·브라우저·채널·DEVICE·FIELD 증거를 별도로 기록한다.
5. D-642~D-646 수용 receipt 후에 D-640의 model routing/유한 debate·교정/독립 평가/승격을 연결한다. 정상 작업·로컬 안전을 느린 모델 호출에 종속시키지 않는다.

## 시험과 완료 증거
Python 시험은 커밋된 HEAD만 `tools/remote/remote_pytest.py`로 보낸다. 관련 suite와 별도 상황/브라우저 invocation을 구별하고 각 `run-1.txt`에 `test/known_failures.py`를 실행한다. 시험 PC floor·실제 terminal exit·원격 receipt를 기록한다. 노트북 pytest, 확인되지 않은 기존 실패 분류, 모델/장치 성공의 대체 보고는 하지 않는다.

이번 **문서 변경**의 검증 명령은 다음과 같다. 구조 구현 suite의 통과를 의미하지 않는다.

```powershell
python tools/harness/rosy_harness.py generate
python tools/harness/rosy_harness.py lint
python tools/remote/remote_pytest.py --log-dir X:/DevTemp/<session>/logs/structure-docs -- test/test_network_topology_contracts.py test/test_harness_contracts.py
python test/known_failures.py X:/DevTemp/<session>/logs/structure-docs/run-1.txt
```

완료 기록에는 시작/최종 SHA·ADR 수용·정책/평가 revision·이전 unit·호출자/fixture/install 변경·테스트 terminal/known_failures·단일 원장/권한 보존·잔여 배포/수용을 포함한다. 현재 폴더 책임표의 실제 경로는 해당 unit 구현 뒤에만 갱신한다. main 착지·push·배포는 별도 사용자 지시와 해당 gate를 따른다.
