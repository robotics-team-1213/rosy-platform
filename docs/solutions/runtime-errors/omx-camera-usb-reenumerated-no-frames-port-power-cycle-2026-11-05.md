---
title: A re-enumerated D435 gives zero frames until its root port and peer are powered off for 30 s; a unit restart never fixes it
date: 2026-11-05
last_updated: 2026-11-06
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

`cell_upkeep.py --fix` does this for a camera that fails after the unit restart and gives no frames on a direct read (`usb_recover`): resolve the root port and peer through sysfs, refuse (and report) when an OpenRB-150 board sits below **any port that will be cycled**, stop timer and unit, hold 30 s, retry the read up to 90 s, start timer and unit, and report the link speed with a warning on USB2. No arm motion. Tests: `test/test_omx_cell_upkeep.py` (late first frame, shared port refused, no `--fix` reports only). The recovery implementation has not been accepted on the real PC.

The earlier root-only board check was incomplete: a USB3 camera can have an OpenRB on the USB2 companion subtree, yet recovery powers both ports. Discovery must match serial devices against both complete subtrees, using path components so a neighboring port such as `3-20` is not mistaken for `3-2`. Missing camera/sysfs links, a dangling peer or an incomplete USB ancestor chain must raise `OSError` before unit or port writes; an ancestor walk must stop at the filesystem root. Do not recover from unknown topology by guessing a port or omitting its boards.

### 2026-11-06 correction: inspect the whole power domain before recovery

The initial implementation inspected serial boards below only the camera's USB root, although it disabled both that port and its peer. A USB3 camera and a USB2 OpenRB behind the same connector can therefore appear below different roots. An arm-local session check does not protect another arm's board on that peer. The [kernel USB power-management documentation](https://www.kernel.org/doc/html/latest/driver-api/usb/power-management.html#usb-port-power-control) describes the USB2/USB3 peer relationship; the power action's complete domain, rather than the camera's ancestry alone, determines what must be checked.

The correction resolves both roots and checks serial descendants with path boundaries (`3-4` must not match `3-40`). All affected ports must initially report `disable=0`; otherwise recovery refuses without changing them. Missing device/root ancestry terminates with `OSError`, instead of climbing forever at `/`. After entering the power cycle, a `finally` block attempts to enable every affected port even after partial disable or an interrupted wait. An enable failure does not prevent attempts on the remaining ports, and the error is still propagated. Camera-unit cleanup remains separate. This restores the initially enabled state as far as writes succeed; it does not guarantee recovery after an unwritable port, process kill or host failure.

Use this condition on both the normal and peer port before applying the manual procedure above. Do not perform the cycle when the topology or initial port state cannot be established. Never infer that another arm is safe from the current arm's session lock alone.

## Verification evidence

Recovery verified 2026-11-05 on the site control PC by hand (steps above): direct read, HTTP 200, no further watchdog kills. The code path is covered by fakes only until it runs there.

2026-11-06 source candidate commit `f24dc07253664399b0b446c280a6286ca1ee4069` fixes the discovery gap. Test-only candidate commit `89df767de398bfac134802245c1745983c08f59b` reproduced eight failures and two controls; the USB cases cover a peer-only OpenRB and five missing-chain cases without an unbounded test. Remote execution of `test/test_omx_upkeep_identity.py`, `test/test_omx_cell_upkeep.py` and `test/test_omx_joint_jitter.py` then passed 31 tests, skip 0, NEW/known/flaky 0. These use filesystem and diagnostic-trace fixtures. No real USB power cycle, SSH operation, service change or new hardware acceptance was performed. Publication and deployment of this source are separate gates.

The independently developed recovery-cleanup correction has landed locally; publication is a separate gate. On the model test PC, the test-only revision reproduced all seven added cases as expected failures (16 existing tests passed); the corrected revision passed all 23 tests, with no skips or NEW failures. Both used environment `35327e86830df3ba`, freeze `906d7aca580f620b`. Topology cases use temporary filesystem symlinks and recovery writes use fakes; no USB power or arm was operated. These regressions do not establish actual camera recovery or field acceptance.

## When to apply

Unit restart loops or 503 on a USB camera after a hub, cable or power event, and `v4l2-ctl` on the node returns nothing. If the direct read streams, the fault is in the service, not USB. If the speed is USB2 for a D435, also fix the cable or port (depth needs USB3, see `omx-cell-device-identity-after-rewiring-2026-10-31.md`).
