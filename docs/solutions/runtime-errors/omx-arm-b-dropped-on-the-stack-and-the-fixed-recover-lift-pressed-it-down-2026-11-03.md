---
title: arm_b dropped onto the container stack, and the fixed recover lift pressed it further down
date: 2026-11-03
last_updated: 2026-11-03
category: runtime-errors
module: deploy/robot/omx (cell_auto_pick.py pivot, cell_pipeline.recover, cell_unwedge.py, cell-params)
problem_type: runtime_error
component: deployment
severity: high
symptoms:
  - "goto above_pick to an over-target pivot: wrist_flex following error >5 motor degrees; command=3333, current=3276"
  - "the extended arm came down on the stacked containers; one tier fell over"
  - "cell_pipeline --stage recover: the same wrist_flex error again, at 62 % PWM, the arm did not move"
  - "unwedge counted lift commands as clearance while the shoulder oscillated with zero net displacement"
  - "park returned ok=true with settled=false but recovery reported success"
root_cause: wrist_overload_and_a_pose_specific_recovery
resolution_type: code_fix
---

# arm_b dropped onto the container stack, and the fixed recover lift pressed it further down

## Problem

On 2026-11-03 at 04:05 a supervised `cell_auto_pick --commissioning` carry on arm_b sent the arm to a pivot over the
target container. On the way the wrist_flex fell more than 5 degrees behind, the guard turned torque off, and the
extended arm came down onto the stack. `cell_pipeline --stage recover` then stopped on the same wrist error.

## What led there

1. The pick was refused for "no finger room: 26.0 / 6.0 mm". `auto.finger_mm` was still 8 mm, the old gripper's value.
   The jaw v2.1 (Jira KAN-107 STL) is a 1.1 mm plate with a 0.9 mm pad strip, and the ship plate's 6 mm cell gaps
   were designed for it. With 2.0 mm the room check passed. This change was right and is kept.
2. The pick then needed a map bias near the target. No region was saved, and no clear point lay within 80 mm. The
   over-target pivot was off because the pivot height (0.10 m) did not clear the column tops by 30 mm.
3. To enable it, the pivot height was raised to 0.155 m and `pivot.over_top_mm` to 95 for a three-tier column.
   **This caused the drop.** Holding the extended arm 5 cm higher loads the XL330 wrist_flex more. The same
   wrist_flex error is recorded on 10-29 and 10-31 for goto and lift moves. Nobody checked that history before
   raising the height. Both values were reverted on the field PC the same morning.

## Why the built-in recovery failed

`cell_pipeline.recover` lifts with a fixed `jog elbow_flex.pos -5 wrist_flex.pos 4`. That reverses a 15 mm
top-down descent (2026-10-25). Here the arm lay forward on the stack: elbow −1.9 and wrist 59.4, against home 53.1
and 51.6. Both deltas pointed away from home, so the jog pressed the arm further onto the containers. It also asked
the weak wrist to lift the arm's end, and the wrist stalled at 62 % PWM, 4.8 degrees behind.

## Fix

- `cell_unwedge.py`: only shoulder_lift ("lift") and elbow_flex ("pull") move, one unit toward home per step. The
  wrist gets no command. After each step a rule reads every body joint's lag:
  - over 1.2 units: back off by half a step and try the other joint;
  - both joints strained in a row: stop for a person;
  - measured shoulder displacement reaches 12 units toward home from the initial readback: request park;
  - report recovered only when park confirms settlement and measured body joints are within the runner's home tolerance.

  Each step keeps top and side frames and a decision row. The original field report records that arm_b was freed in
  21 steps with no strained step and then parked. That trial predates the success-condition correction below.
- `cell_pipeline.recover` with nothing held now uses `cell_unwedge`, and no longer opens the jaws to `grip_open`
  (62). Opened that wide on top of a stack, the fingers push the neighbours. With a box held it keeps the old path.

## 2026-11-03 success-condition correction (host verification)

The following refs identify local review/test commits at this pre-publication checkpoint; their D-868 merge-commit
publication is pending, and this section does not claim they are deployed.

Review of candidate `0c71fb0e2a` found that its clearance counter counted accepted lift commands. Starting at
HOME + 0.25, its direction changed at home and the fake actuator oscillated: 21 steps produced zero net shoulder
displacement but triggered park. The runner also legitimately returns `ok=true, settled=false` after a settlement
timeout; checking only `ok` reported recovery without proving home.

The correction in `f81b8315d0` fixes the lift direction from the initial measured shoulder and checks signed measured
displacement. A jog changes the runner's held target, so its step is clamped against that target's remaining distance
to home. Reaching or crossing home before clearance stops the attempt. Park success requires positive `ok` and
`settled`, finite body readback and measured home error within the runner's `SETTLE_TOL`. Missing measurements and
failed backoff stop the attempt. The clearance unit is a shoulder joint unit; this check does not measure TCP height.

The committed RED `1bd891afdf` produced four expected failures and three passes remotely. The reviewed source
`f81b8315d0` then passed all 55 unwedge and pipeline cases with no skips or new/known/flaky failures. The recovery
fake now updates measured state and models park settlement instead of always returning unchanged positions.
These are host regression results; a supervised D-911 trial of the corrected revision remains required for field
acceptance. Guard, torque and session rules remain in force; preserve stopped/stuck outcomes for operator recovery.

## Next time

- Before raising a goto or pivot height over an extended reach, grep the runner logs for wrist_flex following errors
  on that arm. Height costs wrist torque. A taller obstacle means a different approach, not a higher hover.
- After a gripper change, re-measure every gripper value in cell-params and the chunk library together:
  `auto.finger_mm`, `gripper.held_30mm`, `gripper.gap_mm_per_unit` and the library's `gripper_closed`.
  The v2.1 jaws close at 48.6, and the library's 46.6 makes them push each other. The opening map
  (52.3 for 30 mm, 10.4 mm per unit) is still the 10-29 measurement.
- A dry run measured 26/10 mm of finger room where the live run measured 26/6. Plan with the live numbers.
