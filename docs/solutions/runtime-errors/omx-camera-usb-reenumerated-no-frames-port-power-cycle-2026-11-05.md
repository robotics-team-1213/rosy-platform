---
title: A re-enumerated D435 gives zero frames until its root port and peer are powered off for 30 s; a unit restart never fixes it
date: 2026-11-05
category: runtime-errors
module: deploy/robot/omx (cell_upkeep.py, camera_source.py, rosy-omx-cameras-bind.timer)
problem_type: runtime_error
component: development_workflow
symptoms:
  - "rosy-omx-camera@top restarted 652 times in about 2 h (systemd watchdog 8 s), the viewer answered 503 'No fresh frame'"
  - "v4l2-ctl --stream-mmap --stream-count=N on the colour node returned 0 bytes at 424x240 and 640x480"
  - "the camera came back on a USB2 root port (speed 480) and its USB3 peer port reported 'not attached'"
  - "after the camera recovered both arms' maps were stale: cell_upkeep check_map reported camera_moved, max_px about 50"
root_cause: hardware_state
resolution_type: tooling_addition
severity: high
tags: [omx, camera, realsense, d435, usb, hub, watchdog, power-cycle, cell_upkeep]
applies_when: "a camera unit restarts in a loop or the viewer serves 503 after a hub was replugged, and a direct v4l2-ctl read of the device also gives no bytes"
---

# A D435 stuck after a USB hub replug

## Problem

2026-11-04 23:53 a person replugged a USB hub. The top camera (RealSense D435, colour node `/dev/v4l/by-id/rosy-realsense-d435-color`, USB 8086:0b07) re-enumerated on a USB2 root port, its USB3 peer port `not attached`. The preview unit got no frames, the watchdog killed it every 8 s, and the bind timer (re-starts the unit every 20 s) kept it cycling. `cell_upkeep` only restarted the unit, which cannot help.

## What did not work

- sysfs `authorized` 0 -> 1 toggle.
- `USBDEVFS_RESET` ioctl.
- A 5 s `disable` 1 -> 0 of the root port and its peer.
- Any service restart: a direct `v4l2-ctl` read gave 0 bytes, so the device, not the service, was stuck.

## What worked (02:24)

1. Stop `rosy-omx-cameras-bind.timer` and `rosy-omx-camera@top` (otherwise they reopen the node during the cycle).
2. Write 1 to `disable` of the camera's root port (`/sys/bus/usb/devices/3-0:1.0/usb3-port4`) and of its `peer` (`usb4-port4`) for 30 s, then write 0 (lab PCs have `sudo -n`).
3. The first direct read right after re-enable still gave 0 bytes. A read about a minute later streamed 640x480 YUYV, still on USB2.
4. Start the timer and the unit: preview stable, HTTP 200, no more watchdog kills.

So: the hold must be long (30 s, not 5 s) and the first read must be retried for about 90 s before concluding it failed.

## Side effect

The camera had also physically moved about 50 px, so the arms' maps were stale. After recovering a camera, run the `cell_upkeep` map check before any pick.

## Prevention

`cell_upkeep.py --fix` now does this for a camera that fails after the unit restart and gives no frames on a direct read (`usb_recover`): resolve the root port and peer through sysfs, refuse (and report) when an OpenRB-150 board sits below that root port, stop timer and unit, hold 30 s, retry the read up to 90 s, start timer and unit, and report the link speed with a warning on USB2. No arm motion. Tests: `test/test_omx_cell_upkeep.py` (late first frame, shared port refused, no `--fix` reports only). Not verified on the real PC at the time of writing.

## Verification evidence

Recovery verified 2026-11-05 on the site control PC by hand (steps above): direct read, HTTP 200, no further watchdog kills. The code path is covered by fakes only until it runs there.

## When to apply

Unit restart loops or 503 on a USB camera after a hub, cable or power event, and `v4l2-ctl` on the node returns nothing. If the direct read streams, the fault is in the service, not USB. If the speed is USB2 for a D435, also fix the cable or port (depth needs USB3, see `omx-cell-device-identity-after-rewiring-2026-10-31.md`).
