---
title: mutation 증명 탐침은 safety 태그 경로 밖에서 찍는다
date: 2026-11-01
category: workflow-issues
module: test/architecture (신규 가드 추가), tools/land.py (D-430 §5 Safety-Review 게이트)
problem_type: workflow_issue
component: development_workflow
severity: medium
root_cause: process_interaction
resolution_type: process_change
symptoms:
  - "D-940 후속 브랜치의 mutation probe 커밋(78e7a05dde)이 operations/fleet/fleet/server/ledger/task_dispatch_routes.py에 임시 필드를 넣었다가 초록(3359 passed)에도 착지가 STOP했다"
  - "probe 커밋과 그 revert(cb59bedf6f)가 각각 `Safety-Review:` 트레일러를 요구받았다 — 임시 커밋에 트레일러를 달 수는 있어도 독립 리뷰를 동반하지 못한다"
---

## 증상

새 구조 시험(mutation 증명 규칙, `test/AGENTS.md`)을 추가할 때 probe를 `concern: safety` 경로에 박으면,
시험 자체는 초록이어도 `land.py`의 D-430 §5 검사가 probe·revert 커밋 각각의 `Safety-Review:` 트레일러와
독립 리뷰를 요구해 착지가 멈춘다. 2026-11-01 D-940 후속 착지에서 실제로 발생했다.

## 원인

두 규칙의 교차다. 신규 가드는 mutation 증명 없이 믿지 않고(옳다), D-430 §5는 safety 태그 경로를
건드린 **모든** 커밋에 트레일러를 요구한다. probe는 원래 임시·폐기 대상이라 이 요구를 충족할 수 없다.
같은 날 D-940 게이트 자체의 probe는 `deploy/site/fleet-mdns.py`와 learning geometry에 찍어 아무 충돌 없이
통과했으므로, 문제는 probe의 위치 선정이지 두 규칙 어느 쪽도 아니다.

## 해결

- **예방**: probe를 찍기 전에 `tools/harness/platform_parts.yaml`의 `concern: safety` root와
  `safety_modules`를 먼저 본다. 가드가 지켜야 하는 대상이 safety 경로 안에만 있다면, probe는
  등록부·시험 더미처럼 safety 밖의 동등한 대상으로 증명한다.
- **복구(이미 걸렸을 때)**: mutation 커밋을 떼고 본체만 새 브랜치로 재구성한다 —
  `git checkout -b <branch>-b main` 후 본체 커밋을 cherry-pick(충돌은 docs/logs.md·생성물은
  main 쪽+재생성, 표는 union). 빨간불 증거는 probe 커밋 SHA의 원격 실행 기록으로 이미 유효하므로
  착지 브랜치에 probe가 없어도 증명으로 인정된다.

## 검증 근거

- 초록: `6aa4000879` 원격 affected 3359 passed/485 skipped/NEW 0.
- 빨강: `78e7a05dde` 원격 `test_rest_model_mirror.py` exit 1, `probe_field`를 정확히 지목.
- 재브랜치 착지: `e373c7b615`(본체만) → main 반영 확인(`main:test/architecture/test_rest_model_mirror.py`).
- `safety_review.py`는 동작 그대로 — 게이트를 약화하지 않았다.

## 다음에 적용할 조건

신규 가드·계약 시험을 mutation-prove하는 모든 착지에서. probe 파일 선정은 본체 커밋을 만들기 **전에**
safety 태그 확인과 함께 한다.
