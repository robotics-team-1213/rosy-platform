---
title: CORE UMask 0027 strips o+r from /run/rosy/status-inputs.json and blocks device drivable steering
date: 2026-11-22
last_updated: 2026-11-22
category: runtime-errors
module: middleware/core/gateway/core/system/host_files.py, middleware/perception/sensors/line_observation/core_law_input.py
problem_type: runtime_error
component: core_and_perception
symptoms:
  - "Front camera debug overlay on live Pinky robots shows STOPPED BY: STEERING - core_steering_law_unavailable even while CORE writes fresh schema-2 status-inputs.json."
  - "su -s /bin/sh rosy-camera -c 'head -c 80 /run/rosy/status-inputs.json' exits 1 with Permission denied on geg6 (2026.11.20-208) and b8xy (2026.11.21-219)."
root_cause: configuration_and_file_mode
resolution_type: code_fix
severity: high
tags: [pinky-pro, systemd, umask, status-inputs, drivable, line-observer, permissions]
---

# CORE UMask 0027 strips o+r from `/run/rosy/status-inputs.json` and blocks `learned_drivable` steering

## Problem

`rosy-core.service` runs under `User=rosy-core`, `Group=rosy-core`, and `UMask=0027`, while `rosy-camera.service` runs under `User=rosy-camera` (not a member of group `rosy-core`).

To drive with `learned_paint_target: drivable` on real hardware (`native_law_required() == True`), `line_observer_node` calls `CoreLawInput.read('/run/rosy/status-inputs.json', ...)` to invert CORE's effective steering law (`line_follow_steering_law`). Because `HostFileExchange.write_status_inputs()` delegated to `_write_private(path, ..., 0o644, "status-inputs")` which only passed `mode` to `os.open(...)` without `os.fchmod(fd, mode)`, the process umask `0027` masked `0o644` down to `0o640` (`rw-r-----`). Every open by `rosy-camera` raised `PermissionError`, `CoreLawInput.read()` returned `None`, and `line_observer_node` halted steering with `core_steering_law_unavailable`.

Unit tests passed because pytest ran with a default umask (`0022`), and Gazebo `fleet_trips` passed because `native_law_required()` is `False` outside device deployments.

## Solution

In `middleware/core/gateway/core/system/host_files.py`, `_write_private` now opens the temporary file with `mode & 0o600` (so the staging file never has broader permissions before write) and calls `os.fchmod(handle.fileno(), mode)` before closing (with an `os.chmod` fallback on platforms lacking `fchmod`), matching the pattern already used by `write_face_inputs`. Preserved `0o600` and `0o640` modes on all other `_write_private` callers.

Added POSIX regression test `test_write_status_inputs_keeps_0644_under_umask_0027` in `middleware/core/gateway/test/test_host_status_summary.py`, verifying `0o644` for `write_status_inputs` and unchanged `0o640`/`0o600` for `_write_private` under `os.umask(0o027)`.

## Verification

- Verified `su -s /bin/sh rosy-camera` read failure (`Permission denied`, `stat 0o100640 uid=960`) on both `geg6` (`2026.11.20-208`) and `b8xy` (`2026.11.21-219`) prior to the fix.
- Remote pytest (`test_host_status_summary.py` and `test_core_steering_law_input.py`) on Linux lab host under real POSIX `os.umask(0o027)` semantics.
- Live robot readback and front-camera `learned_drivable` overlay verification after deploying the signed `payload-v2` release.

## Prevention

- **Never rely on `os.open(..., mode)` to grant group/other bits under systemd services.** Units hardened with `UMask=0027` or `0077` silently strip permission bits from `open(2)`. Any hand-over file meant for cross-service readers (`rosy-face`, `rosy-camera`, root status tools) must explicitly `os.fchmod(fd, mode)` inside the atomic temp-file helper.
- **Test systemd cross-user hand-over writers under `os.umask(0o027)`.** Include explicit `os.umask(0o027)` checks in POSIX unit tests for files shared across UIDs.
