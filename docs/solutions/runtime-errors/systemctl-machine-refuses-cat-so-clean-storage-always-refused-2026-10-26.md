---
title: systemctl refuses `cat` over --machine, so the clean-storage helper refused a linked unit on every lab PC
date: 2026-10-26
category: runtime-errors
module: deploy/site/rosy-host-control (D-524 helper, D-883 clean-storage)
problem_type: runtime_error
component: deployment
symptoms:
  - "clean-storage answered `refused: no rosy-test-storage.service`, exit 5 (Fleet NO_STORAGE_SERVICE), on the model PC"
  - "the same PC showed rosy-test-storage.service as `loaded ... linked` and its timer had run at 12:31"
  - "host pytest for the helper passed"
root_cause: wrong_api
resolution_type: code_fix
severity: medium
framework_version: systemd 255 (Ubuntu 24.04)
tags: [systemd, systemctl, machine-transport, user-units, host-control, d-524, d-883, test-stub]
---

# systemctl refuses `cat` over --machine, so the clean-storage helper refused a linked unit on every lab PC

## Problem
The root helper reaches a login user's units with `systemctl --user --machine=<user>@ ...`. To refuse a PC where rosy-ops never linked `rosy-test-storage.service`, D-883 checked for the unit with `systemctl ... cat`. systemd refuses `cat` over any remote or machine transport, so the check failed on every PC and the storage button and the guard's automatic request could never run.

## Symptoms
- `SSH_ORIGINAL_COMMAND=clean-storage /usr/local/sbin/rosy-host-guard-remote` on the model PC printed `refused: no rosy-test-storage.service`, rc 5.
- `systemctl --user status rosy-test-storage.service` on the same PC: `Loaded: loaded (... linked)`, last run finished normally.

## What didn't work
The helper test replaced `systemctl` with a stub that accepted every argument, so the refusal never appeared off the device. Installing the helper and reading the code did not show it either.

## Solution
Check the unit with a property query, which works over `--machine`:

```sh
[ "$(systemctl --user --machine="$owner@" show -p LoadState --value rosy-test-storage.service 2>/dev/null)" = loaded ] \
  || refuse "no rosy-test-storage.service" 5
```

The helper test now uses a systemd-like stub (`_systemd_like` in `operations/fleet/test/test_host_control.py`) that refuses `cat` with `--machine` and answers `show -p LoadState --value` with `loaded` or `not-found`. The old helper fails it (RED on the remote test PC), the fixed one passes.

## Why this works
`show -p LoadState --value` reads the unit's state from the user manager over the same bus the `start` call uses. It prints `loaded` for a linked unit and `not-found` for a missing one, and it is allowed over `--machine`; only `cat`, which reads unit files from the local disk, is refused.

## Verification
- On the model PC (systemd 255.4): `systemctl --user --machine=rosy@ cat rosy-test-storage.service` → `Cannot remotely cat units.`, rc 1; `show -p LoadState --value` → `loaded`; for a missing unit → `not-found`.
- Remote pytest: the new test failed on the old helper and passes on the fix; `test_host_control.py`, `test_host_guard.py`, `test_host_state.py` NEW 0.
- Device acceptance of the fixed helper waits for its install on the AI and model PCs.

## Recovery
Until the fixed helper is installed, run the storage service directly as the PC's login user: `systemctl --user start rosy-test-storage.service`, or `python3 ~/rosy-test/maintenance/host_storage.py --apply`.

## Prevention
- For a helper that drives another user's units with `--machine`, prefer `show -p <Property> --value`, `is-active`, `start`. Do not use `cat`, `edit`, or other verbs that read local unit files.
- A test stub for a system tool must refuse what the real tool refuses. A stub that accepts every argument cannot show this class of bug; run the exact command once on a lab PC before relying on the stub.
