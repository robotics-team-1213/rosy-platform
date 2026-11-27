---
surface: fleet
kind: additive
slug: autonomous-cell-dispatch
date: 2026-11-27
title: 자율 무승인 셀 작업 투입 및 입회 면제
history: Additive: ROSY_FLEET_AUTONOMOUS_CELL_DISPATCH=1 시 POST /api/fleet/pipeline/cell-tasks 즉시 QUEUED 투입 및 claim 입회 면제
---
Additive (v1.next): 사이트 환경변수 `ROSY_FLEET_AUTONOMOUS_CELL_DISPATCH=1` 활성 시 `POST /api/fleet/pipeline/cell-tasks`가 `propose: true`가 없으면 `service`/`ai_observer` 주체와 AI 폴백도 즉시 `QUEUED`(`approval_mode=autonomous_policy`)로 투입하며, `POST /api/fleet/pipeline/cell-tasks/claim`은 `requires_presence_confirm` 미설정 작업의 `PRESENCE_CONFIRMATION_REQUIRED` 검사를 생략한다. 기본값(`0`)은 기존 `PROPOSED` + 기명 운영자 승인 동작을 유지한다.
