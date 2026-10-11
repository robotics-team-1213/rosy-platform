# 실제 규칙 원장 export와 독립 비교 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 실제 규칙 선택과 모델 원장을 같은 사건 cohort로 독립 비교하면서 미확인 운영 결과는 HOLD로 남긴다.

**Architecture:** `learning/curation/pinky/fleet_rules.py`가 기존 SQLite를 읽고 신규 JSON만 쓴다. 기존 `learning/evaluation/decision/operational_comparison.py`의 /1 검증을 재사용하며 /2에 별도 규칙 후보를 추가한다. 공통 D-700 JSON 계약을 재사용하며 Fleet을 import하지 않는다.

**Tech Stack:** Python stdlib sqlite3/hashlib/JSON, existing contracts.learning.

## Source checkpoint

2026-10-12 commit `410d69f8e72ed223fcfba9f52982c8df4bd34294`를 로컬 main에 착지했다. 적격 AI PC 9GB의 관련 26개 파일 원격 통합 시험 667 passed, terminal exit 0, known-failures NEW 0과 lint를 확인했다. 실제 resolver 원장→읽기 전용 export→동일 사건 모델 cohort→독립 `python -I -S` 비교 CLI와 기존 /1·primary /3·구조·release 검사를 포함한다. 고정 로그는 세션 `logs/rule-export-land-410d69f8e7/run-1.txt`다.

독립 검토의 전체 JSON 크기·CLI 연결 지적을 수정했고 정확한 크기 경계와 덮어쓰기 거절을 시험했다. 이전 통합 655 passed/1 failed의 가짜 키 시험 표식도 검사 규칙을 유지한 채 수정했다. 규칙 기록은 retained-only이며 결과·비용·호출·명령·재발은 null이다. 전체 목표는 ACTIVE다. 실제 모델 품질·독립 정답과 한계·운영 coverage·승격/복귀·배포·현장 수용과 push는 이 checkpoint에 포함하지 않는다.

1. `test/learning/decision/test_rule_operational_comparison.py`에 실제 resolver 원장·기존 model export의 연결과 source 없는 CLI·변조/누락/범위 회귀를 작성하고 committed HEAD 원격 RED를 확인한다.
2. curation export는 explicit scope/time bounds·read-only WAL transaction·행/전체 hash·credential-free canonical JSON을 검증한다. 정상 case null을 가짜 사건으로 만들지 않는다. partial retention은 retained-only로 표시한다.
3. 독립 compare /2는 rule 후보와 model 후보의 같은 evaluation 사건 집합을 결속하고 기존 split 누출·digest·scope·budget 검증을 유지한다. NONE/ANSWER/HOLD/HANDOFF와 necessity를 기록하되 운영 결과/비용 0을 추정하지 않는다.
4. 기존 /1·단독 primary /3·writer/import/크기 회귀를 원격 시험하고 독립 검토 후 승인된 local landing을 한다. 독립 정답/수용 한계·완전한 명령/호출/재발 coverage·전략 provenance·승격/복귀·실제 모델/배포/현장은 후속이다.
