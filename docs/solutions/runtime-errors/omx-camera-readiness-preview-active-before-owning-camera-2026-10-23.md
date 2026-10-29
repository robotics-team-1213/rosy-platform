---
title: OMX camera readiness failed every boot because the Type=simple preview was active before it owned the camera
date: 2026-10-23
last_updated: 2026-10-29
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

## Fifth failure: role, producer unit and release configuration diverged (2026-10-28–29)

The front image role moved to the arm S gripper camera (Innomaker), whose producer
is `rosy-omx-camera@arm_a_wrist`. Readiness still inferred `@front` from the role.
Restore refused with `existing producer must be the sole camera owner` even while
the intended wrist producer was running. Renaming the image role would also have
changed the pipeline URL and dataset feature, so the fix keeps the role and sets
`cameras.front.unit = "arm_a_wrist"` in the private readiness profile.
`camera_readiness.py:76` resolves that optional unit; both baseline capture and
restore use it (`prepare()` and `restore()`). Old baselines retain their old
producer identity and profile hash: editing the profile alone cannot migrate them.

A separate `50-gripper-topic.conf` drop-in replaced the viewer's `ExecStart` with
the previous ROS setup command. After the native-snapshot transition (D-901), it
also bypassed the new foundation `PYTHONPATH`. The viewer journal showed
`ModuleNotFoundError: No module named 'core_common'`. Restarting without removing
that override repeated the same failure. Custom camera mappings belong in the
optional `omx-camera-view.env` supported by the updated unit, as described in the
[OMX deployment guide](../../../deploy/robot/omx/README.md); do not replace the
release command to change a source key. Deploy the supporting unit before moving
a working override, and verify advancing fresh frames afterwards.

These were update failures as well as camera failures. The devices updater rolls
back if a managed unit fails its restart. Its journal on 10-28 recorded
`rolled_back`, then repeated `known_bad`, and finally `switched` after recovery.
`omx_autoupdate.py:343` compares the candidate release with `state.json`'s `failed`
value before preparing it. Fixing a host configuration does not clear that marker:
the same release stays blocked until main changes or that marker is cleared.

### Recovery and evidence

The verified 10-28–29 recovery sequence was:

1. Back up private updater, profile, environment and state files. Wait until no
   `record_session.py` or `chunk_runner.py` owns the cell; keep the idle gate.
2. Remove the retired `@front` instance from the private updater's `units`.
   Readiness was temporarily outside that list during repair; restore its gate
   after it is healthy. Do not add a second producer for the same camera.
3. Move the obsolete viewer drop-in into the private host directory
   `~/.config/rosy/disabled-dropins/`, reload systemd and
   use the release's command and imports.
4. After correcting the cause, back up updater `state.json` and remove only its
   `failed` key. Keep current/previous/history and all camera baselines. Run the
   updater through its normal idle/rollback checks.
5. With the unit-aware code deployed and the cell idle, stop readiness and inspect
   `restoration.json` and control readback. Preserve any failed restore as evidence;
   never discard a baseline to conceal it. Archive the old state directory, set the
   profile's per-camera `unit`, and start readiness with a new state directory.
6. Check readiness and advancing fresh top/front images, then put readiness back
   into the updater's managed units. Exercise a later idle update before claiming
   update-transition acceptance.

The host retained `omx-camera-environment.pre-unit-20261028` and the disabled
`50-gripper-topic.conf`. On 10-29, its readiness journal showed a successful start;
a read-only check at 16:06 found both image roles fresh with `NORMAL` photometric
quality. That observation does not establish task visibility or motion acceptance.
Regression coverage remains in `test/test_omx_camera_readiness.py` and
`test/test_omx_autoupdate.py`; `test/test_native_observation_snapshot.py` additionally
executes the viewer command through user systemd with default and overridden keys.

## Evidence
Fleet PC journal 2026-10-23 06:10 (boot failure) and 11:33–11:34 (refusal, restore, READY). Fix commit on `fix/omx-camera-readiness-producer-wait`. The deployed file was replaced only after its SHA-256 matched the pre-fix repository version, and a backup `.bak-20261023` was kept.
