---
title: "rosy-io stop left the wheel torque on because a repeat SIGINT interrupted the driver close"
date: "2026-11-09"
category: runtime-errors
module: middleware/devices/pinky/bringup
problem_type: runtime_error
component: motor_driver
symptoms:
  - "D-986 re-approval begin FAILED with 'motor preflight must show both configured IDs' after every rosy-io stop"
  - "dynamixel_probe: FAIL DXL id=1 torque is already enabled; writing 0 to address 64 by hand made it PASS"
root_cause: signal_interrupts_cleanup
resolution_type: code_fix
severity: high
tags: [pinky, dynamixel, sigint, systemd, execstoppost, d-986]
---

## Cause

Journal of the stop (geg6, 2026-11-09): `bringup` died with `KeyboardInterrupt` inside
`DynamixelDriver.terminate()` at `time.sleep(0.1)`, which sat between the zero-RPM goal and
`_disable_all()`. The unit has the default `KillMode=control-group`, so systemd sends SIGINT to every
process in the cgroup, and `ros2 launch` forwards a second SIGINT to its children. rclpy's handler
absorbs the first; the second reaches Python as `KeyboardInterrupt` in the cleanup. Exit code -2,
torque still 1. rosy-navigation runs the same bringup node and had the same fault.

## Fix

- `terminate()` writes torque off before any sleep; `bringup.main` ignores SIGINT/SIGTERM in its `finally`.
- `rosy-io` and `rosy-navigation` get `ExecStopPost=+/usr/bin/python3 -I -B /opt/rosy/native-runtime/wheel_torque_off.py`
  (`deploy/robot/pinky_pro/native/wheel_torque_off.py`): write-only, address 64, IDs 1 and 2. If the port
  cannot be opened or a write fails it prints FAIL to the journal and exits 0, so a stop is never blocked.
  It also covers SIGKILL after `TimeoutStopSec` and a crash, which in-process cleanup cannot.
- The D-986 begin probe still requires torque off; nothing was weakened (see its addendum).

## Check

`journalctl -u rosy-io` after a stop shows `ok torque-off id 1 ... id 2`; `dynamixel_probe` then passes.
Next time a cleanup "never ran", read the journal traceback for where it was interrupted before blaming
the close path. A hand-installed drop-in `90-local-torque-off.conf` (11-09 hotfix) is redundant once this
release is on the robot; remove it then.

## Second fault found in the same re-approval (geg6 2026-11-09)

`navigation_approval_host.SystemOps.commit` ran `HERE / "os_storage_dispatch.py" --projected`. The API spawns
begin/seal from the release copy (`/opt/rosy/releases/<id>/deploy/robot/native/`), where the dispatcher's
`bootstrap_entry()` looks for `os-bootstrap` beside its own `parent.parent`, finds none, and answers
`{"phase":"HOLD"}` rc 1, so begin and seal failed with "did not reach the PROJECTED phase" although runtime.env
was committed. It now runs `/opt/rosy/native-runtime/os_storage_dispatch.py`, the image-installed copy.
