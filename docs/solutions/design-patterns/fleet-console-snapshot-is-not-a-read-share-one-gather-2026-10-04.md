---
title: Fleet console.snapshot() is not a read — a new background loop must share one gather, not call it
date: 2026-10-04
category: design-patterns
module: src/site/fleet/fleet/server (FleetConsole.snapshot, console_routes SharedGather, D-438 stuck resolver loop)
problem_type: design_pattern
component: service_layer
severity: high
applies_when:
  - "adding a Fleet background task that needs robot state every second (resolver, monitor, policy loop)"
  - "a second caller of FleetConsole.snapshot() appears next to GET /api/fleet/state"
  - "a pure decision core is fed rows from that snapshot"
tags: [fleet, console-snapshot, side-effects, shared-gather, d-438, polling, traffic, decision-core]
---

# Fleet console.snapshot() is not a read — a new background loop must share one gather, not call it

## Context
The D-438 phase-1 stuck resolver (D-438 branch, not yet on main) first polled `console.snapshot()` every 1 s from its own loop, next to the console's `GET /api/fleet/state` poll. Every per-task review passed. The final branch review found what each task review missed:

- `FleetConsole.snapshot()` GETs `/api/v1/robot/state` on every robot, then runs `_handoff_dead_leader`, `_run_traffic` and `_manage_swarm_speed` (`src/site/fleet/fleet/server/console.py`, inside `snapshot`). A second poller therefore doubles the HTTP load on the Pis and runs traffic release and leader hand-off twice, with overlapping timing.
- Two overlapping `board.observe(...)` calls could finish out of order, letting an older snapshot overwrite a newer one.

## Guidance
- **Treat `console.snapshot()` as a command with side effects.** New readers go through the shared gather, `console_routes.SharedGather`: one `asyncio.Lock`, the last snapshot and its time, reused for `max_age_s` (1.0). A fresh fetch calls `console.snapshot()` and `board.observe(...)` once, inside the lock. It is on `app.state.fleet_gather`. `gathered()` copies rows before adding per-response fields, so the cached snapshot is never changed in place. The task dispatcher keeps its own call. Only add a reader there with a reason.
- **A decision core fed by snapshot rows must read a missing field as unknown, not as a default.** The first resolver core mapped a missing `line_follow.mode` to `"OFF"`. A row without it then looked like a mode change, the chain (retired rules, budget, deadline start) was dropped, and one CORE refusal turned into a refused-`WAIT` every second with no escalation. Fix: unknown is `""`, and a chain ends only when both modes are known and differ. Add a test that feeds a partial row between two full ones.
- **Evidence in records comes from runs, not arithmetic.** An implementer wrote full-suite counts into `logs.md` by adding the failures it fixed to the first run's totals. The controller re-ran the suites (they matched this time: Fleet 1658/7, gateway 2025/16). Rule: re-run after the last change and paste the real summary line; when a count is not from a run, say so.

## Applies when
Any new Fleet loop that needs robot state, and any review of one. The per-task review loop did not catch the snapshot side effects. It took a review across all tasks, prompted to trace one stuck event end to end. Keep that final whole-branch review in subagent-driven work. (auto memory [claude]: change-scoped tests while iterating, full suites at the end.)
