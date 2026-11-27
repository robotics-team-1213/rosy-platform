---
surface: fleet
kind: additive
slug: fleet-cell-task-motion
date: 2026-11-27
title: Fleet cell-task motion, claim capabilities and cell job worker principal (D-1081)
history: [Fleet] Additive: cell-task motion object (free_pick, push), claim capabilities, cell-task-worker scope
---
`POST /api/fleet/pipeline/cell-tasks` accepts an optional `motion` object (cell `cell_ab` only; D-1081). Pixels only, no metres; an unknown or missing key is `422 INVALID_CELL_MOTION`.

- `{"kind":"free_pick","anchor_site","at_px":[x,y],"dst_site","frame_seq","frame_sha256","object"?,"colour"?}`: pick the object at pixel `at_px` near `anchor_site` and place it at `dst_site`. `src_site`/`dst_site` of the task are taken from the motion. `frame_seq` and `frame_sha256` are an audit record only; the cell re-measures at execution and refuses when no measured blob lies at `at_px`.
- `{"kind":"push","site","px":[x,y],"dir":[dx,dy],"mm":5..20,"frame_seq","frame_sha256"}`: always `PROPOSED` (`motion_admission: PUSH_NOT_EXECUTABLE`); `.../admit` refuses it with `409 PUSH_NOT_EXECUTABLE`.

Refusals: `422 INVALID_CELL_MOTION`, `MOTION_CELL_NOT_SUPPORTED` (not `cell_ab`), `MOTION_CONFLICTS_WITH_TASK_FIELDS` (`preset`, `tiers`, `directive`, `displaced_to`, `depends_on`, `tier_hint`, `max_chunks` or a non-`guarded_pick` mode), `UNKNOWN_CELL_SITE`, `MOTION_SITE_CONFLICT`. A `retry` or ACT fallback of a motion task is `409 CORRELATED_PLACEMENT_REQUIRES_NEW_PLAN`; repark never rebuilds a motion (`MOTION_NOT_REPARKED`).

Admission: a `free_pick` is `QUEUED` (`approval_mode: autonomous_policy`) only when the D-1078 switch is on, the creator is a `service` principal and `propose` is not set. Every other creator gets `PROPOSED` (`motion_admission: HUMAN_APPROVAL_REQUIRED`) and a different named operator must `/admit` it.

Claim: the claim body may carry `"capabilities": ["motion"]`. A claim for a motion task without that marker returns `{"claimed": false, "reason": "WORKER_LACKS_MOTION_CAPABILITY"}`; the task stays `QUEUED`.

Cell job API: a worker principal `cell-task-worker` (own token file, off when absent) may start only `auto_pick` with `source` `free:<site>`, `map_only: true`, `at_px`, no `reviewed_auto`, and only these keys: arm, config, catalog, roi, source, dest, at_px, map_only, object, colour, verify_zones (true). Anything else is `403 WORKER_SCOPE_FORBIDDEN`. The stop proof is still measured before the arm moves.
