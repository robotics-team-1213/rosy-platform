---
title: OMX Chunk Runner waits for alignment before start, parks folded wait poses without unfolding, and tolerates legacy Fleet software-stop records
date: 2026-11-15
category: logic-errors
module: deploy/robot/omx + middleware/devices/omx/adapter
modules: [deploy, middleware, test]
problem_type: logic_error
component: motion_control
severity: high
symptoms:
  - "Sending a chunk right after `command=start, ok=true` hit `alignment deadline exceeded` on real hardware"
  - "`park_path` unfolded a folded `wait(side)` pose through TRANSIT instead of rotating pan folded"
  - "Pre-Nov-8 site Fleet container kept `software stop ... nothing physical held it` as an open incident, blocking `arm_a` startup"
root_cause: startup_and_boundary_assumption
resolution_type: code_fix
tags: [omx, chunk_runner, park_path, fleet, software_stop, hardware]
applies_when:
  - "Signaling runner readiness (`start ok=true`) over guarded motion hardware"
  - "Returning from a folded side-wait pose to home via `park`"
  - "Querying older site Fleet servers for open arm holds after folded software stops"
---

# OMX Chunk Runner waits for alignment before start, parks folded wait poses without unfolding, and tolerates legacy Fleet software-stop records

## Problem

On `rosy-arm-cell` (`arm_a`), running `goto_wait` immediately after `chunk_runner` printed `{"command": "start", "ok": true}` failed with `software stop (alignment deadline exceeded)`. Afterwards:
1. Older site Fleet containers (`rosy-site-fleet:09069e25b9`, pre-Nov-8) ignored `decision.hold == False` and returned `1 open arm incident(s): software stop (...) with the arm folded on its command; nothing physical held it` from `open_incidents`, blocking subsequent starts.
2. `park_path` always routed through `TRANSIT` (shoulder lift `~0`) unless already within `NEAR_HOME` pan (`<= 12` units), unnecessarily unfolding an already-folded `wait(side)` pose to turn `shoulder_pan` back home.

## Root cause

- `chunk_runner_run.Runner.run` reported `start ok=true` before `motion.tracking` became true, pushing synchronization onto callers' blind post-start sleeps.
- `park_path` only checked pan proximity (`NEAR_HOME`) rather than whether `start` and `goal` were already folded with small wrist roll delta and closed jaws.
- Client hold gating (`_effectively_held`) assumed all Fleet server deployments honored `decision.hold == False` when storing `software_stop` summaries.

## Solution

- Delegate pre-start alignment wait to `wait_aligned_before_start` (`chunk_runner_settle.py`), keeping `chunk_runner_run.py` under the 400-line modularization cap and emitting `start ok=true` only after `motion.tracking` is true (while servicing `human-hold`, `state`, and `stop` during alignment).
- Keep `park_path` (`chunk_library.py`) folded for `wait(side)` pan turns when both poses satisfy `lift <= -50`, shared body joints match within 10 units, pan delta `<= 70`, and wrist roll delta `<= 45` (closing jaws first if needed).
- Teach `_effectively_held` (`omx_incident_fleet.py`) to treat explicit `"with the arm folded on its command; nothing physical held it"` non-hold answers as not physically held.

## Verification

- `load_predict.check_chunk` (`verdict: "ok"`, max wrist share `0.029`) and `omx_load.py check` (`ok: true`, `min_clearance_mm: 16.1`, `n_flags: 0`) passed on `park_wait`.
- `rosy-arm-cell` live 2-leg verification on `arm_a` (`goto_wait` with 0s post-start sleep, 2s torque-off sag <= 1 tick, `wait(side)` -> folded `park` across 256 samples staying `lift -62.3..-62.25` -> `stop` with all torque `0`) passed cleanly without manually clearing the pre-existing `software stop` row.
