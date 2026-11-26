---
title: Restarting rosy-omx-cell-job-api.service SIGKILLed a detached human-held chunk_runner
date: 2026-11-24
category: runtime-errors
module: deploy/robot/omx (rosy-omx-cell-job-api.service, cell_job_api.py)
problem_type: runtime_error
component: deploy
symptoms:
  - "systemctl --user restart rosy-omx-cell-job-api.service sent SIGTERM twice to an active detached chunk_runner holding an extended arm under human_hold_latched: true"
  - "chunk_runner refused both SIGTERMs (HOLD: human hold already latched / still holding, torque ON), then systemd TimeoutStopSec=5 timed out and sent SIGKILL"
  - "The arm remained physically suspended on OpenRB-150 RAM torque_enabled=1 with hold: 'runner HOLD' in arm-leases/<arm>.json and stale live.json, with no live runner process to receive SIGUSR2"
root_cause: systemd_default_control_group_killmode_kills_detached_chunk_runner_children
resolution_type: systemd_unit_and_regression_test_fix
severity: high
tags: [omx, cell-job-api, systemd, killmode, human-hold, chunk-runner, d-911]
applies_when: "restarting or updating rosy-omx-cell-job-api.service on an OMX arm cell while a session or human-hold runner may be active"
---

# Restarting `rosy-omx-cell-job-api.service` SIGKILLed a detached human-held `chunk_runner`

## Problem

While an OMX follower arm was extended over the workcell holding a payload under a latched `human-hold` (`human_hold_latched: true`, `torque_hold_commanded: true`), deploying updated code restarted `rosy-omx-cell-job-api.service`.

1. Systemd sent `SIGTERM` twice to the detached `chunk_runner` child that owned the arm session.
2. As required by D-911, `chunk_runner` refused `SIGTERM` twice (`HOLD: human hold already latched; a person must support the arm, then kill -USR2 the runner` / `HOLD: still holding, torque ON`) so an unsupported arm would not drop.
3. Because `TimeoutStopSec=5` expired while `chunk_runner` refused to exit, systemd hit `final-sigterm` timeout and terminated `chunk_runner` with `SIGKILL`.
4. After `SIGKILL`, no host process held the serial port or accepted `SIGUSR2`, `chunk-io-<arm>/live.json` froze with `human_hold_latched: true`, `~/.local/state/rosy/arm-leases/<arm>.json` kept `hold: "runner HOLD"`, and OpenRB-150 servo RAM still held the physical arm with `torque_enabled=1`.

## Root Cause

`cell_job_api.py` spawns jobs with `subprocess.Popen(..., start_new_session=True)` to detach them into a new POSIX session (`setsid`). However, `start_new_session=True` does not move child processes out of the launching systemd service's cgroup.

Because the deployed `rosy-omx-cell-job-api.service` unit was not tracked in the repository and omitted `KillMode=`, systemd used its default `KillMode=control-group`. Every restart of `rosy-omx-cell-job-api.service` signaled the entire cgroup—including detached `with-session-arm-*.sh -> record_session -> chunk_runner` processes—and escalated to `SIGKILL` after `TimeoutStopSec=5`.

## Fix

- Added the canonical unit file `deploy/robot/omx/rosy-omx-cell-job-api.service` with `KillMode=process`, `NoNewPrivileges=true`, and `UMask=0077` so restarting the HTTP API signals only `cell_job_api.py` and preserves detached arm-session children (similar to `rosy-omx-arm-session@.service`'s cgroup separation rationale).
- Added regression test `test_cell_job_api_service_unit_preserves_detached_arm_sessions` in `test/test_omx_cell_job_api.py` asserting `KillMode=process` and forbidding `KillMode=control-group`.
- Added a pre-restart `pgrep -f chunk_runner` guard in local cell deployment tooling (`deploy_cell.py`) so deploys refuse to restart `rosy-omx-cell-job-api.service` while any `chunk_runner` is active, and synced the tracked service file with `systemctl --user daemon-reload`.

## Recovery & Verification

If a held `chunk_runner` has already been killed with `SIGKILL`:

1. Inspect physical arm pose and payload clearance via overhead/side cameras (`:8767`) before touching any software lock.
2. Read servo registers without resetting the board (`register_probe.open_readonly_port` with `dtr=False, rts=False`) to confirm `torque_enabled` and `hardware_error`.
3. Physically support the arm with a hand before disabling servo torque or E-stop/power, remove any held object, fold the arm safely to home, and restore power.
4. Clear the stale `"runner HOLD"` lease (`cell_arm_lease.py release-hold <arm>`), then run `:8781` `home` so `chunk-io-<arm>/live.json` updates cleanly.

Service unit verification on the cell host:

- `systemctl --user show -p KillMode --value rosy-omx-cell-job-api.service` prints `process`.
