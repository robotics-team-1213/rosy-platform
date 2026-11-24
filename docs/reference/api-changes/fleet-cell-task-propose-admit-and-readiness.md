---
surface: fleet
kind: additive
slug: fleet-cell-task-propose-admit-and-readiness
date: 2026-11-23
title: Fleet cell-task PROPOSE/admit CAS, interlock_scope, and cell readiness
---

- `POST /api/fleet/pipeline/cell-tasks`: opened to `proposer_guard` (`service` creates `PROPOSED` tasks; `operator` creates `QUEUED` or `PROPOSED`), supports `request_key` / `Idempotency-Key` replay scoped per principal (`409 IDEMPOTENCY_CONFLICT` on body mismatch), server-derives `interlock_scope` (`"amr_bed"` or `"cell_internal"`; `_ready_amr` currently stays fail-closed across scopes), rejects client-spoofed `proposer` (`422`), enforces single retry + chain depth `<= 2` (`409 FALLBACK_RETRY_LIMIT_EXCEEDED`), and rejects automatic/non-terminal `act_policy` -> `guarded_pick` swaps (`403`/`409`).
- `POST /api/fleet/pipeline/cell-tasks/{task_id}/admit`: human-operator-guarded single-transaction SQLite `BEGIN IMMEDIATE` CAS transition from `PROPOSED` to `QUEUED` requiring named human operator (`403 NAMED_OPERATOR_REQUIRED`), distinct proposer != approver (`403 SELF_APPROVAL_FORBIDDEN`), and required matching `expected_readiness_digest` / `expected_dispatch_generation` / `expected_stop_generation` (plus `expected_context_sha256` when bound to a failure bundle; `409 STALE_FAILURE_CONTEXT`).
- `POST /api/fleet/pipeline/cell-tasks/{task_id}/cancel`: allows cancelling `PROPOSED` as well as `QUEUED` tasks and bumps `dispatch_generation`.
- `GET /api/fleet/pipeline/cells/{cell_id}/readiness`: `read_guard` endpoint returning `rosy.fleet-cell-readiness.v1` with `authority_epoch`, `dispatch_generation`, `stop_generation`, per-arm holds, task counts, and `readiness_digest`.
- `operations/decision/src/rosy/decision/model_tool_catalog.py`: adds `scope="cell"` closed schemas (`get_cell_readiness`, `get_cell_failure_context`, `propose_cell_fallback` aligned to canonical `FALLBACK_VERBS` + CAS fields); `contracts/foundation/core_common/intent.py` extends `FORBIDDEN_KEYS` with low-level arm and PLC actuator keys.
