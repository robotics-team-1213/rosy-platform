---
title: arm_b's elbow latched an overload at home, wedged 1 degree short by a box hanging from the jaws
date: 2026-11-03
category: runtime-errors
module: deploy/robot/omx (chunk_runner.py, joint_push.py)
problem_type: runtime_error
component: deployment
symptoms:
  - "UNSAFE END: follower torque or caps not confirmed restored"
  - "Failed to write 'Torque_Enable' on id_=13 with '0' after 3 tries. [RxPacketError] Hardware error occurred"
  - "hardware_faults: {13: {hw_error: 32, packet_alert: true}}; caps_restored: follower 13 i_gain: comm 0 error 128"
root_cause: integral_windup_at_a_standstill_nobody_watched
resolution_type: code_fix
---

# arm_b's elbow latched an overload at home, wedged 1 degree short by a box hanging from the jaws

## Problem

Supervised `cell_auto_pick --commissioning` on arm_b, episode `20261103-132422-pallet-to-pallet` (session
`75d927d1…`, motor-health `motor-health-1793679551361952273.jsonl`, fault record
`faults/arm_b_follower-20261103T042721-a3644c.json` with top and side frames). The look over the dense box row
refused, the arm parked home, and 18 s after it arrived the elbow (ID 13, XM430) latched Hardware Error Status 32
(overload). The session could not turn ID 13's torque off or restore its I gain and ended UNSAFE.

## What happened, from the health log (motor-health samples, raw counts, t from session start)

| t (s) | elbow cmd / present | elbow PWM (cap 600) | gripper cmd / present, PWM (cap 300) |
|---|---|---|---|
| 389-426 | 2411 / 2412 (hover) | -3..-26 | jaw-mark toggles 2074 <-> 2538 |
| 432 | 2411 / 2413 | -241 | **1998 / 2226, -278**: the jaws closed on a box edge and stayed there |
| 444-468 | folding 2416 -> 3134 | -137 .. 261 | 1998 / 2226, -286..-291 the whole fold |
| 468.5 | 3134 / 3123 (11 counts = 0.97 deg short) | 261 | same |
| 471.8 -> 486.7 | 3134 / 3123..3128, not moving | 295 -> 476, **+4 every 0.23 s** | same |
| ~487 | fault: ID 13 hw_error 32 | | |

The side frame at the fault shows an orange box tilted up against arm_b's jaws: the box rode home in the jaws and
wedged against the pallet edge, so the elbow could not finish the fold. The integral term wound the PWM up at a
standstill until the motor's own overload protection latched.

The first episode of the same session parked to 3134 exactly at PWM 30, flat for 150 s. That flat hold is what a
folded home looks like.

## Why nothing stopped it

- `stalled` (PWM >= 285 and > STALL_GAP 4 units short) never fired: the elbow was only 0.97 units short.
- `strained()` only watches a running chunk; the park had already settled (0.97 <= SETTLE_TOL 3), so the arm was
  at rest.
- The guard's overload-risk check needs error > 2 deg at >= 90 % of the cap; this was 1 deg at 79 %.
- Nothing checked the jaws outside a grasp chunk. They had been blocked 5.8 units short of closed at 97 % of their cap
  for 55 s, so the box was carried home.

## Fix

`deploy/robot/omx/joint_push.py` (`pushing()`), called by `chunk_runner` on every 1 Hz health sample:

- **Wind-up at a standstill.** Over the last 4 samples, a load-bearing joint's target and position are still, it is
  >= 0.5 units short, and |PWM| climbs on every sample, by >= 40 in total, to >= 40 % of its cap.
  - During a chunk the runner holds (`contact in <chunk>`).
  - At rest it sets the target to where the arm is and reports `pushing at rest` with `person_needed`. If the arm is
    folded home, `idle()` ends the session immediately (torque OFF while folded) instead of waiting `idle_stop_s`.
- **Jaws in a park.** The jaws are still, more than 2 units from the park's gripper target, at >= 50 % of their cap
  on two samples. The park holds instead of folding the object home.

- **A closing `grip` that catches something reopens.** This is where the incident started. If a grip closes from
  free jaws (present within EMPTY_MARGIN of the old target) and the jaws then stop short at load, the runner returns
  them to where they were and reports `caught: true`. The box is let go where it was pinched. A grip sent while
  already holding (`recover`'s re-tighten) is not armed, so it cannot drop a held box.

The thresholds are measured cell params (`windup.rest_rise` 40, `windup.rest_pwm` 0.4, `windup.jaw_pwm` 0.5,
`windup.jaw_gap` 2.0), not constants. `push_replay.py` is the loop that keeps them honest:

1. Run it over the session's motor-health logs after each supervised session.
2. A hit before a fault is a catch. A hit in a clean session is a real press or a false alarm: look at it.
3. Compare the per-joint normal envelope with the thresholds before changing them.

On 2026-11-03 the normal standstill wind-ups reached a rise of 79, but only at PWM <= 198 of 600. The real presses
wound past 273. That gap is what the two gates together keep.

Tests: `test/test_omx_joint_push.py` replays the 13:27 numbers and the normal holds.
`test/test_omx_chunk_runner.py::test_an_elbow_winding_up_short_of_home_ends_the_session_folded_before_it_overloads`
and `::test_a_park_with_something_in_the_jaws_holds_instead_of_folding_it_home` cover the runner.

## Verification

- Offline replay of `pushing()` over every follower motor-health log on the field PC (1 Hz):
  - **arm_a** (`…FF06202D`, 32.6 h): 0 hits.
  - **arm_b** (`…FF061D2D`, 5.1 h): 3 hits.
    - Two are this incident. The first fired at t = 469 s, about 17 s before the overload.
    - The third (session 04:51, t = 424-426 s) was a real press: the elbow sat 0.9 deg short with PWM 225 -> 262. When
      the jaws opened it dropped 16 counts past its target, so the jaws had been resting on something.
- Remote pytest: joint_push, chunk_runner, runner_idle_fold and cell_params all passed.
- Not yet run on the real arm: no supervised run since the fix.

## Recovery (verified 2026-11-03 about 15:33 field time)

An overload latch clears with the Dynamixel **Reboot** instruction; no power cycle is needed.

1. Make sure no session holds the bus.
2. Read torque, hardware error and caps on every motor.
3. Reboot only the latched ID, and only when every motor reads torque 0.
4. Read the registers again.

Result for ID 13: hw_error 32 -> 0, alert cleared, pings normally. All six motors read torque 0, pwm_limit 20 and
i_gain 0, so the session's failed I-gain restore was undone by the reboot. The reboot does not move the arm and
leaves torque OFF. The latch only goes away; the cause does not. Before torque goes on again, a person checks that
nothing is wedged in the jaws or against the arm.

## The handling is a pipeline now

Handling this incident by hand took about an hour of reading logs, frames and registers. `omx_incident.py` now does
the same steps; `record_session --arm` runs it at the end of every session.

1. It collects session.json, the runner status rows, the fault records and frames, and the health log.
2. It decides by measurement, the judge seat's rule. A reboot is offered only for an overload or voltage latch, with
   every motor at torque 0 and the arm folded at home. Any physical sign holds the arm for a person.
3. It writes a `stage: incident` decision row and `incidents/<stamp>-<arm>/agenda.md`.
4. It runs the allowed reboot.
5. It writes `incidents/HOLD-<arm>.json`, which refuses the next session until
   `omx_incident.py clear --by --note` records who checked the arm.

The decision model (`ROSY_DECISION_MODEL`, an Ollama URL) only explains the fault frames. It never chooses an
action. On the 13:27 frames, qwen3-vl:8b saw "an orange block wedged between the jaws and the platform, the elbow
blocked". It called arm_b the "right" arm, which shows its left/right cannot be trusted.

Replayed on the real 13:27 `session.json`, the pipeline reached the same decision as the hand diagnosis:
reboot_latched, then hold for a person. The field PC has no key to the AI PC's model, so on the field the pipeline
runs measurement-only.

## Next time

- A hold that is flat is normal. A PWM that climbs on every sample at a standstill is pushing against something:
  look at the rise, not at the error size or a fixed PWM threshold.
- The cause was upstream: the jaw-mark toggles at the hover over a 6 mm-gap row caught a box. The new checks stop
  the damage; the look still needs to stop opening the jaws among the boxes.
- arm_a runs the same runner and gets both checks; its 32.6 h of logs show no wind-up so far.
