---
title: Site autoupdate deferred forever on retained terminal goals and terminal DOCK_FAILED
date: 2026-11-25
last_updated: 2026-11-25
category: runtime-errors
module: deploy/site/site_update_runtime.py, operations/fleet/fleet/server/console/console_helpers.py
problem_type: runtime_error
component: site_autoupdate
symptoms:
  - "rosy-site-autoupdate logged deferred-busy with reasons containing '<robot>: goal active' and '<robot>: docking DOCK_FAILED' on every run while /api/fleet/trips was idle"
  - "Signed site-* candidate releases remained unapplied on the site host"
root_cause: terminal_state_mismatch_between_fleet_console_and_site_idle_gate
resolution_type: code_fix
severity: high
tags: [site, autoupdate, idle-gate, fleet-console, goal-lease, goal-in-flight, dock-failed]
applies_when: "gating host Compose stack restarts or maintenance from /api/fleet/state without falsely matching robot-only self-update guards or cached CORE heartbeats"
---

# Site autoupdate idle gate must require Fleet goal_in_flight=False for retained terminal goals and allow terminal DOCK_FAILED

## Problem

Live `rosy-site-autoupdate` runs deferred signed `site-*` candidate rollouts with `deferred-busy` (`reasons: ["<robot>: goal active", "<robot>: docking DOCK_FAILED"]`), even while `trips` had `running: null` and `open: []`, robots were in `mode: IDLE` with terminal `navigation: CANCELED` and zero velocity, and no arm session or queued dispatch was active.

## Cause

1. **Retained last-goal display vs. cached CORE heartbeat race:** `FleetConsole` intentionally keeps `console._goals[robot_id]` after terminal navigation (`ARRIVED`, `CANCELED`, `FAILED`) for UI display (`fleet/server/trips/trip_guard.py`, `fleet-dispatch-stale-goal-deadlock-and-silent-unknown-2026-11-22.md`) and previously only attached `goal_lease` when leases are enabled (`0` by default). Simply ignoring `row["goal"]` on `mode == 'IDLE'` and terminal `navigation` is unsafe because `FleetConsole._gather_state` can reuse a cached CORE heartbeat up to `_hub_state_max_age_s` (3 s) while `row["goal"]` already projects a newly accepted unleased goal, classifying a newly dispatched goal as idle.
2. **Robot-only docking allowlist copied into site stack restarts:** `deploy/site/site_update_runtime.py` copied robot-side `_DOCKING_IDLE_STATES = {'UNDOCKED', 'DOCKED', 'CHARGING'}`. On a robot (`deploy/robot/pinky_pro/native/auto_update_host.py`), `DOCK_FAILED` must block self-updates because rebooting or restarting CORE clears faulted dock evidence before operator inspection. By contrast, `rosy-site-autoupdate` only restarts the configured site Compose stack (including PostgreSQL and enabled overlays); CORE stays on the robot and no motion commands are sent. Per D-28/D-31, `DOCK_FAILED` is terminal and does not auto-retry (matching `FAILED` already allowed in `_NAV_IDLE_STATES`).

## Solution

- Updated `operations/fleet/fleet/server/console/console_helpers.py` and `console_routes.py` (`gathered()`) to record `_goal_sent_at[robot_id]` on goal acceptance (and pop it with `_goals`) and refresh `goal`, `goal_in_flight`, `queued`, `named_stop_custody`, `yielding`, and `held` after telemetry awaits per HTTP `/api/fleet/state` response from live console state so `SharedGather`'s 1 s cache cannot serve stale `goal_in_flight: false` after a re-dispatch. `goal_in_flight` becomes `False` only when `_goal_busy`, `goal_leases.pending`, and `goal_leases.get()` are all clear, `state` is `mode == 'IDLE'` with terminal `navigation`, and `_state_mono - _goal_sent_at >= max(5.0, _hub_state_max_age_s + 2.0)` classifies the terminal CORE observation as occurring after goal acceptance and past the heartbeat cache window.
- Tightened `_robot_busy_reasons` in `deploy/site/site_update_runtime.py` so `row.get('goal')` is treated as retained historical display only when `row.get('goal_in_flight') is False`, `state` is `mode == 'IDLE'` with terminal `navigation`, and `goal` has no active `goal_lease`. Missing `goal_in_flight`, `goal_in_flight: True`, or cached legacy responses keep failing closed as busy.
- Added `'DOCK_FAILED'` to site-only `_DOCKING_IDLE_STATES` while leaving `deploy/robot/pinky_pro/native/auto_update_host.py` and `navigation_reapprove.py` unchanged so robot self-updates continue to hold on `DOCK_FAILED`.
- Added regression tests in `test/test_site_autoupdate_idle.py` and `operations/fleet/test/test_console_goal_in_flight.py`.

## Verification

- **Unit & policy suites (`tools/remote/remote_pytest.py`):** Verified `test/test_site_autoupdate_idle.py`, `test/test_site_autoupdate.py`, `test/test_rosy_auto_update_eligibility.py`, `test/architecture/test_document_placement.py`, `operations/fleet/test/test_console_goal_in_flight.py`, `operations/fleet/test/test_server_app.py`, and `operations/fleet/test/test_background_workers.py`. Source pytest does not substitute for live site-host acceptance.
- **Live site host:** Requires reinstalling the reviewed 5-file updater set to `/usr/local/lib/rosy-site/` from the merged `origin/main` commit, clearing any pre-fix in-memory retained goal in an idle pre-fix Fleet container once if needed, verifying `check-idle` and `--dry-run`, and running `rosy-site-autoupdate.service` to roll out the pending signed candidate.

## Recovery

Because `rosy-site-autoupdate.service` executes `/usr/bin/python3 -I /usr/local/lib/rosy-site/rosy_site_autoupdate.py` outside `/opt/rosy/candidate` (D-301 §3), site stack rollouts stay blocked until an administrator backs up and reinstalls the reviewed 5-file unit (`rosy_site_autoupdate.py`, `verify_candidate.py`, `candidate_signing.py`, `site_update_io.py`, `site_update_runtime.py`) into `/usr/local/lib/rosy-site/` from the reviewed `origin/main` commit per `deploy/site/README.md`. Pre-fix Fleet containers do not emit `goal_in_flight`, so a single idle Fleet container restart clears any pre-existing retained goal before the first automatic switch.

## Prevention

- Never assume `row["goal"]` paired with `IDLE`/terminal `navigation` represents finished work unless monotonic state-observation timestamps prove the terminal state occurred after goal acceptance (`goal_in_flight: False`).
- Distinguish robot CORE restarts from site-host Compose stack restarts when choosing idle allowlists (`DOCK_FAILED` blocks robot CORE restarts, not site Compose stack restarts).
