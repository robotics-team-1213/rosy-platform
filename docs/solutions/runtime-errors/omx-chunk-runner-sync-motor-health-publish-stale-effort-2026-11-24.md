---
title: Synchronous MotorHealth publish in chunk_runner stalled past 0.5s effort bound on run entry, and recover-unlatch/stop left live.json stale
date: 2026-11-24
category: runtime-errors
module: deploy/robot/omx/chunk_runner (MotorHealth async_publish, live.json flush on unlatch/stop)
problem_type: runtime_error
component: robot-omx
symptoms:
  - "arm_b live ACT cell_policy_drive failed on run entry (at: 0) with encoder read failed: stale effort sample (>0.5 seconds): tick_ms=241.0 last_tick_ms=454.8 last_effort_ms=532.3 pwm_ms=1.9 monitor_ms=234.7"
  - "After POST /jobs/recover_hold exited 0 via recover-unlatch -> stop, chunk-io-b/live.json kept human_hold_latched: true and fault: human hold, blocking peer arm jobs"
root_cause: incomplete_rollout_and_missing_terminal_publish
resolution_type: code_fix
severity: high
tags: [omx, motor-health, async-publish, chunk-runner, live-json, recover-unlatch, cell-job-api, stall]
applies_when: "Editing MotorHealth call sites or terminal state transitions in chunk_runner"
---

# Synchronous MotorHealth publish in chunk_runner stalled past 0.5s effort bound on run entry, and recover-unlatch/stop left live.json stale

## Problem
Two real-hardware issues surfaced on `arm_b` during the first live ACT verification (`20261124-153302-c9a242`) and the subsequent `recover_hold` unlatch/stop (`20261124-154010-a6b5fb`):

1. **Synchronous `MotorHealth.publish()` in `chunk_runner`:** An earlier fix added `MotorHealth(async_publish=True)` only in `guarded_native_cli.py`, leaving `chunk_runner.py` constructing `MotorHealth()` synchronously (`async_publish=False`). During ACT startup load (`dt_ms=421.4 ms`), `monitor.sample()` spent `234.7 ms` performing synchronous `atomic_snapshot` write+replace, pushing `last_effort_ms=532.3 ms > 500 ms`, which tripped `NativeJointMotion`'s stale-effort fault on `run entry` before leaving home.
2. **Stale `live.json` after `recover-unlatch` -> `stop`:** `chunk_runner_loop.py` only emitted `runner.live(...)` inside the 30 Hz control loop. When `recover_hold` issued `recover-unlatch` immediately followed by `stop`, `chunk_runner` logged clean status rows and exited (`return False`), leaving `chunk-io-b/live.json` frozen at `human_hold_latched: true, fault: "human hold"`. `cell_job_guards.check_peer_ab_folded` then rejected peer `arm_a` moving jobs.

## Symptoms
- `chunk-status.jsonl` (job `20261124-153302-c9a242`): `"encoder read failed: stale effort sample (>0.5 seconds): tick_ms=241.0 last_tick_ms=454.8 last_effort_ms=532.3 pwm_ms=1.9 monitor_ms=234.7"`.
- `motor-health` JSONL lines 31–32: sample at `+421.4 ms` jitter followed by `monitor_ms=234.7 ms` on the synchronous snapshot publish tick.
- After `recover_hold` job `20261124-154010-a6b5fb` exited `0`, no `chunk_runner` process remained, yet `chunk-io-b/live.json` still reported `"human_hold_latched": true, "fault": "human hold"`.

## What didn't work
- Keeping `MotorHealth(async_publish=True)` only in `guarded_native_cli.py` left `chunk_runner.py` (all chunked/ACT policy sessions) doing blocking disk snapshots inside the 5 Hz effort hook.
- Relying on the periodic 10 Hz `runner.live(...)` write in `chunk_runner_loop.run()` missed immediate state clears (`recover-unlatch`, `stop`, and `idle`/`_park_settled` returns).

## Solution
1. In `deploy/robot/omx/chunk_runner.py`, instantiate `MotorHealth(async_publish=True)` when `async_publish` is in `inspect.signature(MotorHealth).parameters` (matching `guarded_native_cli.py` while keeping zero-argument test stubs working). This runs under `main_thread_signals.route()` prior to `unblock_main()`, so the publisher thread inherits blocked shutdown signals, and `admit()`, `fault()`, and `end()` still flush synchronously.
2. Extract `publish_live(runner, *, state=None, best_effort=False)` in `deploy/robot/omx/chunk_runner_loop.py` and call it:
   - in `chunk_runner_recover.dispatch_recover_unlatch` right after `runner.report(...)` when `not runner.human_hold_latched`;
   - in `chunk_runner_commands.py` on clean `stop` when `not runner.human_hold_latched`;
   - in `chunk_runner_loop.run` right before the non-interrupt `_stopped and _park_settled` or `runner.idle()` return.

## Why this works
- Offloading periodic 2 Hz `atomic_snapshot` writes from `sample()` to `AsyncSnapshotPublisher` keeps `monitor_ms` off the critical 5 Hz effort deadline while retaining synchronous `flush(close=True)` guarantees on `fault()` and `end()`.
- Flushing `live.json` at `recover-unlatch`, clean `stop`, and clean idle/park exit guarantees `cell_job_guards.check_peer_ab_folded` sees the cleared hold state as soon as the session exits or unlatches.

## Verification
- Observed hardware fault telemetry in live failure bundle (`20261124-153302-c9a242`) and `recover_hold` live run (`20261124-154010-a6b5fb`).
- Regression test `test_chunk_runner_async_health_and_live_flush_on_unlatch_and_stop` in `test/test_omx_recovery_park_hold.py` verifies both `MotorHealth(async_publish=True)` wiring in `chunk_runner.main()` and immediate `live.json` clearance accepted by `check_peer_ab_folded()`.

## Recovery
- If an older runner exited cleanly via `recover_hold` while leaving a stale `human_hold_latched: true` in `live.json`, do not hand-edit `live.json`; inspect hardware and open arm incidents first, then upgrade `omx-tools-current` to a release containing this fix.

## Prevention
- When adding non-blocking telemetry options to shared safety/health classes (`MotorHealth`), audit every entrypoint (`guarded_native_cli.py`, `chunk_runner.py`) rather than only the teleop wrapper.
- Every transition in `chunk_runner` that clears `human_hold_latched` or ends a run without `_interrupt` must publish its final snapshot before returning.
