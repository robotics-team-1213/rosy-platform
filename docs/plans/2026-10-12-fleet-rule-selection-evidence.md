# Fleet 실제 규칙 선택 근거 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 실제 resolver 선택을 원장에 기록하고 의미가 일치하는 선택만 조건부 모델 검토의 기준으로 연결한다.

**Architecture:** selector 실행은 기존 Fleet resolver 하나다. loop가 실제 결과·Assessment를 결속하고 observe가 같은 DB에 저장한다. 독립 소비 가능한 JSON은 contracts.learning에서 검증하며 factory는 현재 기록의 읽기 포트만 연결한다.

**Tech Stack:** 기존 Python dataclass/SQLite, 공통 계약 wheel, 기존 Fleet 설치·원격 시험.

## 실행

1. `operations/fleet/test/test_rule_selection.py`에서 실제 정상/HOLD/HANDOFF pass, physical ANSWER 미변환, MIXED·stale·다른 사건·기록 실패 거절 시험을 먼저 추가하고 원격 RED를 확인한다.
2. `contracts/learning/src/rosy/contracts/learning/incident_rule.py`에 exact-field·finite·scope·kind·privacy 검증을 구현한다. 명령/모델/결과 건수를 추정하지 않는다.
3. `operations/fleet/fleet/observe/rules.py`에 동일 DB의 bounded append/read 원장을 구현한다. `stuck/pipeline.py`와 `stuck/loop.py`에서 실제 step 결과를 기록하며 모델 시작 전에 현재 기준을 교체한다. 기록 오류는 기존 dispatch를 중단하지 않고 비교 기준을 비운다.
4. `incidents/automation/runtime.py`에서 미지정 baseline만 현재 저장 선택 포트로 연결한다. physical/mixed/ABSTAIN/stale/다른 사건은 None이며 수동 기존 포트의 호환은 유지한다.
5. 커밋 HEAD를 적격 시험 PC로 보내 신규 실패와 비교한다. 실제 설치·기존 resolver/model loop·holder/크기를 확인하고 독립 검토 후 승인된 local landing을 한다. 전체 map/lifecycle provenance·규칙 전략 export/독립 cohort 비교·배포·현장 수용은 후속이며 목표 완료로 바꾸지 않는다.
