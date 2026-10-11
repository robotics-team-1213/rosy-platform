# Fleet Central Judgment Stages Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fleet이 개입·비개입·판단 보류를 근거로 구별하고, 중앙 중재와 외부 담당자 처리를 실제 결과로 닫는 규약을 D-640보다 먼저 완성한다.

**Architecture:** [D-647 공통 판단 책임·배포 0단계](../adr/D-647-shared-judgment-ownership-and-deployment.md)에서 World 상태·공통 상황평가·deliberative 후보·작업/자원 중재를 구별하고 논리 holder와 초기 배포 위치를 먼저 결정한다. 현재 `fleet.stuck`과 Console은 기존 소비자·adapter로 재사용하며 공통 판단 전체의 Fleet 소유를 뜻하지 않는다. 기존 Mission/claim transaction과 Fleet admission 및 CORE/OMX 권한은 보존한다.

**Tech Stack:** 기존 Python/httpx/SQLite, ROS-free 계약, Console 정적 JS 및 원격 브라우저. 외부 알림은 설정된 Discord/Slack/Telegram adapter와 인증 Console 처리 링크로 시작한다.

**Status:** 2026-10-11 검토용 계획, 아래 ADR 전부 Proposed. 이번 변경은 문서만이며 판단 코드·화면·알림 구현과 실채널 전송은 수행하지 않았다. 신규 경로와 상태 의미는 구현 예정이며 오늘의 API가 아니다.

## 우선순위와 단계

**0단계 구체화:** [D-648 목표 책임 구조](../adr/D-648-shared-judgment-target-structure.md)의 [설계](2026-10-11-shared-judgment-structure-design.md)와 [분리 계획](2026-10-11-shared-judgment-structure.md)을 먼저 검토한다. 공통 assessment는 Situation, 대안은 Decision, 순수 작업 규칙은 기존 execution/site, 원장/승인/transport는 현재 어댑터로 두는 Proposed 구조다. 중앙 판단의 구현 위치는 이 구조의 수용과 설치 closure 확인 뒤 확정한다.

| 순서 | ADR | 산출물 | 다음 단계 조건 |
|---|---|---|---|
| 0 | [D-647 공통 판단 책임·배포 0단계](../adr/D-647-shared-judgment-ownership-and-deployment.md) | 단일 셀/로봇/다중 로봇 책임·의존 표와 holder/port·초기 배포 결정 | 사실/권고/승인 분리, 기존 transaction·권한 보존, 배포 대안과 선택 근거 검토 |
| 1 | [D-642 근거 규약](../adr/D-642-fleet-judgment-evidence.md) | 당시/현재와 증상/가설/검증을 구분하는 근거 계약 | 시각·출처·binding·누락/상충 회귀와 API/DB 호환 통과 |
| 2 | [D-643 개입 필요성](../adr/D-643-fleet-intervention-necessity.md) | 개입·비개입·판단 보류 규칙과 정상 구간 분모 | 정상/위험/불명 검수 시나리오 및 zero-command 통과 |
| 3 | [D-644 중앙 처리](../adr/D-644-fleet-central-judgment-transaction.md) | 단일 owner·중복/세대 fence·조치/결과 원장 | 경쟁·장애·재시작·응답 불명·실제 해소 구분 통과 |
| 4 | [D-645 알림·사람 처리](../adr/D-645-fleet-channel-escalation.md) | durable 알림과 세 채널·인증된 담당자 처리 | fake 계약 뒤 지정 실채널 수신·Console 처리·결과 회수 증거 |
| 5 | [D-646 화면·독립 수용](../adr/D-646-fleet-judgment-acceptance.md) | 이해 가능한 관제와 독립 개입/비개입 평가 receipt | 해당 SOURCE/계약/브라우저/설치/사람·장치 수용을 각각 확인 |
| 후속 | [D-640](../adr/D-640-fleet-deliberation-and-incident-improvement.md) | 전문 모델 라우팅·제한 토론·지속 개선 | 1~5 규약과 중앙 판단 baseline 수용 receipt를 선행 참조 |

문서/계약 시험이 통과해도 장치·현장·실채널 층을 자동 GO로 바꾸지 않는다. 단계 4의 채팅 내 직접 응답은 발송+Console 인수 뒤 별도 인증 관문을 통과한다. 모델 다양화나 자동 토론을 먼저 붙여 중앙 판단의 근거/처리 부족을 감추지 않는다.

## 현재 소스에서 확인한 출발점

- `operations/ui/console/console.js:279-300`은 닫힌 여부와 `phase_at_open`, 고정 점수의 AI 초안, 수락/미확인 조치를 함께 보여 준다. `ASKING`은 시작 단계이며 현재 상태가 아니다.
- `operations/situation/rosy_situation/incidents/context.py`는 CORE cause에서 원인 초안을 만들고 원인별 0.45/0.35/0.2 점수를 부여한다. 이 값은 모델 성능이나 보정된 원인 확률이 아니다. `seen`은 같은 robot/stuck 초안을 한 번만 발행한다.
- `operations/fleet/fleet/stuck/reports.py::_resolution`은 답 수락 tier로 `resolved_by`를 계산할 수 있다. 실제 목표/복구 성공과 구별해야 한다.
- `operations/fleet/fleet/stuck/resolver.py`, `problems.py`, `outcome.py`, `closed_loop.py`에 규칙·문제 감시·결과 회수의 기존 경로가 있다. 처음부터 별도 범용 판단기를 만들지 않고 호출자를 확인해 확장한다.
- D-632와 `operations/ui/console/inbox.js`는 읽음과 개입 해소를 이미 구별한다. 기존 ER2 outbox는 모델 turn용이며 외부 메시지 전송기가 아니다. 조사한 경로에서 세 외부 채널의 실제 전달/사람 처리 완료 경로는 확인되지 않았다.
- 사용자 스크린샷은 과거 사건 보고의 예다. 이 계획에서 현재 로봇 상태나 물리 정지·원인 정확도·복구 성공의 증거로 취급하지 않는다.

## 판단 표와 관측 결과

아래 행은 코드 enum 추가가 아니라 검수할 의미다. 실제 필드/호환 계약은 구현과 API Reference에서 함께 확정한다.

| 상황 | 필요성 평가와 현재 owner 처리 | 장치 영향 | 기록·알림과 재판단 |
|---|---|---|---|
| 신선한 정상 진척 | 비개입 | 추가 명령 없음 | bounded 정상 샘플/판정; 새 위험·진척 실패 때 재판단 |
| 정상 신호/자원 대기 | 비개입 + 감시 | 기존 owner 정책 유지 | 허가/owner/기한 확인; 기한 초과는 개입 후보 |
| 다른 담당자가 처리 중 | 추가 개입 불필요 + 감시 | 경쟁 명령 없음 | 담당·기한 유지; owner 상실/실패 시 재판단 |
| 사건이 해소되고 현재 정상 근거 있음 | 비개입, 사건 종료 확인 | 오래된 후보 폐기 | 실제 해소 근거; 필요 시 기존 알림 종료 업데이트 |
| 새 문/장애물·암 대상 실패, 조건 충족 | 개입 필요 | 기존 허가 경로에서 제한된 조치 | 원인 가설·근거·담당·조치/결과와 위험 정책 알림 |
| stale·연결 단절·위치 불명·근거 상충 | 판단 보류 | 임의 재개 없음; 기존 local 안전 유지 | 누락 근거·다음 관측·기한; 필요한 사람 상승 |
| 잠깐의 정체/교착 첫 후보 | 지속 여부 평가 | 성급한 재계획/중복 정지 없음 | debounce/지속 관문 뒤 재판단; 새 위험은 지체하지 않음 |
| 수락됐으나 실제 결과 없음 | 결과 불명 | 자동 성공/재실행 없음 | owner readback 조정, 기한 후 사람 처리 |

비개입의 성공은 요청을 안 보냈다는 사실과 유효한 관측 결과로 확인한다. `WAIT` 명령 전송은 비개입이 아니며, 자동 안전 대기 유지와 새 대기 명령을 구별한다. 읽음·ACK·기권도 서로 다른 기록이다.

## 단계별 파일과 검증 작업

### 0. 공통 판단 책임과 배포 위치

Read: D-429, Proposed D-435, D-630, `operations/world/AGENTS.md`, Situation/Decision/Fleet 설치와 Mission/claim의 실제 소비자. [D-647 공통 판단 책임·배포 0단계](../adr/D-647-shared-judgment-ownership-and-deployment.md)의 사례·입출력·의존·transaction 표를 만든다. 단일 암 셀/로봇/다중 로봇과 Mission 없는 관측의 owner를 비교하고, 공통 평가 holder/port와 초기 배포를 결정한다. 현재 코드 수정·새 서비스 생성은 수행하지 않는다. B(논리 분리 후 기존 배포 유지)는 잠정 추천이며 독립 서비스 필요는 실제 자원·장애 격리·지연 요구로 검토한다. 아래 공통 로직의 생성 경로는 이 관문 뒤 확정한다.

### 1. 사건 근거와 표시 의미

Modify: `operations/fleet/fleet/stuck/reports.py`, `board.py`, `episodes.py`, `operations/situation/rosy_situation/incidents/context.py`, `operations/fleet/fleet/server/console_routes.py`, `operations/ui/console/console.js`.
Existing tests: `operations/fleet/test/test_line_stuck_evidence.py`, `test_line_stuck_api.py`, `test_ai_facts.py`, `operations/situation/test/test_incident_context.py`.

1. 각 producer/consumer와 문서 필드를 `rg`로 확인하고 현재 API fixture와 DB 읽기 사례를 고정한다.
2. 당시/현재 혼동, 카메라 시간 근접의 원인 오인, 고정 confidence, stale/상충/잘못된 사건, 누락 영상, 재관측 갱신 회귀를 먼저 작성·커밋한다.
3. 커밋 HEAD를 원격으로 시험해 새 회귀의 실패를 확인한 뒤 기존 helper/validator로 최소 수정한다.
4. 계약/필드를 바꿀 때 `docs/reference/ROSY API & Protocol Reference.md`와 공통 schema, fixtures, 호출자를 같이 갱신한다. 과거 기록은 덮어쓰지 않고 additive migration만 한다.
5. 원격 재검증과 known_failures 비교 뒤 해당 계약 commit·schema revision·로그 경로를 receipt에 남긴다.

### 2. 개입·비개입·보류

Modify: `operations/fleet/fleet/stuck/resolver.py`, `problems.py`, `lane_lost.py`, `ai_first.py`와 실제 호출자.
공통 필요성 평가/판단 기록의 생성 경로는 D-647의 holder 결정 후 명시한다. Fleet 파일은 기존 호출자와 중재 adapter 범위이며 `fleet/stuck/judgment.py`를 공통 판단의 영구 위치로 선점하지 않는다.
Tests: 기존 `test_stuck_resolver.py`, `test_stuck_no_motion_fleet.py`; new `operations/fleet/test/test_intervention_necessity.py`.

판단 표를 사람 검수 fixture로 만든 뒤 fake clock으로 필요성/사유/유효 범위·재판단 전이를 먼저 시험한다. 비개입/보류가 기존 transport의 mutating call을 만들지 않는지 확인한다. 관측 읽기는 허용된다. 정상 sample과 문제 transition의 bounded 기록, 전이 중복, debounce·기한·owner 상실·새 위험을 시험한다. 모델 abstain을 정상으로 분류하지 않는다. 정상 샘플링/보관 한계와 평가 허용값은 구현 전에 고정한다.

### 3. 단일 중앙 owner와 결과

Modify: `operations/fleet/fleet/stuck/loop.py`, `closed_loop.py`, `outcome.py`, `reports.py`, 기존 Mission/claim 서비스의 실제 소비자.
Tests: `operations/fleet/test/test_stuck_resolver_loop.py`, `test_line_stuck_api.py`, `test_mission_feedback_loop.py`; new `operations/fleet/test/test_judgment_transaction.py`.

owner/사람 우선/사건·세대 fence와 중복·불명 결과의 실패 시험을 먼저 쓴다. 판정 기록→제출→수락/거절→실제 결과→해소를 기존 journal에 연결하고 자연 해소·비개입 해소를 따로 기록한다. 수락 tier를 인과 복구 성공으로 표시하지 않는다. 원장 장애/경쟁·재시작·stop·stale reply와 기존 제한 재전송을 검증한다. safety 태그의 변경은 독립 리뷰를 거친다.

### 4. 외부 알림과 사람 처리

Reuse/read: `fleet/server/sqlite_policy.py`, `mission_model_turn_store.py`의 원자 claim 패턴, `site_users.py`, D-632 Console inbox. 기존 ER2 큐에는 외부 알림을 넣지 않는다.
Proposed create: `operations/fleet/fleet/incidents/notifications.py` (bounded outbox/세 채널 adapter; 크기가 실제로 분리 기준을 넘을 때만 나눈다), `deploy/site/notifications.env.example`.
Modify: 실제 Fleet 사건 transaction·설정 로더·worker 설치와 lifecycle 소비자. 기존 파일 위치는 구현 직전 caller inventory로 확정한다.
New tests: `operations/fleet/test/test_incident_notifications.py`.

1. 비개입 zero-send, 미설정 차단, atomic outbox·dedupe·expiry·재시작·현재 사건 확인을 fake provider/clock으로 먼저 시험한다.
2. 현재 httpx·SQLite를 이용해 세 adapter의 timeout/429/5xx·전송 불명·부분 실패와 제한 재시도를 구현한다. 전송 실패를 Fleet 해결 실패/안전 명령으로 변환하지 않는다.
3. 사건 식별과 최소 근거·기한·담당, 인증 Console 처리 링크를 보낸다. channel/secret/수신자 정보는 비공개 설정이며 public template·ignore/배치 계약을 함께 시험한다. 공개 로그에는 secret·원본 영상이 없어야 한다.
4. 설치와 실제 채널·담당자 설정 후 지정 수신→로그인→같은 사건 처리→Fleet readback→결과/종료 알림으로 인수한다. 실제 채널을 확인하기 전에는 fixture 전달을 사람 수신으로 보고하지 않는다.
5. 채팅 내부 응답은 위 인수 이후 수행한다. Slack/Discord의 공식 요청 검증, Telegram의 webhook secret 등 각 방식과 외부 actor의 Fleet 권한 매핑·nonce/expiry·사건 세대를 검증한 다음 접수/검토부터 연다. 로봇 영향 조치는 기존 Fleet admission과 별도 재확인 조건을 그대로 따른다.

### 5. Console과 독립 수용

Modify: `operations/ui/console/console.js`, `line-stuck.js`, `inbox.js`, 필요한 기존 markup/styles.
New tests: `operations/fleet/test/test_judgment_console_browser.py`; 기존 `test_console_roles_browser.py`, `test_console_queues_contract.py`, `test_line_stuck_api.py`.

화면에 현재 판단·근거/누락·담당/기한·알림 상태·실제 결과를 보여 주고 과거 사건은 당시 자료로 표시한다. 읽음, 담당 접수, 조치 수락, 실제 해소를 각각 확인한다. 소스 수정과 함께 해당 변경 범위의 G1/G2/G3를 수행한다. 정상/미개입/보류/위험·실패·자연 해소의 독립 검수 세트와 분모를 고정해 오개입·미개입·기권·지연·알림·복구/재발을 보고한다. install/runtime/실채널/DEVICE/FIELD 각각의 증거와 미확인을 receipt에 남긴다.

## 시험 명령과 완료 기록

각 단계는 테스트/구현을 소유 경로만 커밋한 뒤 원격으로 검증한다. 아래는 **현재 존재하는 출발점 suite**이며 새 테스트가 생기면 해당 단계 invocation에 추가한다. 브라우저는 별도 원격 scope invocation으로 분리한다.

```powershell
python tools/remote/remote_pytest.py --log-dir X:/DevTemp/<session>/logs/fleet -- operations/fleet/test/test_line_stuck_evidence.py operations/fleet/test/test_line_stuck_api.py operations/fleet/test/test_ai_facts.py operations/fleet/test/test_stuck_resolver.py operations/fleet/test/test_stuck_resolver_loop.py operations/fleet/test/test_stuck_no_motion_fleet.py operations/fleet/test/test_mission_feedback_loop.py
python test/known_failures.py X:/DevTemp/<session>/logs/fleet/run-1.txt
python tools/remote/remote_pytest.py --log-dir X:/DevTemp/<session>/logs/situation -- operations/situation/test/test_incident_context.py
python test/known_failures.py X:/DevTemp/<session>/logs/situation/run-1.txt
python tools/harness/rosy_harness.py generate
python tools/harness/rosy_harness.py lint
```

이번 문서 변경 자체는 `test/test_network_topology_contracts.py`, `test/test_harness_contracts.py`를 원격 실행하고 known_failures와 비교한다. 구현 suite·모델 성능·실채널·장치 시험이 수행됐다고 보고하지 않는다.

단계 receipt에는 ADR/계약/정책 revision·커밋·평가 세트 hash·원격/브라우저 로그·설치 digest·실채널 및 owner/목표 readback·미해결 항목·다음 단계 허용 여부를 둔다. D-640은 이 receipt를 소비하며 중앙 판단 수용 부족을 모델 합의로 대신하지 않는다. 착지·push는 별도 사용자 지시 후 수행한다.
