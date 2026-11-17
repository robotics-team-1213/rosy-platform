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
  Normal roll travel lag is about 0.7 units. **Superseded 2026-11-06: see the correction below.**
  - `test_a_blocked_wrist_roll_holds_at_low_pwm_before_the_guard_drops_the_arm` replays the 23:19 shape.
  - `test_a_wrist_roll_travel_lag_is_not_a_block` guards against false holds.
- The hold text lists the other joints' lags (`(lags: shoulder_pan 1.3, ...)`). A second joint lagging with the
  first shows in the message itself.
- `motor_health.keep_fault`: each guard fault writes `faults/<owner>-<utc>.json` (`rosy.motor-fault.v1`, every joint)
  next to the snapshot, and saves the local camera view frames named in `ROSY_OMX_FAULT_FRAMES` (default: the camera
  view unit's top and side on port 8767; empty turns it off). The snapshot keeps
  only the public reason, and the next session overwrites it. Before this, no frame of any fault existed.
- Fleet: the monitor flags the joint the guard named (`fault: true`), Fleet keeps each arm's last 20 stops, and the
  cell page's `고장 이력` lists the stopped joint, every joint lagging over 1° with it, and the camera frames on
  screen when the stop arrived.
- Idle fold (2026-11-03, tests only, not yet seen on an arm): a fold out of a hold had strain detection off
  (`not self.fault`) and counted as home when `SETTLE_S` ran out, so it pushed a blocked roll and could turn torque
  OFF away from home. Now a fold watches for strain, is home only when settled, and an idle fold a hold stopped is
  tried once more after `runner.idle_retry_s`; a second hold keeps the arm and reports `person_needed`
  (`test/test_omx_runner_idle_fold.py`).

## Correction (2026-11-06): the fix above made false holds on arm_b

`ROLL_BLOCK_LAG` assumed a roll travel lag of about 0.7 units. On arm_b it steps while going negative, and its lag saws up
to about 1.6 and grows with the angle. The rule held it near -13, -15.7 and 9.89 in free air. Those holds were read as a
stuck wrist or a taut cable for three days. A wrist floor (`joint_min`), narrowed pivot yaws and a cable-check request
followed, and they blocked the remap and the grasp by the ends.

- **Evidence:** all 8 recorded holds kept moving afterwards (0.7-1.4 units in the next 0.5 s) at PWM about 40 of 300.
  Replaying the old rule over every trace stops at those same angles.
- **Fix:** `ROLL_STILL`/`ROLL_STILL_TICKS`. A rising lag past `ROLL_BLOCK_LAG` holds only after 0.5 s of stillness, or at
  `STRAIN_LAG` (4.0 deg, short of the guard's 5).
- **On the arm (18:35, free air, closed jaws, one pose):** 20 -> 0 -> -13 passed with no hold. On the way to -30 the new rule
  held near -20.9 (lag 2.1, PWM -63), and the joint still moved on to -21.81. That is not a wall either: the steps get
  longer than 0.5 s there. Use about -18 as the floor at that pose. Why the lag grows with the angle is not known.
- **Not shown:** that the new rule stops a real block in time on the arm. Only the tests cover it. The arm_a stops of
  2026-11-01 were real (a container against the jaws, pan stalling with the roll).

## Correction 2 (2026-11-12, arm_s live test): `ROLL_BLOCK_PWM = 0.20` and `retreat` lead-frame trim

During the 2026-11-12 fast pick-and-debate live run on `arm_s`, `start_to_partial` rotated `wrist_roll` from `+28.0` to `-8.13` and stopped near the end of the trajectory (`present = -6.30, target = -8.13, lag = 1.83 units`) with `contact: wrist_roll lag 1.8 units at PWM -44 of 300`, followed on `retreat` by `ValueError: shoulder_pan: following error >5 motor degrees`.

- **Why `wrist_roll` held at `PWM = -44` (`14.6%` of cap):** Motor 15 (`XL330`) runs with `p_gain = 400, i_gain = 0`. A `1.8 unit` (`~3.2°`) error produces only `PWM = -44 of 300` (`14.6%`), where proportional torque exactly balances USB wrist-camera cable torsion + gear stiction, so `wrist_roll` sits still (`still = True`) at the tail of a long sweep without hitting any obstacle. True blocked-roll incidents (e.g. the 2026-11-01 `arm_a` jaws-against-container stops) reached `PWM = 82 of 300` (`27.3%`) or kept climbing past `STRAIN_LAG` (`2.2 units`).
- **Why `retreat` tripped the guard (`shoulder_pan >5°`):** `Runner.hold()` saved `self.played[::-1]` as `retreat_frames` where `self.played[-1]` was `1.6 units` ahead of `present` (`self.target`), and left `self.pace_floor = 1.86` and idle `self.trend` rows intact. When `retreat` started, it jumped `+1.6 units` forward to `played[-1]` and reversed a 270-frame trajectory at full speed without acceleration ramping.
- **Fixes (`runner_strain.py`, `chunk_runner_run.py`, `chunk_runner_commands.py`):**
  1. Added `ROLL_BLOCK_PWM = 0.20` (`60 of 300`): the `still` check at `1.5 <= lag < STRAIN_LAG` triggers only when `abs(pwm[4]) / max(1, cap[4]) >= ROLL_BLOCK_PWM`, while `lag >= STRAIN_LAG` (`2.2 units`) still holds unconditionally.
  2. Reset `pace_floor, paced, pace_last, trend` on `hold()` and at the start of every `run`/`goto`/`park`/`chain`/`retreat`.
  3. In `retreat`, when `len(raw) > 25`, trim unreached leading frames ahead of `runner.target` (`present`) and pass `raw[best_i:]` through `retime(..., 0.65 * GUARD_UNITS_PER_S, start=runner.target)` so `retreat` smoothly accelerates backward from `present`.

Before calling a joint stuck, plot present against sent after the hold. A joint that keeps moving was not stopped by anything.

## Next time

- Read the fault's tick rows for **all** joints and the motion direction before suspecting a motor, gains or load.
  Compare with the last run of the same library that passed.
- Both arms' `motor-health-*.jsonl` share one folder, and the file name does not name the arm. Filter by the
  `usb_port` board serial. A file from the other arm was misread once during this diagnosis.
- Any per-joint safety rule (`[:4]`, `range(4)`) must say why each excluded joint is safe. The roll was excluded
  from `FOLLOW_STOP` for teach lag on purpose. Its exclusion from the strain hold had no reason.
- Before moving an arm after a fault, look at the cameras around its path. A neighbour arm's push can move
  objects into it.
