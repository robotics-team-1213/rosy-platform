---
title: os.replace is not in os.supports_dir_fd, so the device first boot took the chown-less fallback and CORE looped on a root-owned rosy.yaml
date: 2026-10-31
category: runtime-errors
module: deploy/robot/pinky_pro/native/first_boot_runtime.py, deploy/robot/pinky_pro/image/first-boot/rosy-first-boot.py
problem_type: runtime_error
component: deployment
symptoms:
  - "rosy-core restarts every ~45 s with PermissionError: /var/lib/rosy/core/.rosy/rosy.yaml"
  - "mDNS stage stays PROVISIONED; Fleet discovery lists the robot but it never reaches CORE_READY"
  - "/var/lib/rosy/core is rosy-core:rosy-core but .rosy and rosy.yaml under it are root:root (0750/0600)"
root_cause: wrong_api_assumption
resolution_type: code_fix
applies_when:
  - "code gates a dir_fd/no-follow file path on `fn in os.supports_dir_fd`"
  - "a fresh Pinky card shows CORE in a restart loop on the CORE overlay"
  - "a test checks file ownership with the test process's own uid"
---

## Problem

nsfh (10-30) and b8xy (10-31, a freshly written card, first boot 8 minutes earlier) both had CORE in a restart
loop. `.rosy` and `rosy.yaml` under CORE's HOME were root-owned. On 10-30 the cause was put down to a manual
`sudo` edit, because the first-boot code clearly `fchown`s to rosy-core. That was wrong.

## Cause

- `first_boot_runtime._NOFOLLOW_FS` required `os.replace in os.supports_dir_fd`.
- CPython lists `os.rename` there but not `os.replace`. Both take `src_dir_fd`/`dst_dir_fd` through
  `renameat`. Checked on b8xy, Python 3.12.3: `open True replace False rename True`.
- So `_NOFOLLOW_FS` was False on every device. `_core_api` took `_core_api_by_path`, the fallback commented
  "Fixture hosts without O_NOFOLLOW/dir_fd (Windows); the device never takes this path". It created
  the directories and file as root and never chowned.
- Evidence: b8xy `stat` birth of `.rosy` and `rosy.yaml` is 07:36:29.759 (unsynced boot clock).
  `rosy-first-boot.service` ran 07:36:28.25 to 07:36:40 and `/etc/passwd` already held rosy-core
  (960) from 07:36:25.

## Why tests missed it

`test_the_overlay_belongs_to_rosy_core_and_is_private` expected the test process's own uid. A file created by
that process already has that owner, so the test passed with no chown at all, on either path.

## Fix

- `_NOFOLLOW_FS` checks `os.rename` (fix commit on `fix/first-boot-core-overlay-owner`).
- The path fallback also chowns CORE's HOME, `.rosy` and the temporary file when the owner is known.
- `test_linux_takes_the_descriptor_path_and_hands_the_overlay_to_rosy_core` asserts `_NOFOLLOW_FS` on Linux
  and records `fchown(960, 960)` three times. Remote: it fails on the old runtime and passes with the fix.
  `test_the_path_fallback_also_hands_the_overlay_to_rosy_core` covers the fallback.

## Recovery on a device already written

`sudo chown rosy-core:rosy-core /var/lib/rosy/core/.rosy /var/lib/rosy/core/.rosy/rosy.yaml` then
`sudo systemctl restart rosy-core`. b8xy reached CORE_READY within a minute (10-31).

## Not yet verified

A card written from an image built after the fix has not been booted. Cards already in the field keep the
root-owned files until fixed by hand or rewritten.

## Apply next time

- Do not use `fn in os.supports_dir_fd` for `os.replace`. Test `os.rename`, or call the function and handle
  `NotImplementedError`.
- An ownership test must expect a uid other than the test process's own, or record the chown call.
- A "never on the device" fallback needs a test that the device condition is true on Linux.
