---
surface: fleet
kind: additive
slug: fleet-task-reconcile-unknown
date: 2026-11-22
title: 미확정 작업 정지 증거 기반 운영자 정산
history: Additive (D-1071): named-operator POST /api/fleet/tasks/{task_id}/reconcile releasing UNKNOWN task claims only after live CORE cancel and D-732 quiescence proof
---
Named operators may reconcile an `UNKNOWN` navigation task via `POST /api/fleet/tasks/{task_id}/reconcile` (v1.next, D-1071). Bound native runs check live CORE readback reachability (`503 CORE_QUIESCENCE_UNAVAILABLE` without mutating task state when unreachable) and delegate to D-732 `task_result` readback; unbound tasks issue `navigation/cancel`, require a fresh (`<=2 s`) CORE `GET /api/v1/navigation/state` full D-732 `quiescence` proof (`lookup="FOUND"`, `navigation in {IDLE, ARRIVED, CANCELED, FAILED}` rejecting `PLANNING`/`NAVIGATING`/`BLOCKED`, `operation.phase="TERMINAL"`, `requested_run_id=operation.run_id`, `quiescent=true`, `owner_run_id=null`, all in-flight flags `false`) or zero-run boot proof (`lookup="UNKNOWN"`, `operation=null`, `quiescence=null`, `owner.owner_run_id=null`, `navigation="IDLE"`), and CAS-transition to `HOLD(OPERATOR_RECONCILED_QUIESCENT)` while releasing only that task's dispatch generation claim.
