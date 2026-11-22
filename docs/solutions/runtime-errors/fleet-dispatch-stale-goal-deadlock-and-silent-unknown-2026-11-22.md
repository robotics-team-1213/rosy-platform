---
title: Fleet task dispatch stalls after first arrived goal and silently swallows UNKNOWN dispatch errors
date: 2026-11-22
last_updated: 2026-11-22
category: runtime-errors
module: operations/fleet/fleet/server/background_workers.py, operations/fleet/fleet/server/ledger/task_service.py
problem_type: runtime_error
component: site_fleet_dispatch
symptoms:
  - "Multi-waypoint operator navigation queue stops dispatching task 2+ after task 1 reaches ARRIVED until POST /api/fleet/robots/{id}/cancel is called."
  - "Tasks transitioning to UNKNOWN (COMMAND_RESULT_UNKNOWN) on RobotApiError (>=500) or unexpected exceptions leave no diagnostic trace in Site Fleet container logs."
root_cause: stale_goal_check_and_missing_exception_log
resolution_type: code_fix
severity: high
tags: [site-fleet, task-dispatch, console-goals, unknown-task, logging]
---

# Fleet task dispatch stalls after first `ARRIVED` goal and silently swallows `UNKNOWN` errors

## Problem

1. **`_task_dispatch_loop` deadlocked on retained `console._goals`:** `FleetConsole` intentionally retains `console._goals[robot_id]` after a navigation goal reaches `ARRIVED` (for UI last-goal display; `trip_guard.engaged` explicitly notes this and only counts active or `< GOAL_FRESH_S` goals). Meanwhile `run_snapshot_traffic` only pops `console._claims`, never `console._goals`. Because `operations/fleet/fleet/server/background_workers.py` checked `row["goal"] is None`, any queued task after the first `ARRIVED` navigation task was skipped indefinitely unless an operator manually called `POST /api/fleet/robots/{robot_id}/cancel`.
2. **Silent `UNKNOWN` transitions in `FleetTaskService._dispatch_next`:** `operations/fleet/fleet/server/ledger/task_service.py` transitioned `RobotApiError` (`status >= 500`) and unclassified `Exception` into `UNKNOWN (COMMAND_RESULT_UNKNOWN)` with no `_LOG.warning` or `_LOG.exception`, making live incidents (such as `b6648df9` on `rosy_42`, which transitioned in 394 ms without reaching CORE) impossible to diagnose from container logs.

## Solution

- Added `_goal_in_flight(console, row, now)` in `operations/fleet/fleet/server/background_workers.py` reusing `GOAL_FRESH_S` from `fleet.server.trip_guard`, checking `row["yielding"]`, `console._goal_busy`, `console.goal_leases.pending`, and fresh `console.trip_goal_sent_at` (`now - sent_at < GOAL_FRESH_S`). Updated `_task_dispatch_loop` to check `not _goal_in_flight(console, row, now)` instead of `row["goal"] is None`, preserving all safety, navigation-state, lease, claim, and trip guards.
- Added `_LOG.warning` (for `RobotApiError` with `status >= 500`, logging status/code/task/robot/attempt) and `_LOG.exception` (for unclassified exceptions) in `operations/fleet/fleet/server/ledger/task_service.py` while keeping raw exception details out of the persisted SQLite `reason`.
- Added regression tests in `operations/fleet/test/test_background_workers.py` and `operations/fleet/test/test_task_service.py`.

## Verification

- Observed live on `rosy-fleet-r` + `rosy_42`: queued `wp-2` stayed `QUEUED` after `wp-1` reached `ARRIVED` until manual `cancel`, and `b6648df9` entered `UNKNOWN (COMMAND_RESULT_UNKNOWN)` with zero corresponding error/warning lines in `rosy-site-fleet-1` logs.
- Verified with remote pytest across `operations/fleet/test/test_background_workers.py`, `test_task_service.py`, `test_link_address_source.py`, `test_loop_supervision.py`, `test_task_api.py`, `test_dispatch_admission.py`, `test_cancel_all.py`, and `test_task_native_outcomes.py`.

## Prevention

- Match the canonical in-flight goal definition (`trip_guard.engaged`) instead of checking raw presence in `console._goals`.
- Every `UNKNOWN` error branch at external robot boundaries must emit a structured warning/exception log with `task_id`, `robot_id`, and `attempt_id` without persisting raw error text into DB state.
