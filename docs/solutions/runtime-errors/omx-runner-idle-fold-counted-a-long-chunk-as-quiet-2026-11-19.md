---
title: The runner's idle fold must count quiet time from the end of the last chunk, not from its command's arrival
date: 2026-11-19
module: deploy/robot/omx
tags: [omx, chunk_runner, idle, pivot, session]
problem_type: runtime-error
applies_when: a caller's chunk (a slow goto, a long move) runs close to runner.idle_park_s, or a pivot/carry stops with "chunk park is still running"
---

## Symptom

Every arm_b pivot near the tray (temp_plate_b) "stopped" with bias null. chunk-status showed `load`, then
`run goto above_pick` ok 62 s later, then the pivot's next `state`/`grip` refused: "chunk park is still running".
It looked like an elbow-load stop or a session race and was guessed at twice (an elbow guard; a keep-alive during the
pre-motion check, which was reverted because nothing was quiet there).

On 2026-11-24 the same failure recurred during arm_b remap point #4: `goto above_pick` ran 74.1 s (> 60 s
`runner.idle_park_s`) and `check_runner_idle` launched `park` on the exact same loop tick `check_chunk_settled` finished
`goto above_pick` (28 ms before `grip 50.5`), because commit `2a2df78df4` had absorbed this lesson doc without landing
the code change or test into `main`.

## Cause

`chunk_runner_loop` updates `last_input` only when a FIFO command arrives. When `goto above_pick` at speed_low runs
longer than `runner.idle_park_s` (60 s), `quiet = clock() - last_input` exceeds 60 s while the arm is still moving.
On the exact tick `check_chunk_settled` clears `runner.chunk`, `check_runner_idle` ran immediately afterward in the
same loop iteration and started an idle fold before the caller could send the next command. A chunk row's `t` is written
when the chunk ends, which hid that the goto itself was the long part.

## Fix

Both `chunk_runner_settle.check_runner_idle` (while `runner.chunk`, `runner.queue`, or `runner.pending` is non-empty)
and `chunk_runner_settle.check_chunk_settled` (updating `runner.last_input = now` when clearing `runner.chunk`) keep
`last_input` current across active chunks so quiet time starts only after the arm finishes moving and settling. Idle
window values (`runner.idle_park_s=60`, `runner.idle_retry_s`, `runner.idle_stop_s=30`), release confirmation holds,
`_recovery_active`, `idle_parks` retry tracking, and `_policy_session` behavior are unchanged. Tests:
`test/test_omx_runner_idle_fold.py::test_a_chunk_longer_than_the_idle_window_is_not_idle_time` and
`test/test_omx_runner_idle_fold.py::test_idle_park_still_fires_after_a_long_chunk_when_caller_goes_silent`.

## Watch for

A stop right after a long chunk with "chunk park is still running": read the chunk rows' times as end times and compare
the gap since the previous command's arrival with runner.idle_park_s before suspecting the arm.
