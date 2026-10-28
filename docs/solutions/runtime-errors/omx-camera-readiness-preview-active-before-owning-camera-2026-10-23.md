---
title: OMX camera readiness failed every boot because the Type=simple preview was active before it owned the camera
date: 2026-10-23
category: runtime-errors
module: deploy/robot/omx (camera_readiness.py, rosy-omx-camera-readiness.service, rosy-omx-camera@.service)
problem_type: runtime_error
component: deployment
symptoms:
  - "rosy-omx-camera-readiness.service failed at boot: CalledProcessError fuser /dev/v4l/by-id/...-video-index0 exit 1"
  - "ExecStopPost restore then failed too: 'camera restore incomplete; inspect restoration.json' with the same fuser error per camera"
  - "after the fix, the first manual start refused: 'camera settings changed since baseline; refusing overwrite'"
  - "2026-10-25 auto-update: cameras and readiness restarted together; readiness refused to start yet the updater logged switched"
  - "hours later, on the first lighting recovery: 'camera producer changed during environmental recovery' with no preview restart in the journal"
root_cause: startup_ordering
resolution_type: code_fix
severity: medium
tags: [omx, camera, v4l2, systemd, fuser, boot-ordering, readiness, restore, fleet-pc, auto-update, is-active]
applies_when: "a service must confirm that another Type=simple unit owns a device (fuser/lsof) right after systemd reports that unit active"
---

# OMX camera readiness failed every boot because the preview was active before it owned the camera

## Problem
`camera_readiness.py` refuses to tune a camera unless the preview unit `rosy-omx-camera@<role>` is its sole owner. It made this check once. The preview is `Type=simple`, so systemd reports it `active` before the process opens the V4L device. At boot the single `fuser` call found no owner. `fuser` exits 1 in that case, `command()` raised `CalledProcessError`, and readiness failed. The memory note "starting it immediately fails fuser" described this symptom without a fix. `After=` on the preview units would not fix it either, because `active` does not mean the device is open.

## Fix
`producer()` now polls the systemd state and `fuser` within a bound: 15 s in `run`, 5 s in `restore`, so that two cameras fit inside `TimeoutStopSec=20`. It treats `fuser` exit 1 as "no owner yet". The sole-owner refusal is unchanged: once the time runs out, no owner or more than one owner still raises. Regression tests are in `test/test_omx_camera_readiness.py` (`test_producer_*`). The boot test fails on the old code with the same `fuser` error seen in production.

## Recovery order on a host that already failed
1. The failed boot left the cameras on the previous run's tuned values, because restore failed too.
2. The first start after the fix refused with `settings changed since baseline`. This refusal is correct, so the baseline must not be deleted.
3. That failure ran `ExecStopPost` restore, which now succeeded (`restoration.json`: both `restored: true`, current controls equal to `baseline.json` originals).
4. The second start passed: `state: READY` with both cameras `NORMAL`.

Verify with `v4l2-ctl --get-ctrl=...` against `baseline.json` `original`. Do not edit or remove `baseline.json` to get past step 2.

## Second failure: a reused baseline guarded the wrong preview
`baseline.json` survives restarts and reboots on purpose, because it holds the original settings that restore writes back. It also stored the `producer` (preview PID and InvocationID) of the run that first recorded it on 10-19. `prepare()` checked that today's preview owned the camera, but did not replace that stored identity. The monitor's recovery step then compared today's preview with the 10-19 one. So the first lighting recovery after a reboot always stopped the service, even though no preview had restarted. That happened at 15:22 on 2026-10-23, after 3 h 47 min READY. `prepare()` now keeps this run's verified producer in memory and leaves the file unchanged. A preview restart during a run is still refused. To diagnose, compare `baseline.json` `cameras.*.producer` with `systemctl --user show rosy-omx-camera@<role> -p MainPID -p InvocationID`.

## Third failure: nobody made the second start (2026-10-24)
After a reboot at 19:47, the fixed release refused with `settings changed since baseline`, which is step 2 above. `ExecStopPost` restored the originals (`restoration.json` at 19:47, both `restored: true`). But the unit had `Restart=no`, so step 4 never ran. The cameras stayed unmanaged for 50 minutes, and the front camera was overexposed, until a manual `systemctl --user restart` reached READY. The unit now has `Restart=on-failure`, `RestartSec=15` and `StartLimitBurst=3` within 300 s. That allows the one documented retry plus a margin, and leaves a persistent refusal failed for a person to inspect. `test_service_has_independent_restore_for_the_same_state_directory` pins the retry. `cell_check.py` reports a stopped readiness service and prints this restart command.

## Fourth failure: the auto-updater restarted cameras and readiness together (2026-10-25)
D-871 put the cameras and readiness under `omx_autoupdate.py` (`rosy-omx-devices-autoupdate`). On the first switch it ran one `systemctl --user restart` over all the units. The restart stopped readiness, and its `ExecStopPost` restore ran while the cameras were reopening, so it ended `camera restore incomplete`. The new readiness then refused with `settings changed since baseline` (step 2 above). The updater still logged `switched`, because `systemctl is-active --quiet a b c` exits 0 when *any one* of the units is active.

Fix (#209):
- `"sequential": true` stops the units one by one in reverse order (readiness first, while the cameras are still open), then starts them in order.
- The updater checks `is-active` per unit, so a refused readiness fails the switch and rolls it back.
- `test_a_sequential_restart_stops_in_reverse_then_starts_in_order` and `test_one_failed_unit_among_several_fails_the_restart` pin both.

Recovery was the same order as above. The failed start's `ExecStopPost` restore succeeded (`restoration.json` both `restored: true`), then `systemctl --user reset-failed` and `start` reached READY (top and front 120 confirmations).

Evidence: Fleet PC 2026-10-25 20:33 (first switch, failure); later the same evening the second switch to d0d7f7367b4d with `sequential`, then a rollback and a switch forward again. Readiness was READY after each. This holds for any updater or script that restarts several units in one call: never trust a multi-unit `is-active`, and stop readiness before its cameras.

## Evidence
Fleet PC journal 2026-10-23 06:10 (boot failure) and 11:33–11:34 (refusal, restore, READY). Fix commit on `fix/omx-camera-readiness-producer-wait`. The deployed file was replaced only after its SHA-256 matched the pre-fix repository version, and a backup `.bak-20261023` was kept.
