---
title: A blocked wrist roll reached the guard's 5 degree stop unseen, and the fault text misled the diagnosis
date: 2026-11-02
category: runtime-errors
module: deploy/robot/omx (chunk_runner.py strained, motor_health.py fault)
problem_type: runtime_error
component: deployment
symptoms:
  - "ValueError: wrist_roll: following error >5 motor degrees; command=2657, current=2714 at the first goto from home"
  - "the session ends with torque off and the arm part-way out (next start state is not home)"
  - "the same goto passed minutes earlier; registers match the other arm; PWM only 2-28 % of its cap"
root_cause: strain_hold_ignored_the_unloaded_joint
resolution_type: code_fix
severity: high
tags: [omx, guard, wrist-roll, following-error, motor-health, diagnosis, arm-a]
applies_when: "an OMX session ends on a guard following error, or a hold/strain rule is written for some joints only"
---

# A blocked wrist roll reached the guard unseen

## Problem

On 2026-11-01, arm_a (right) stopped four times on its first goto from home (15:12, 15:18, 23:19, plus one more in
the same window). The guard ended each session with `wrist_roll: following error >5 motor degrees` and turned
torque off. Each time the arm was left part-way out. The same library and goto had passed at 15:07.

Two wrong leads cost a day:

- **CPU contention.** It failed with no test jobs running.
- **Gains.** ID 14 and ID 15 registers matched arm_b.

The fault text "always about 57 counts" looked like a signature. It is not: 57 ticks is the guard bound itself
(4096/360 × 5 = 56.9). Every guard following-error message carries `command − current ≈ 57`.

## What the data showed

Read the tick rows of the session's `motor-health-<ns>.jsonl`, not the fault line:

- wrist_roll followed within 1° and then stopped dead (2718 → 2714 → 2714) while its command ran on. PWM rose only
  to 82 of 300.
- **shoulder_pan stalled at the same moment** (2205–2226 in all three runs).
- It happened only in the pan +/roll − direction. The park back (pan −/roll +) followed within 0.4°.

Two joints stalling together, in one direction only, after the same motion had passed, means an outside restraint:
contact, or a cable going taut. It does not mean a weak or broken roll motor. The top and side cameras showed the
arm_a jaws against a container that arm_b's push had left crooked at 14:40. A cable is not ruled out. The record is
`Rosy/docs/workspace-records/2026-11-02/arm-a-wrist-roll-stall.md`.

## Cause in code

`Runner.strained()` covers goto, park and lift. It holds a joint with torque on when its lag keeps rising **and** its
PWM is at half the cap. It looked at `MOTORS[:4]` only. The wrist roll carries no load, so a blocked roll pushes at
low PWM. No rule held it, and the guard's 5° stop dropped the arm. The pan lag, 1.3 units at 43 % PWM, was also
under the strain thresholds.

## Fix

- `chunk_runner.ROLL_BLOCK_LAG` (1.5 units, ≤ 2.7°): a wrist roll whose lag keeps rising past it holds at any PWM.
  Normal roll travel lag is about 0.7 units.
  - `test_a_blocked_wrist_roll_holds_at_low_pwm_before_the_guard_drops_the_arm` replays the 23:19 shape.
  - `test_a_wrist_roll_travel_lag_is_not_a_block` guards against false holds.
- The hold text lists the other joints' lags (`(lags: shoulder_pan 1.3, ...)`). A second joint lagging with the
  first shows in the message itself.
- `motor_health.keep_fault`: each guard fault writes `faults/<owner>-<utc>.json` (`rosy.motor-fault.v1`, every joint)
  next to the snapshot, and saves the local camera view frames named in `ROSY_OMX_FAULT_FRAMES`. The snapshot keeps
  only the public reason, and the next session overwrites it. Before this, no frame of any fault existed.

## Next time

- Read the fault's tick rows for **all** joints and the motion direction before suspecting a motor, gains or load.
  Compare with the last run of the same library that passed.
- Both arms' `motor-health-*.jsonl` share one folder, and the file name does not name the arm. Filter by the
  `usb_port` board serial. A file from the other arm was misread once during this diagnosis.
- Any per-joint safety rule (`[:4]`, `range(4)`) must say why each excluded joint is safe. The roll was excluded
  from `FOLLOW_STOP` for teach lag on purpose. Its exclusion from the strain hold had no reason.
- Before moving an arm after a fault, look at the cameras around its path. A neighbour arm's push can move
  objects into it.
