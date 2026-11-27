---
surface: cell
kind: additive
slug: cell-job-cancel
date: 2026-11-28
title: Cell job cancel as a cooperative stop (D-1081)
history: [Cell] Additive: POST /jobs/<id>/cancel
---
`POST /jobs/<id>/cancel` (cell job API, empty body) asks a running, moving `auto_pick` to stop at its next guarded step: the API writes a per-job stop marker, `Guarded.act` sees it and takes its existing park-and-abort path with torque ON. It sends no signal and kills nothing, and it is not an emergency stop: an in-flight chunk finishes first.

- Allowed: the human principal, or the principal that started the job (the `cell-task-worker` principal may cancel only its own job). Another principal gets `403 CANCEL_FORBIDDEN`.
- `200` with the job state and `cancel_requested` (true while it runs). Repeating it is idempotent; the first request is one `cancel_requested` row in `audit.jsonl`. A finished job returns its state and writes nothing (`cancel_requested: false`).
- `404` for an unknown id; `409 JOB_NOT_CANCELLABLE` for a job without a cooperative stop (every job except a moving `auto_pick`).
- The marker is removed when the job is reaped. The child sees its path in `ROSY_CELL_JOB_STOP_FILE`; a run without it (direct or manual) behaves as before.
