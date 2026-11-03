---
title: arm_b dropped onto the container stack, and the fixed recover lift pressed it further down
date: 2026-11-03
category: runtime-errors
module: deploy/robot/omx (cell_auto_pick.py pivot, cell_pipeline.recover, cell_unwedge.py, cell-params)
problem_type: runtime_error
component: deployment
symptoms:
  - "goto above_pick to an over-target pivot: wrist_flex following error >5 motor degrees; command=3333, current=3276"
  - "the extended arm came down on the stacked containers; one tier fell over"
  - "cell_pipeline --stage recover: the same wrist_flex error again, at 62 % PWM, the arm did not move"
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
  - shoulder up 12 units: park.

  Each step keeps top and side frames and a decision row. On the real arm it freed arm_b in 21 steps with no strained
  step, then parked home.
- `cell_pipeline.recover` with nothing held now uses `cell_unwedge`, and no longer opens the jaws to `grip_open`
  (62). Opened that wide on top of a stack, the fingers push the neighbours. With a box held it keeps the old path.

## Next time

- Before raising a goto or pivot height over an extended reach, grep the runner logs for wrist_flex following errors
  on that arm. Height costs wrist torque. A taller obstacle means a different approach, not a higher hover.
- After a gripper change, re-measure every gripper value in cell-params and the chunk library together:
  `auto.finger_mm`, `gripper.held_30mm`, `gripper.gap_mm_per_unit` and the library's `gripper_closed`.
  The v2.1 jaws close at 48.6, and the library's 46.6 makes them push each other. The opening map
  (52.3 for 30 mm, 10.4 mm per unit) is still the 10-29 measurement.
- A dry run measured 26/10 mm of finger room where the live run measured 26/6. Plan with the live numbers.
- Over the pallet box nearest arm_b (11:37-11:49 local), the jaws did open and close (60.9 / 51.3) but no look saw
  them: there the wrist hides both fingers at the 2.5 cm hover.
- Over the next box (12:39), the jaws never opened. Every `grip 62` read 49.33 at 50 mA. The gripper runs in mode 5,
  where Goal Current limits the force. The session raised Current Limit to 250, but Goal Current stayed at the
  baseline 50. With the library's `gripper_closed` 46.6 (the v2.1 jaws close at 48.67), every park drove them past
  contact, and 50 mA could not always pull them open again. So the hover saw no jaw mark because the jaws did not move.
  A trial look from the 0.10 m view height then reported a mark (a false blob) and passed. The descent with closed
  jaws landed about 15 mm beside the box, empty (19 mA). The trial was reverted on `feat/omx-look-raise`. A look at
  another height does not vouch for the hover.
- Fix: the session now writes the gripper's Goal Current with its Current Limit (`d189c9b332`). On arm_b, the jaws
  then opened to 60 and closed to 49.5. arm_b also has its own plan and chunk library with closed 48.8. Before a
  look, check that the jaws follow `grip` (state[5] moves) before blaming the camera.
- After the empty grasp, `lift_pick` tripped wrist_flex (5.1 deg) and the arm came down on the row again.
  `cell_unwedge` freed it in 21 steps with no block (field `20261103-124327-unwedge-decisions.jsonl`).
- The attempt record used to keep only the last hover hook's answer, which hid the unseen and false looks. Since
  `6dbf19e7b9`, the wrist step keeps every hook's answer under `hooks`. Until then, find them in `chunk-status.jsonl`
  (the `grip 50.5`/`grip 62.0` pairs are the jaw marks; state[5] shows whether the jaws moved).
