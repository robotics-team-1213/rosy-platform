# Responsibility, Authority and Orchestration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 공통 판단·모델 후보·작업 규칙·현장 중재·장치 실행·결과 평가를 책임별로 연결하고 정상 비개입까지 독립 평가한 뒤 제한된 모델 토론/개선으로 확장한다.

**Architecture:** [D-656](../adr/D-656-responsibility-authority-and-orchestration-boundaries.md)의 논리 책임을 현재 배포 안에서 분리한다. 순수 규칙은 Situation/Decision/execution에, 기존 DB·auth·claim·generation fence·transport는 Fleet 현장 어댑터에 둔다. CORE/OMX의 최종 writer와 독립 목표 검증, 기존 단일 원장을 유지한다.

**Tech Stack:** 기존 Python·표준 라이브러리·SQLite/httpx/pydantic·ROS-free 계약·wheel/sdist source mapping·원격 pytest. 새 범용 orchestration framework나 dependency는 추가하지 않는다.

**Status:** 책임 추출과 D-660~D-662의 판단 기록·사람 인수·알림·독립 checker를 구현하고 원격 검증했다. 실제 소유 경로와 단위별 증거는 [구현 기록](../validation/responsibility-boundaries-2026-10-11/implementation.md)을 따른다. 공개 API는 API Reference에 기록한 필드만 사용한다. 팀은 새 Discord 서버/채널 준비와 현장 정답 검수·한계 확정을 맡는다. 실제 채널 수신·현장 수용이 없는 단계 3~5는 HOLD이며, 단계 6은 선행 수용 뒤 구현한다. 전체 CI·실제 이미지 빌드·배포·현장 활성화는 별도다.

---

## 진행 순서와 관문

| 단계 | 산출물과 단일 책임 | 완료 조건 | 현재 상태 |
|---|---|---|---|
| 0 | 실제 producer/consumer·권한·사건 owner 목록 | 각 판단/쓰기/종료의 owner와 설치 소비 확인 | 소스 목록 확정; 현장·문 capability 미확인 |
| 1 | 모델 원장 도구의 현장 어댑터 분리 | Decision 핵심 Fleet import 제거, 동일 transaction/fence/설치 보존 | 소스·원격 설치 계약 완료 |
| 2 | 순수 작업 진행·목표 근거 규칙 추출 | 계산만 이동, 현재 store/admission/장치 호출 유지 | 소스·원격 설치 계약 완료; 실물/ARM64 미확인 |
| 3 | 현재 사건·비개입·보류·owner·결과·화면 연결 | 신선도/기한/경쟁/자연 해소, 단일 종료 writer 확인 | D-660 읽기 판단·종료 근거, D-661 이름 있는 인수 구현; 운영 수용 HOLD |
| 4 | 외부 알림·인증된 사람 인수 | outbox→수신→Console 인수→결과 readback | D-661 기본 OFF·3채널 fake 시험 완료; 팀 Discord 준비/실제 수신 HOLD |
| 5 | 독립 중앙 판단 수용 | 정상 분모·도메인 정답·지연/정확도 한계 확정 및 통과 | D-662 offline checker 구현; 팀 정답/한계 검수 HOLD |
| 6 | 제한 모델 런과 개선 후보 | 0~5 receipt 뒤 후보 전용 토론·독립 비교·승격/rollback | 선행 실제 수용 대기 HOLD; 구현/provider 호출 미착수 |

단계 1/2는 의미를 보존하는 추출이다. 단계 3부터의 새 저장/공개 필드/정책은 해당 D-642~D-646의 세부 수용 뒤 구현한다. 5단계가 준비되기 전 운영 provider 호출을 연결하지 않는다. 문서 검증 통과는 이 관문들의 런타임 완료가 아니다.

## 공통 작업 절차

각 단위마다 아래 순서를 따른다. 구현자는 `@using-git-worktrees`, `@executing-plans`, `@verification-before-completion`과 저장소 AGENTS를 적용한다.

1. 현재 HEAD·main·변경 경로의 AGENTS/ADR와 모든 caller/test/fixture/config/export/install을 `rg`로 확인한다. 자기 registered non-main worktree만 수정한다.
2. 기존 의미와 변경하려는 경계의 실패/정상/경쟁/늦은 결과 시험을 작성한다. RED 커밋을 원격 실행하고 terminal 로그를 known_failures와 비교한다. 예상 RED도 NEW로 남기고 baseline에 추가하지 않는다.
3. 최소 구현과 실제 호출자·fixture·설치 mapping·manifest root를 함께 수정하고 정확한 파일 경로만 add/커밋한다.
4. GREEN 커밋 HEAD를 같은 원격 suite로 검증한다. 새 실패 0, source 밖 wheel/sdist 및 source image 구성 확인, 기존 writer/transaction/fence 보존을 확인한다.
5. 문서·receipt와 unit 결과를 기록한다. 사용자에게 이미 승인된 착지 범위에서 `tools/land.py --tests auto`로 최신 main을 통합하고 재검증한다. push·배포·활성화는 각각 해당 사용자 지시와 별도 관문을 따른다.

시험 예시는 PowerShell이며 `<session>`은 관리 도구로 만든 `X:/DevTemp/projects/rosy-platform/...`다. 커밋 후에만 실행하고 RED/GREEN별 log-dir를 나눈다.

```powershell
python tools/remote/remote_pytest.py --log-dir <session>/logs/<unit>-green -- <test-paths>
python test/known_failures.py <session>/logs/<unit>-green/run-1.txt
```

기대: 원격 프로세스 exit 0, `0 new`. 닿는 시험 PC가 없으면 확인 못 함이며 착지하지 않는다. 노트북 pytest나 전체 CI의 로컬 대체 실행은 하지 않는다.

## Task 0: 책임·입력·쓰기·종료 owner를 현재 소스로 확인

**Read:** `operations/{world,situation,decision,execution,fleet}/AGENTS.md`, 해당 하위 지침, D-656/D-648/D-652/D-642~D-646 및 기존 API Reference.

**Modify:** `docs/reference/platform-folder-responsibilities.md`의 실제 착지 unit만. **Create:** `docs/validation/responsibility-boundaries-<date>/result.md` (공개 가능한 producer/consumer·권한/증거 목록; 주소·secret 없음).

1. `MissionFeedbackToolDispatcher`, `MissionProgressService`, `GoalPredicate`, `LineStuckBoard`, model-turn scheduler/worker의 실제 caller를 검색한다. 각 source·입력 생산자·출력 소비자·쓰기 권한·종료 owner·패키지/호스트를 한 행으로 기록한다.
2. 단일 로봇/Arm 셀/다중 로봇/문 앞 정지/관측-only/정상 비개입의 사례별 owner와 실제 condition predicate를 기록한다. 미제공 문 센서·capability는 미확인으로 두고 검증 전 adapter를 활성화하지 않는다.
3. 다음 task의 이동 단위와 현재 namespace를 고정한다. roster 기반 cache와 불변 순수 입력만으로 가능한 일을 새 공통 DB/service로 확장하지 않는다.

**완료:** 모듈명만 있는 표가 아니라 모든 쓰기와 결과 확인의 실제 owner가 있고 설치/실행 위치를 구별한다. 부족한 도메인 producer와 현재/과거 표시의 gap을 다음 task에 명시한다.

## Task 1: 모델 원장 도구 중재를 Fleet 현장 어댑터로 이전

**Move proposed:** `operations/decision/src/rosy/decision/tool_dispatch.py` → `operations/fleet/fleet/server/model_feedback_dispatch.py`.

**Read/Modify:** `operations/fleet/fleet/server/{app,mission_model_turn_worker}.py`, 실제 import/export caller, `operations/fleet/fleet/_source_layout.py`, `operations/fleet/setup.py`, `tools/packaging/fleet_sources.py`에서 영향이 확인된 항목, `tools/harness/platform_parts.yaml`, 양측 AGENTS.

**Test:** `operations/fleet/test/{test_er2_tool_dispatch,test_model_tool_call_journal,test_model_tool_adapter_conformance,test_mission_ai_proposal,test_mission_feedback_loop}.py`, `test/test_remaining_platform_installed.py`, `test/architecture/test_platform_parts.py`.

1. 기존 도구 allowlist·principal/workcell·owner·claim·stop/generation·late result·store 예외·재시작 결과를 테스트로 고정한다. 동일 candidate에 경쟁 요청이 와도 유효한 원장 변경은 하나여야 한다.
2. dispatcher와 Fleet store 결속만 이동하고 provider-neutral tool 계약/catalog와 후보/모델 adapter는 Decision에 둔다. 기존 이름/호출자 전체를 갱신하며 새 범용 port나 호환 shim을 추가하지 않는다.
3. `test_remaining_platform_installed.py`의 기존 `rosy.decision.tool_dispatch` import를 새 namespace로 바꾸고 checkout 밖 wheel/sdist에서도 호출을 확인한다. 새 namespace는 내부 Python 계약 변경이며 HTTP route 추가가 아니다.
4. 위 관련 suite를 원격 검증한다. 기존 반환 reason·transaction·원장·fence·최종 writer가 유지되고 Decision 핵심에 Fleet store import가 없으면 완료다.

## Task 2: 순수 작업 규칙과 독립 목표 근거 계산 추출

**Read/Modify:** `operations/fleet/fleet/server/{mission_service,mission_progress,step_dispatcher,goal_evidence,goal_evidence_service,dispatch_admission}.py`.

**Create proposed:** `operations/execution/src/rosy/execution/site/workflow.py`, `goal_evidence.py` (선택한 순수 계산만). **Modify:** 실제 caller와 `operations/execution/pyproject.toml`, Fleet/execution 설치·manifest의 영향 항목.

**Test:** `operations/fleet/test/{test_mission_service,test_mission_progress,test_step_dispatcher,test_goal_evidence,test_goal_evidence_service,test_dispatch_admission,test_cell_job_recovery}.py`, `test/test_platform_installed_entrypoints.py`, `test/test_remaining_platform_installed.py`.

1. 먼저 `goal_evidence.py`의 pure 타입/검증과 진행 계산의 실제 I/O 의존을 분류한다. 첫 추출의 함수·시그니처·예외·객체 identity 소비자를 Task 0 기록에 적은 뒤 한 단위씩 이동한다. `MissionProgressService`를 store와 통째로 옮기지 않는다.
2. 빈/상충/stale 근거·다른 attempt·미래 시각·재시작·budget 소진을 RED로 고정한다. API 수락/Action 성공/목표 확인/자연 해소를 구별하고 관측 없는 완료를 거절한다.
3. 기존 frame/provenance/predicate 의미와 예외를 보존한다. 순수 계산은 execution/site, 조회·auth·claim·재검사·dispatch·stop fence는 기존 Fleet transaction에 남긴다. MissionStore/CellJobStore/ProposalStore와 원장은 이동하지 않는다.
4. 설치된 execution/Fleet 소비자가 같은 계약 객체와 결과를 쓰는지 확인한다. safety-tagged 변경이면 D-430 독립 검토와 필수 기록 뒤 착지한다.

**완료:** 단일 셀도 계산을 재사용하고 기존 Fleet I/O 회귀가 통과한다. 추출로 실행 권한·복구 예산·종료 writer가 늘어나지 않는다.

## Task 3: 중앙 사건 판단·owner·결과·관제 표시 연결

**Reuse:** D-652 `operations/situation/rosy_situation/{assessment,snapshot_assessment}.py`. **Read/Modify:** `incidents/context.py`, Fleet `fleet/stuck/{board,reports,episodes}.py`, 현재 사건/작업 store·service와 `operations/ui/console/site-map.html`의 실제 표시 caller.

**Test:** `operations/situation/test/{test_intervention_assessment,test_assessment_consumers,test_incident_context}.py`, `operations/fleet/test/{test_line_stuck_evidence,test_line_stuck_api,test_stuck_no_motion_fleet}.py`, 해당 실제 Console browser suite.

1. D-642~D-644와 D-646의 producer/consumer 계약을 검수하고 필요한 새 저장 필드가 있으면 기존 원장 migration/API Reference/schema/fixtures를 같은 unit으로 확정한다. 이 계획의 표를 wire schema로 쓰지 않는다.
2. 당시 근거와 현재 상태, 가설 점수와 검증된 판단을 분리한다. offline/stale/conflict/legacy 시각 누락은 보류, 유효 안전 대기는 기한까지만 비개입, 지속 막힘/owner 상실은 신선한 근거로 개입 평가한다.
3. 채택 직전 현재 owner·case/revision·policy·expiry를 재검사한다. 조치 수락·응답 불명·실행 terminal·목표 확인·사건 종료를 별도로 기록하고 owner 하나만 종료를 쓴다. 정상 신규 command/problem alert는 0, 자연 해소는 조치 성공과 별도다.
4. 새 door/Arm adapter는 producer/capability/도메인 정답이 있는 것부터 한 개씩 추가한다. CORE snapshot용 helper에 문·Arm 조건을 억지로 넣지 않는다.

**완료:** D-642~D-644 receipt와 현재/당시 화면 검증, 담당 인수/재시작/늦은 결과·무조치 해소 회귀가 있다. 실제 운영 소비/현장 정확도는 shadow 시험과 별도 receipt로 확인한다.

## Task 4: 외부 알림과 인증된 사람 인수

**Detailed plan:** [중앙 판단 단계](2026-10-11-fleet-central-judgment-stages.md)의 D-645 절. **Create proposed:** `operations/fleet/fleet/incidents/notifications.py`, `operations/fleet/test/test_notifications.py` (기존 adapter가 있으면 재사용).

**Read/Modify:** 실제 사건 owner의 transaction·store/service, 기존 Console 인증·inbox·설정 및 채널별 비공개 설정 template.

1. outbox 원자성·중복·expiry·재시작·부분 실패·429/timeout·전송 불명·종료 직전 상태 변화·정상 zero-send·secret 비노출을 fake 채널로 RED/GREEN 검증한다.
2. 최초 연결은 지정 채널 발송과 token 없는 인증 Console 사건 링크다. 기존 model-turn outbox를 알림 전송 큐로 소비하지 않는다. 읽음/발송 성공을 처리 접수나 해소로 표시하지 않는다.
3. 지정된 실제 Discord/Slack/Telegram 목적지에서 발송→수신→로그인/권한 확인→담당 인수→Fleet readback→실제 결과→종료 통지를 확인한다. 실제 발송/채팅 callback 활성화는 별도 승인·설정 관문이다.

**완료:** 채널별 receipt와 실패 시 Console 표시/담당 상승이 있다. 서명/auth/nonce/expiry/세대 검증 없는 채팅 응답은 조치 명령으로 접수하지 않는다.

## Task 5: 정상 분모와 독립 도메인 정답으로 중앙 판단 수용

**Reuse:** D-646 [수용 계약](../adr/D-646-fleet-judgment-acceptance.md), `learning/curation/perception/incident_feedback.py`, `tools/decision_replay.py`, 기존 검증 records. **Test:** `test/learning/perception/test_incident_feedback.py`, 해당 도메인 producer/adapter suite.

1. 정상·허가 대기·비개입·보류·자연 해소·실제 개입의 사람 검수 정답과 고정 평가 hash를 만든다. 장소/시간/세션을 분리하고 기존 학습 정답과 평가 세트가 겹치지 않게 한다.
2. 필요 개입의 정답 P와 정상/안전 대기 N을 기준으로 누락률=`P 중 개입 필요를 놓친 수/|P|`, 불필요 개입률=`N 중 개입한 수/|N|`를 계산한다. 보류율은 별도로 보고하고 P의 보류가 대응 기한을 넘기면 누락 평가에 포함한다. 분모 0은 N/A다.
3. 해소율은 실제 조치를 시도한 검증 가능한 사건 기준으로 보고하고 자연 해소를 별도 집계한다. 끝까지 관측하지 못한 사건·목표 미확인은 성공에서 제외해 별도 수로 남긴다. 시각·재발 관측 구간·p95 처리 지연을 고정한다.
4. 표본 수·도메인별 허용 한계·기권 처리·지연/복구 예산·독립 checker를 평가 실행 전에 확정한다. 운영 승격의 임의 숫자를 이 계획에서 만들어 넣지 않는다. SOURCE/설치/CI/채널/DEVICE/FIELD를 별도로 판정한다.

**완료:** 모든 대상 도메인과 정상 분모의 독립 receipt, 허용 한계 통과 및 이전 승인 정책 rollback 경로가 있다. 미확인 도메인은 운영 활성화 HOLD이며 모델 합의로 대체하지 않는다.

## Task 6: 후보 전용 모델 숙고와 지속 개선

2026-10-12 추가 지시로 Discord를 제외한 후보 소스를 선행 구현했다.
실제 경로·검증과 남은 관문은 [책임 경계](2026-10-12-decision-deliberation-boundary.md)를 따른다.
아래 0~5 receipt 선행 조건은 실제 provider 활성화/운영 승격에 유지한다.

**Detailed plan:** [D-640 모델 토론 실행 계획](2026-10-11-fleet-deliberation-loop.md). 기존 파일별 Task 1~6을 재사용한다.

**Create proposed:** `operations/decision/src/rosy/decision/{deliberation,cli_deliberation}.py`, `operations/fleet/test/{test_deliberation,test_cli_deliberation,test_deliberation_journal,test_deliberation_replay}.py`.

**Reuse:** `model_tool_contract.py`, `model_tool_catalog.py`, `operations/fleet/fleet/server/model_feedback_dispatch.py`, 기존 `mission_model_turn_{store,scheduler,worker}.py`, incident feedback/replay. D-640의 현장 dispatcher 경로도 같은 namespace를 사용한다.

1. 0~5 선행 receipt가 준비된 뒤 구현한다. 규칙/검수 사례/빠른 모델과 미해결 문제의 유한 토론을 구별한다. 한 문제 활성 런 하나, 전체 deadline/횟수/비용 제한·취소·재시작·출력 불명·상충·늦은 결과를 fake adapter/clock으로 검증한다.
2. 실제 CLI/model ID·버전·권한·지원 기능을 확인하고 승인 프로파일을 고정한다. 프로세스/네트워크/파일 권한 제한과 호스트 hooks/MCP/메모리 비상속을 검증한다. 정상 작업/장치 stop은 모델을 기다리지 않는다.
3. 첫 실제 연결은 보고/후보 전용이다. 원장 쓰기는 기존 현장 어댑터만 수행하고 모델 답으로 Motion/Action/E-stop 해제나 사건 종료를 직접 호출하지 않는다.
4. 규칙·단일 모델·토론을 동일 독립 평가 세트로 비교한다. 모델·프롬프트·규칙·라우팅 개선은 별도 version과 receipt를 가지며 수집→교정→평가→shadow→제한 장치→현장 승인 순으로 승격한다. 악화 시 고정 이전 프로파일로 되돌린다.

**완료:** 후보 전용 런의 제한/설치/결과 lineage와 실제 provider smoke, 독립 비교 receipt가 있다. 자동 조치와 학습 정책 자동 활성화는 이 완료에 포함하지 않는다.

## 이번 문서 변경의 검증과 인계

```powershell
python tools/harness/rosy_harness.py generate
python tools/harness/rosy_harness.py lint
# 위 생성 결과를 정확한 경로로 커밋한 뒤
python tools/remote/remote_pytest.py --log-dir <session>/logs/docs -- test/test_network_topology_contracts.py test/test_harness_contracts.py
python test/known_failures.py <session>/logs/docs/run-1.txt
```

기대: ADR 본문/Log 제목·상태 일치, 링크/생성 index/소유 규약 통과, lint 오류 0, 원격 문서 계약 NEW 0. 이것은 runtime/DEVICE/FIELD 수용이 아니다.

각 task 인계에는 시작/최종 SHA, 실제 수정 경로, producer/consumer, 단일 원장·권한 보존, remote terminal·known_failures, 설치/CI/배포/현장 상태와 다음 관문을 남긴다. 별도 서비스·World 미래 예측·새 범용 ResourceManager는 실제 요구와 증거가 생긴 뒤 별도 ADR로 검토한다.
