---
title: Site autoupdate deferred forever on retained terminal goals and terminal DOCK_FAILED
date: 2026-11-25
last_updated: 2026-11-25
category: runtime-errors
module: deploy/site/site_update_runtime.py
problem_type: runtime_error
component: site_autoupdate
symptoms:
  - "rosy-site-autoupdate logged deferred-busy with reasons containing '<robot>: goal active' and '<robot>: docking DOCK_FAILED' on every run while /api/fleet/trips was idle"
  - "Signed site-* candidate releases remained unapplied on the site host"
root_cause: terminal_state_mismatch_between_fleet_console_and_site_idle_gate
resolution_type: code_fix
severity: high
tags: [site, autoupdate, idle-gate, fleet-console, goal-lease, dock-failed]
applies_when: "gating host container restarts or maintenance from /api/fleet/state without falsely matching robot-only self-update guards or intentionally retained UI display fields"
---

# Site autoupdate idle gate must ignore retained terminal goals and terminal DOCK_FAILED

## Problem

Live `rosy-site-autoupdate` runs deferred signed `site-*` candidate rollouts with `deferred-busy` (`reasons: ["<robot>: goal active", "<robot>: docking DOCK_FAILED"]`), even while `trips` had `running: null` and `open: []`, robots were in `mode: IDLE` with terminal `navigation: CANCELED` and zero velocity, and no arm session or queued dispatch was active.

## Cause

1. **Retained last-goal display vs. active goal lease:** `FleetConsole` intentionally keeps `console._goals[robot_id]` after terminal navigation (`ARRIVED`, `CANCELED`, `FAILED`) for UI display (`fleet/server/trips/trip_guard.py`, `fleet-dispatch-stale-goal-deadlock-and-silent-unknown-2026-11-22.md`) and attaches `goal_lease` (`"leased"` or `"unbounded"`) via `goal_leases.view()` only while a lease is live. `deploy/site/site_update_runtime.py:_robot_busy_reasons` checked `if row.get('goal')` unconditionally, so a retained terminal goal kept blocking site updates until someone manually called `cancel`.
2. **Robot-only docking allowlist copied into site container restarts:** `deploy/site/site_update_runtime.py` copied robot-side `_DOCKING_IDLE_STATES = {'UNDOCKED', 'DOCKED', 'CHARGING'}`. On a robot (`deploy/robot/pinky_pro/native/auto_update_host.py`), `DOCK_FAILED` must block self-updates because rebooting or restarting CORE clears faulted dock evidence before operator inspection. By contrast, `rosy-site-autoupdate` only restarts site containers (`fleet`, `vision`, `proxy`, `world`) and never restarts CORE or moves robots; per D-28/D-31, `DOCK_FAILED` is terminal and does not auto-retry (matching `FAILED` already allowed in `_NAV_IDLE_STATES`).

## Solution

- Updated `_robot_busy_reasons` in `deploy/site/site_update_runtime.py` to treat `row.get('goal')` as retained terminal UI state (idle) **only** when all four hold: `state` is a dict, `state.get('mode') == 'IDLE'`, `state.get('navigation') in _NAV_TERMINAL_STATES` (`{'ARRIVED', 'CANCELED', 'FAILED'}`), and `goal` has no active `goal_lease`. Missing `state`, non-`IDLE` mode, `navigation: 'IDLE'` (pre-nav dispatch), or any present `goal_lease` still fail closed as busy.
- Added `'DOCK_FAILED'` to site-only `_DOCKING_IDLE_STATES` while leaving `deploy/robot/pinky_pro/native/auto_update_host.py` and `navigation_reapprove.py` unchanged so robot self-updates continue to hold on `DOCK_FAILED`.
- Added fail-closed and live-shape regression tests in `test/test_site_autoupdate_idle.py`.

## Verification

- **Unit & policy suites (`tools/remote/remote_pytest.py`):** Verified `test/test_site_autoupdate_idle.py`, `test/test_site_autoupdate.py`, `test/test_rosy_auto_update_eligibility.py`, and `test/architecture/test_document_placement.py`. Source pytest does not substitute for live site-host acceptance.
- **Live site host:** Requires reinstalling the reviewed 5-file updater set to `/usr/local/lib/rosy-site/` from the merged `origin/main` commit, verifying `check-idle` and `--dry-run`, and running `rosy-site-autoupdate.service` to roll out the pending signed candidate.

## Recovery

Because `rosy-site-autoupdate.service` executes `/usr/bin/python3 -I /usr/local/lib/rosy-site/rosy_site_autoupdate.py` outside `/opt/rosy/candidate` (D-301 §3), site container rollouts stay blocked by the old host gate until an administrator backs up and reinstalls the reviewed 5-file unit (`rosy_site_autoupdate.py`, `verify_candidate.py`, `candidate_signing.py`, `site_update_io.py`, `site_update_runtime.py`) into `/usr/local/lib/rosy-site/` from the reviewed `origin/main` commit per `deploy/site/README.md`.

## Prevention

- Do not reuse Fleet UI display fields (`row["goal"]`) as sole busy indicators without checking `mode`, terminal `navigation`, and `goal_lease`; match `trip_guard.engaged` semantics while failing closed when `state` is absent or `IDLE`.
- Distinguish robot CORE restarts from site-host container restarts when choosing idle allowlists (`DOCK_FAILED` blocks robot CORE restarts, not site-container restarts).
