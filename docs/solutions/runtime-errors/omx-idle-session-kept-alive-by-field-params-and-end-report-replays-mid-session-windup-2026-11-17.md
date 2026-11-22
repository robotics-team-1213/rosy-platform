---
title: An arm session outlived its caller for minutes (field params 180/180 and a home timer reset), and its end report showed a mid-session wind-up as if it happened at the end
date: 2026-11-17
category: runtime-errors
module: deploy/robot/omx (chunk_runner_settle.py, chunk_runner_commands.py, omx_incident.py)
problem_type: runtime_error
component: deployment
symptoms:
  - "an orphaned record_session/chunk_runner (ppid 1) kept arm_a folded with torque ON after cell_calibrate crashed"
  - "incident: wind-up before the end: elbow_flex still 0.8 units short, PWM winding up 206 -> 246 of 600"
root_cause: stale_field_params_and_timer_reset
resolution_type: code_fix
severity: medium
related:
  - docs/solutions/runtime-errors/omx-arm-b-elbow-overload-latched-at-home-by-a-box-in-the-jaws-2026-11-03.md
---

## Problem

2026-11-17 18:00 a real arm_a TCP remap (`cell_calibrate auto --only remap`) crashed after saving its map. Two later
runs (pivot 18:09, carry 18:15) re-attached to the still-running session through `with-session-arm-a-par.sh` (by
design: the wrapper starts a session only when none runs for that `--io`). After the carry exited the session stayed
up until a manual `stop` at 18:20, and its end check raised an arm incident that blocked the arm until a person
cleared it.

## What was not obvious

1. **Field params lengthened the idle window.** Every `with-session-*.sh` passes `--params cell-params-floor-1028.json`;
   it and six other cell params files still had `runner.idle_park_s` / `runner.idle_stop_s` 180 / 180, the values
   before the 11-03 decision of 60 / 30. Params override the code default, so the decision never reached the cell.
2. **`episode` / `load` reset the home timer** of an arm that was already folded, forcing a second idle fold and
   another full wait.
3. **The end-of-session wind-up report replays the whole session.** The wind-up (elbow 9 counts short, PWM -206 ->
   -246 under i_gain 50) happened at 18:05:38 at an extended remap hover, not at the folded home (elbow PWM 0..-3 at
   home 18:08-18:20). Reading the incident text as "it wound up while parked" sends the diagnosis the wrong way.

## Fix

- `chunk_runner_settle.py`: a params file can only shorten the idle park/stop times, never lengthen them past 60/30 s.
  Stopping still needs the arm folded home; a blocked fold still holds for a person (never torque off extended).
- `chunk_runner_commands.py`: `episode` and `load` keep `home_since`.
- Cell: the seven `cell-params-*.json` files set to 60/30 (backups `*.bak-20261117-*-idle`).
- Test `test/test_omx_runner_idle_orphan.py`: park, `episode`, caller dies -> one park and a stop within the idle
  stop time; a 180/180 params file still ends within about 60+30 s.

## Verify / apply next time

- Before trusting an incident's "before the end" wording, find the hit's timestamp in the session's
  `motor-health-*.jsonl` and the pose at that time.
- When a decision changes a runner default, grep the cell's `cell-params-*.json` for the key: a field file silently
  keeps the old value.
- Still open: whether the remap hover's elbow integral needs a limit (the actual wind-up).
