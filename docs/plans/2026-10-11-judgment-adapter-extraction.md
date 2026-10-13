# Judgment Adapter and Pure Execution Extraction Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** D-648 단계 2 및 단계 3 첫 계산 단위를 분리하고 기존 실제 원장·권한·설치 결과를 보존한다.

**Architecture:** D-657에 따라 원장 모델 도구는 Fleet 어댑터, 목표 검증과 진척 시각/상태 계산은 기존 execution/site wheel이 소유한다. Mission 상태 전이와 I/O·인증·claim·generation fence는 Fleet에 유지한다.

**Tech Stack:** 기존 Python stdlib, 기존 wire 타입, static source mapping, setuptools wheel/sdist, committed-head 원격 pytest. 새 서비스·dependency library·추상 port framework는 없다.

**Start:** `063676cbcb`, branch `refactor/judgment-adapter-extraction`.

**Status:** 단계 2 및 단계 3 첫 단위의 소스·설치 분리 구현 `fb2e5e07d3`, 원격 212 passed / NEW 0 및 독립 소스 리뷰 승인. 최신 main 착지 검사는 후속이며 [검증 기록](../validation/judgment-adapter-extraction-2026-10-11.md)에서 증거를 구별한다.

## 1. 계약과 RED 고정

- `test/test_judgment_extraction.py`에 canonical module, Decision의 Fleet import 금지, DB/HTTP/ROS 없는 execution import/호출과 상태·시각 경계 사례를 고정한다.
- `test/test_remaining_platform_installed.py`의 양쪽 import 순서, 실제 wheel과 self-contained Fleet sdist/source Docker COPY fixture를 새 namespace에 맞춘다. execution 파일은 기존 wheel에서만 설치하고 Fleet distribution과 겹치지 않는지 확인한다.
- ADR·Log·계획과 시험만 exact-path stage/commit 후 원격 RED를 실행한다. 설치 입력 변경 전의 실제 누락 실패를 보관한다.

## 2. 원장 결속 dispatcher 이전

- `operations/decision/src/rosy/decision/tool_dispatch.py` → `operations/fleet/fleet/server/model_feedback_dispatch.py`; 원본 byte/AST 보존.
- `operations/fleet/test/test_er2_tool_dispatch.py`와 설치 probe의 실제 import 변경. `rg` 결과 현재 생산 코드는 dispatcher를 주입받으며 신규 조립/서비스를 만들지 않는다.
- `test_er2_tool_dispatch.py`, `test_model_tool_call_journal.py`, `test_model_tool_adapter_conformance.py`, `test_mission_ai_proposal.py`, `test_mission_feedback_loop.py`로 기존 scope·fence·same transaction·늦은 결과 거절을 검증한다.

## 3. 순수 목표·진척 첫 단위

- `operations/fleet/fleet/server/goal_evidence.py` → `operations/execution/src/rosy/execution/site/goal_evidence.py`; 원본 byte/AST 보존.
- `mission_service.py`, `mission_store.py`, `goal_evidence_service.py`, `test_goal_evidence.py`의 import를 함께 변경한다. GoalEvidence producer 인증/후속 frame·attempt 검사는 기존 서비스에 남긴다.
- `mission_progress.py`의 `_timestamp`, `_freshness`, 기존 freshness 상수와 step-state mapping을 `workflow.py`로 추출한다. 기존 함수 본문과 결과를 보존하고 adapter는 동일 clock/store에서 호출한다. 다른 상태 전이·복구 규칙은 이번 단위에 포함하지 않는다.
- `operations/fleet/setup.py`에 기존 execution wheel dependency를 선언한다. `_source_layout.py`/Fleet source bootstrap, site Docker COPY/allowlist, source image probe를 함께 변경한다. Fleet 빌드 helper는 execution을 중복 포장하지 않는다.
- existing `test_goal_evidence*`, `test_mission_service.py`, `test_mission_progress.py`, `test_mission_store.py`, 관련 cell/dispatcher 회귀와 standalone 설치 시험을 원격 실행하고 NEW 0을 확인한다.

## 4. 책임표·기록·착지

- 양쪽 AGENTS·execution 안내·manifest note·현재 folder 책임표를 실제 소스로 갱신한다. ADR D-648의 원래 Proposed 이력은 재작성하지 않고 D-657의 제한 수용을 후속 링크로 기록한다.
- `docs/validation/judgment-adapter-extraction-2026-10-11.md`에 소스 이동·독립 import·원격 terminal 결과·남은 gate를 기록하고 journal/생성 문서를 함께 갱신한다.
- 사용자 세션의 중간 commit/main merge 요청에 따라 원격 검증 후 `tools/land.py --tests auto`로 최신 main에 FF 착지한다. push·배포·모델 활성화·장치 실행은 이번 요청에서 진행하지 않는다.

원격 로그는 관리 세션의 `logs/<stage>/run-1.txt`에 남기고 각 실행마다 `test/known_failures.py`로 비교한다. 노트북 pytest는 실행하지 않는다. 실패를 known 목록에 추가하거나 크기 기준/예외를 확대하지 않는다.
