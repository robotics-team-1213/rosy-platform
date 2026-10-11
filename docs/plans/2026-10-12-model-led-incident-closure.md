# 모델 주도 범용 관제·사건 종결 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 교체 가능한 여러 판정 모델이 사건을 판단·해결·확인·개선하고 사람은 최종 미해결 사건을 검토한다.

**Architecture:** Fleet은 사건·근거·원장과 실행 연결, Decision은 판정·비교·단계 선택, AI PC는 운영 추론, Model PC는 독립 평가를 담당한다. CORE의 안전 권한과 기존 공통 tool catalog/admission을 재사용한다. D-679의 한 번의 연결 시험 이후 독립 수용된 프로파일로 자동 처리를 확대한다.

**Tech Stack:** 기존 Python Decision/Fleet, SQLite journal/outbox, 공통 model tool contract/catalog, Qwen 로컬 추론, OpenCode GLM, 모델별 고정 어댑터, 독립 replay/evaluation.

---

## 통합 요구사항

2026-10-12 사용자 재확인: 이 문서와 활성 목표는 지금까지의 요구사항을 하나로 묶는다. 최종 목표는 범용 사건의 **판단 → 조건부 재평가 → 제한된 처리 → 결과 확인 → 최종 미해결 인수 → 실패 피드백 → 독립 평가 → 승격·복귀**다. 사람이 매 단계 승인하는 흐름 대신 승인된 범위에서는 모델이 처리하고 사람은 최종 문제와 평가 정답·한계를 검수한다. 첫 현장 대상은 Pinky 차선 정지·재관측이며 이후 문제 유형은 각자의 근거·행동·성공 계약을 수용한 뒤 확대한다.

### 현재 시작점과 다음 순서

최신 source checkpoint: D-696 인수 export와 D-697 독립 원장 소비자는 commit `3a431bbc53e3caf15bbad68f0d64f4740bb1724e`로 로컬 main에 착지했다. 적격 AI PC 9GB의 관련 12개 파일 원격 통합 시험 219개, known-failures 신규 실패 0건과 lint를 통과했다. 인수 근거와 독립 소비자에 대한 독립 검토의 중요 지적은 수정했다. 고정 로그는 `X:/DevTemp/projects/rosy-platform/2026-10-12--033443--deliberation-local-gateway--fc42b3/logs/operational-land-3a431bbc53/run-1.txt`다.

소비자는 실제 paired export의 원장 상태 건수·한계 비용·UNKNOWN 예약 책임과 고정 cohort를 연결한다. 누락·변조·학습/보정/평가 ID와 원본 hash 중복, budget·종결 상태 모순을 거절한다. 기존 export /1과 선택 /2, 직접 producer 객체와 단독 JSON CLI를 유지한다. 단독 CLI는 설치된 contract wheel 없이 source checkout에서도 동작한다. 모든 출력은 HOLD이며 관측 종료를 인과적 성공률로 표시하지 않는다.

아래 3의 근거 생산과 4의 첫 소비자는 구현됐지만 전체 운영 성과 비교는 미완료다. 규칙·Qwen 단독 생산 기준, 독립 정답·수용 한계, 정상 명령과 재발의 완전한 기록 범위, 실제 청구·런타임 수용이 여전히 필요하다. 실제 제공자·독립 품질·운영 활성화·현장 수용과 push는 이 checkpoint에 포함하지 않는다.

| 순서 | 작업 | 완료 증거 |
|---|---|---|
| 1 | 소유자 확인·모델 원장 도구 분리·작업 규칙 추출 | 기존 책임·import·패키지 경계와 원격 회귀 유지 |
| 2 | 중앙 판단·결과 연결 | Fleet/Qwen 불일치·응답 문제에서 제한된 GLM 재평가; 같은 사건·근거·예산 결속 |
| 3 | 알림·최종 사람 인수의 실제 근거 export | D-696 동일 snapshot 검증; queue·전송 수용·claim 구분; Discord 설정은 담당 세션 |
| 4 | 독립 운영 성과 비교 | D-697 규칙/기본 모델/조건부 검토의 같은 cohort 비교; 정상 명령·재발·비용 증거 누락은 HOLD |
| 5 | 제한 모델 토론·개선과 승격·복귀 | 고정 프로파일과 보정 기준, 독립 회귀·운영 readback·새 사건 활성 revision |

기존 1·2의 source 구현과 비용·실패 분류 연결은 로컬 main에 있으며 실제 제공자·운영 활성화·현장 수용은 완료하지 않았다. 3의 인수 근거 생산부터 이어서 구현한다. GLM은 기본 Qwen 호출 도구가 아니라 조건부 재평가 경로다. Jev·Laya 등은 동일 역할 계약의 프로파일로 교체하며 Fleet에 모델별 판단 분기를 추가하지 않는다. 독립 운영 평가의 책임·자료 생산·누락 기준은 [D-697](../adr/D-697-independent-operational-comparison.md)로 고정한다. 아래 과거 checkpoint는 당시 증거이며 최신 상태와 구분한다.

| 요구 | 책임과 완료 증거 |
|---|---|
| 판단·현장 연결·설치 분리 | 모듈 import 경계·소유자·원격 회귀 |
| 정상 상황 미개입 | 정상 입력에서 모델/명령 0회, 미개입 종결 원장 |
| 정지·문·암 등 범용 사건 | domain별 승인 schema·근거·성공 확인 계약 |
| Fleet·Qwen 불일치 GLM 검토 | 동일 사건 바인딩과 제한된 호출 원장 |
| 확률 JSON과 모델 자동 처리 | schema conformance + 독립 calibration + 기존 admission |
| Jev·Laya 등 모델 교체 | 역할 프로파일 교체 시험; 실행 중 사건 revision 고정 |
| 사람 최종 검토와 팀 알림 | 예산 소진/지원 불가/결과 불명 인수; 전송과 인수 readback |
| 자체 개선 | 실패 원인→검수→분리된 학습/평가→회귀 비교→승격/롤백 |
| 실제 성공과 증거 구분 | 소스/원격/호스트/제공자/독립 품질/배포/현장 개별 receipt |

## Phase 0: 현재 요구와 책임 고정

Record: D-679, D-681와 이 계획. 기존 `docs/plans/2026-10-11-fleet-deliberation-loop.md`, 책임 분리 계획 및 Model PC 평가 계약을 함께 읽는다. 실제 소스·서비스·운영 프로파일 소유자를 확인한다. Discord 설정은 담당 세션에 남긴다.

## Phase 1: 동일 사건의 조건부 판정

Execute: `2026-10-12-conditional-fleet-qwen-glm-review.md` Task 1.

- `operations/decision/src/rosy/decision/deliberation/`: 기본 의견·Fleet 불일치·검증된 prior·조건부 재평가.
- `operations/fleet/fleet/server/incident_deliberation.py`: scoped Fleet 기준과 현재 값 확인.
- `operations/fleet/fleet/server/deliberation_journal.py`: 정책/사건/예산 재사용 금지.

먼저 RED → 최소 구현 → 커밋 HEAD 원격 GREEN → known_failures 비교 → 독립 검토 → 승인된 로컬 착지. 현재 Assessment에 처리 방향이 없으면 값을 추정하지 않는다. 비교 기준 생산은 실제 Fleet 규칙 결과의 의미를 검토한 뒤 연결한다.

## Phase 2: 실제 제공자 한 번과 교체 경계

Execute: 같은 계획 Task 2–3. 고정 GLM 요청·전용 계정·secret 비노출·namespace·시간/출력/호출 한도를 확인한다. Qwen은 직접 기본 추론으로 유지한다. Jev/Laya는 공통 제공자 계약으로 역할별 프로파일을 정의한다. 정확한 설치 모델·지원 입력·비용·격리·schema가 없는 프로파일은 미수용 상태로 둔다. 모델 종류별로 Fleet 코드에 분기하지 않는다.

## Phase 3: 확률 판정 JSON과 독립 보정

Extend: 기존 `operations/decision/src/rosy/decision/model_tool_contract.py`, `model_tool_catalog.py`, `deliberation/` 경계를 읽고 D-681 판정 계약의 별도 버전을 추가한다. 기존 D-640 parser는 유지한다. probability sum/NaN/중복/다른 사건/없는 evidence/없는 calibration/초과 출력 RED 시험을 먼저 작성한다.

Evaluation: `tools/decision_replay.py`, 기존 `operations/fleet/test/test_deliberation_replay.py`와 Model PC 독립 평가 경로를 재사용한다. 모델 revision·문제 유형별 실측 선택 정확도·보정 오차·확률 구간별 신뢰도를 계산한다. 팀은 정답과 평가 한계를 최종 검수한다. 0.95/0.20 초기 기준을 실측 확인 없이 자동 처리 승인으로 기록하지 않는다.

## Phase 4: 모델 주도 처리·결과 확인

Read/extend: 기존 Fleet model-feedback dispatcher, Mission journal 및 `operations/fleet/fleet/stuck/pipeline.py`의 admission 경계. allowlisted 관측·처리 단계를 모델이 선택하고 매 단계의 현재 사건·안전·예산을 다시 확인한다. CORE 명령 경로를 새로 만들지 않는다. 실제 처리 후 현재 상태 readback과 성공 근거로 종결한다. 결과 불명·재시작·다른 사건·사람 점유에서 재발행을 거부하는 시험을 넣는다.

## Phase 5: 사람 최종 인수와 팀 전달

기존 outbox·사건 원장을 재사용한다. 단순 낮은 확률을 즉시 사람에게 넘기지 않고 허용된 근거 수집/다른 모델 검토를 먼저 수행한다. 최종 예산 소진·지원 불가·결과 불명에 사건 요약·판정 차이·시도·현재 위험·필요 검토를 전달한다. Discord 세션과 상태/중복 키/인수 계약을 맞추고 Slack·Telegram 어댑터에도 같은 계약을 적용한다. 외부 실제 발송은 사용자가 지정한 경로와 설정에서만 수행한다.

## Phase 6: 실패 피드백과 제한된 개선

Reuse: `learning/curation/perception/incident_feedback.py`, 기존 독립 replay 및 registry promotion 경계. 실패 원인을 판정/관측/지도/설치/장치로 분리하고 팀 검수 결과를 기록한다. 개선 후보를 과거 문제와 새 문제에 비교해 위험·정상 개입·종결·지연·비용 회귀를 검사한다. 승격은 고정 프로파일 revision으로 수행하고 진행 중 사건과 원래 원장/예산은 유지한다.

## 실행 상태 (2026-10-12)

Phase 0·1의 ADR·조건부 검토 source는 로컬 main에 착지했다. Phase 2의 GLM 영속 1회 표식과 Phase 3의 v2 프로파일·판정·공통 CLI 요청·독립 보정은 `daccbd38be`로 로컬 main에 착지했다. 보정은 모델 프로파일 전체 SHA-256에 고정하며 모델·역할·어댑터·한도 변경 시 다시 수용해야 한다. 원격 component 증거와 미확인 범위는 `../validation/deliberation-host-admission-2026-10-12/versioned-judgment.md`에 둔다.

실제 GLM 첫 호출은 관리자 설치 명령을 준비했으며 실행 receipt를 아직 확인하지 못했다. Phase 4~6의 운영 루프·최종 인수·개선 승격과 현장 수용은 완료하지 않았다.

Phase 4의 선택적 읽기 전용 worker와 Phase 5의 최종 실패 outbox 연결은 작업 브랜치 `c41fbba181`에서 관련 9개 파일 원격 시험 151개와 신규 실패 0건을 확인했다. 이어 실제 원장 구현을 `automation/ledger`로 분리하고 기존 import 경로·클래스 identity를 유지했다. 실제 wheel/sdist 설치·책임 크기·기존 resolver loop를 포함한 15개 파일 원격 시험 375개, known-failures 신규 실패 0건, lint를 통과하여 `819a6e3140`으로 로컬 main에 착지했다. 호출·관측·비용 한도와 사건/정책 고정, 취소·재시작·사람 점유·다른 사건·새 관측 검사를 포함한다. 실제 서비스 factory와 수용 프로파일 연결, 실제 Fleet 규칙의 동등한 비교 기준 생산, 물리 처리 admission과 현장 종결 증거는 아직 없다. worker 기본값은 비활성이다. 다음 연결 순서는 [실제 런타임 수용 계획](2026-10-12-incident-runtime-admission.md)에 기록했다.

Phase 6의 단일 사건 읽기 전용 export와 기존 녹화 feedback 연결은 `9078a72586`으로 로컬 main에 착지했다. 관련 6개 파일 원격 시험 185개와 known-failure 비교에서 신규 실패 0건을 확인했다. 현재 모델 자료는 `UNREVIEWED`이며 팀의 정답·현장 수용·훈련 데이터로 자동 승격하지 않는다. 판정 JSON의 확률과 원래 입력을 비용 기록과 함께 고정하는 작업, 독립 후보 비교, 승격·복귀는 후속 작업이다.

후속 브랜치 `e0666b3e3f`에서 검증된 원래 입력·판정·전체 프로파일을 원장의 실제 시도 비용과 연결하고 export 재검증을 추가했다. OpenCode GLM v2 요청·prior·응답을 공통 판정 계약에 연결하며 기존 v1 설치 경로를 유지했다. 실제 설치 패키지·모듈 책임 경계를 포함한 9개 파일 원격 통합 시험은 적격 Model PC 9GB에서 204 passed, exit 0이다. 실제 런처 비용 receipt·운영 수용 연결과 provider/독립 품질/배포/현장 증거는 별도로 남아 있다. 이 source 시험은 모델의 정확도나 현장 종결을 증명하지 않는다.

## 완료 기준

최신 checkpoint: 기존 사건 원장과 resolver loop에 선택적 모델 worker를 구성하는 factory, 최종 검토 outbox 연결, GLM v2 의존성/import closure는 commit `3e2f3b9fdab4bfabbdf28eb665a0cd184591446f`로 로컬 main에 착지했다. D-685 자율 복구 변경을 함께 보존한 13개 관련 파일 원격 통합 시험은 적격 Model PC 7.3GB에서 288 passed, exit 0, known-failures 신규 실패 0건이며 lint도 통과했다. 로그는 `X:/DevTemp/land/feat-conditional-model-review/run-1-1.txt`다. 기본 비활성·같은 DB·사람 점유 차단·UNKNOWN/재발행 거부 경계를 유지한다. 위의 과거 checkpoint에서 미구현으로 적었던 factory는 이제 source 구현되었으며, 실제 서비스 설정과 수용 프로파일 연결은 여전히 남아 있다.

AI PC의 임시 비특권 환경에서 해시 고정 wheel의 오프라인 설치, pip 의존성 검사, v2 import/codec probe가 exit 0과 `PASS_V2_IMPORT_CODEC_ONLY`로 끝났다. 모델 호출은 0회이며 root 설치·서비스 계정 격리·실제 제공자·과금·독립 품질·현장 수용을 증명하지 않는다. 설치 묶음과 실제 확인 범위는 [import closure 기록](../validation/deliberation-host-admission-2026-10-12/versioned-import-closure.md)에 둔다. 다음 작업은 상세 비용 증거를 공통 사건 원장에 연결하고, 실제 Fleet 비교 기준과 수용된 제공자·보정 프로파일을 구성하는 것이다. Discord 설정은 담당 세션이 유지한다. 목표는 아직 진행 중이며 푸시·운영 활성화는 수행하지 않았다.

2026-10-12 checkpoint: Phase 2·3과 Phase 4의 예산 원장·기존 관측 읽기 포트는 `daccbd38be`로 로컬 main에 착지했다. 원격 24개 관련 파일의 364개 source 시험과 known-failure 비교에서 신규 실패 0건을 확인했다. 판단 계약·provider 연결·독립 평가를 실제 하위패키지로 분리했으며 기존 부모의 크기 기준과 +150 한도를 유지했다. 푸시·배포·실제 GLM·현장 수용은 포함하지 않는다. worker·최종 사람 인수 연결은 별도 작업 중이다. Phase 6의 구체적 실행 순서는 [실패 피드백·개선 계획](2026-10-12-model-improvement-feedback.md)에 기록한다.

각 단계의 소스·원격·호스트·실제 제공자·독립 품질·배포·현장 증거를 구분한다. 모델 간 합의나 JSON 성공만으로 현장 완료를 선언하지 않는다. 관측 부족·위험 누락·다른 사건에 조치·정상 불필요 명령 0건 수용 기준은 유지한다. 모델 교체 시 같은 계약/근거/안전/종결 검증이 그대로 통과해야 한다.
