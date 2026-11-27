---
surface: fleet
kind: additive
slug: fleet-cell-push-exec
date: 2026-11-28
title: Cell-task push executes, is auto-admitted and completes on measured displacement (D-1083)
history: [Fleet] Additive: push motion QUEUED like free_pick, claim capability "push", /complete needs stage_result.push
---
A `motion.kind == "push"` cell task (`POST /api/fleet/pipeline/cell-tasks`) is no longer proposal-only (owner decision 2026-11-28; amends D-1077 section 7 and D-1081). With the D-1078 switch on, a `service` principal that does not send `propose: true` gets `QUEUED` (`approval_mode: autonomous_policy`), exactly as for `free_pick`. Otherwise it is `PROPOSED` with `motion_admission: HUMAN_APPROVAL_REQUIRED`, and `POST .../{task_id}/admit` accepts it from a different named operator. `PUSH_NOT_EXECUTABLE` (create answer and `/admit` 409) is removed.

- A push task refuses `object_ref`, `identity`, `identity_observation_ref` and `emit_release_permit` (`422 MOTION_CONFLICTS_WITH_TASK_FIELDS`).
- `POST .../claim`: a push is handed only to a claim whose `capabilities` list both `"motion"` and `"push"`; otherwise `{"claimed": false, "reason": "WORKER_LACKS_PUSH_CAPABILITY"}` and the task stays `QUEUED`. `free_pick` still needs only `"motion"`.
- `POST .../{task_id}/complete` with `phase: RELEASED` for a push needs `stage_result.push` = `{result: "pushed", site, measured: true, commanded_mm, moved_mm, along_dir_mm, lateral_mm}` (exact keys, finite numbers): `commanded_mm` equals the task's `mm`, `along_dir_mm` between `0.5 x mm` and `1.5 x mm + 3`, `lateral_mm` between 0 and 6, `moved_mm` within 0.5 of `hypot(along, lateral)`. A push needs no `place` or zone `verification`; the usual `task_verified`, folded `stop_event` and owner-evidence checks still apply. Anything else is `422 UNVERIFIED_CELL_COMPLETION`.
- Cell job API (:8781): the `cell-task-worker` principal may start `push` with exactly `arm, config, site, roi, catalog, px_x, px_y, dir_x, dir_y, mm` (mm 5..20); any other key is `403 WORKER_SCOPE_FORBIDDEN`. `push` is not cancellable (`POST /jobs/<id>/cancel` answers `409 JOB_NOT_CANCELLABLE`). The `cell_push.py` result adds `displacement` and `park`.
