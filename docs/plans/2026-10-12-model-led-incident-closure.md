# 모델 주도 범용 관제·사건 종결 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 교체 가능한 여러 판정 모델이 사건을 판단·해결·확인·개선하고 사람은 최종 미해결 사건을 검토한다.

**Architecture:** Fleet은 사건·근거·원장과 실행 연결, Decision은 판정·비교·단계 선택, AI PC는 운영 추론, Model PC는 독립 평가를 담당한다. CORE의 안전 권한과 기존 공통 tool catalog/admission을 재사용한다. D-679의 한 번의 연결 시험 이후 독립 수용된 프로파일로 자동 처리를 확대한다.

**Tech Stack:** 기존 Python Decision/Fleet, SQLite journal/outbox, 공통 model tool contract/catalog, Qwen 로컬 추론, OpenCode GLM, 모델별 고정 어댑터, 독립 replay/evaluation.

---

## 통합 요구사항

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

Phase 0·1의 ADR·조건부 검토 source는 로컬 main에 착지했다. Phase 2의 GLM 영속 1회 표식과 Phase 3의 v2 프로파일·판정·공통 CLI 요청·독립 보정은 작업 브랜치에 통합했으며 통합 시험·착지는 확인 후 기록한다. 보정은 모델 프로파일 전체 SHA-256에 고정하며 모델·역할·어댑터·한도 변경 시 다시 수용해야 한다. 원격 component 증거와 미확인 범위는 `../validation/deliberation-host-admission-2026-10-12/versioned-judgment.md`에 둔다.

실제 GLM 첫 호출은 관리자 설치 명령을 준비했으며 실행 receipt를 아직 확인하지 못했다. Phase 4~6의 운영 루프·최종 인수·개선 승격과 현장 수용은 완료하지 않았다.

## 완료 기준

각 단계의 소스·원격·호스트·실제 제공자·독립 품질·배포·현장 증거를 구분한다. 모델 간 합의나 JSON 성공만으로 현장 완료를 선언하지 않는다. 관측 부족·위험 누락·다른 사건에 조치·정상 불필요 명령 0건 수용 기준은 유지한다. 모델 교체 시 같은 계약/근거/안전/종결 검증이 그대로 통과해야 한다.
