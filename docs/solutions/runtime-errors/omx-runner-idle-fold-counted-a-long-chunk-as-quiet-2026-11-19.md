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

## Cause

`chunk_runner` sets `last_input` when a command arrives. `goto above_pick` at speed_low ran about 60 s, so the moment
it ended `quiet` was already past `runner.idle_park_s` (60 s) and the runner started an idle fold before the caller
could answer. A chunk row's `t` is written when the chunk ends, which hid that the goto itself was the long part.

## Fix (verified on the arm)

`chunk_runner_settle.check_runner_idle` resets `last_input` while a chunk, queue or pending command exists, so quiet
time starts when the runner is actually idle. Window values unchanged (60/30 s). Test:
`test_omx_runner_idle_orphan.py::test_a_chunk_longer_than_the_idle_window_is_not_idle_time`.
After deploy (omx-tools-319a8af38b) the same pivot at temp_plate_b:-0.034,-0.167 calibrated: bias [-13.8, 4.5] mm.

## Watch for

A stop right after a long chunk with "chunk park is still running": read the chunk rows' times as end times and compare
the gap since the previous command's arrival with runner.idle_park_s before suspecting the arm.
