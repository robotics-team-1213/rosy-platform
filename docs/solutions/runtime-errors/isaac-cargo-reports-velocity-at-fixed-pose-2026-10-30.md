---
title: Isaac's instantaneous cargo velocity is contact chatter; judge speed by the pose change between samples
date: 2026-10-30
category: runtime-errors
module: learning/envs/isaac (mapped_stack_fixture.py, mapped_stack_task.py)
problem_type: runtime_error
component: simulation
symptoms:
  - "a stability window never closes although every box sits within a fraction of a millimetre of its target"
  - "the same nonzero get_linear_velocity()/get_angular_velocity() value repeats across many samples"
root_cause: instantaneous_velocity_is_solver_chatter
resolution_type: code_fix
severity: medium
tags: [isaac, physx, velocity, stacking, stability]
applies_when: "a stability or settle gate reads rigid-body velocity from Isaac Sim after bodies come to rest"
---

# Isaac's instantaneous cargo velocity is contact chatter; judge speed by the pose change

## Problem

The nine-container run `ce56c57aef58554497f73388367db7bf` (Isaac SDK 6.2.0.0, source `6cb76e6059`)
placed every container, then failed the final 1.1 s stable window. Boxes 5 and 8 reported
.014 and .021 m/s (limit .01) on every sample for 26 s.

## Cause

Their recorded poses did not change by more than 1 um over those 26 s. A body moving at
.014 m/s would have travelled more than 300 mm, so the reported velocity was not motion.

The mechanism is not established. The first version of this note blamed PhysX sleep. That is
wrong for this scene: run `39bebc33ccb75f409ba2f5700dadc616` read the cargo sleep threshold through
`RigidPrim.get_sleep_thresholds()` as 0.0, so these bodies could not sleep. Raising it to 5e-5 for
settled cargo changed nothing: that run reproduced run fa6f frame for frame (10898 frames, same
failure sample).

## Fix

First `684618d077` zeroed the velocity of a pose unchanged within 1 um. That was not enough: run
`b326b5857ef955aca66141fa9ac78fab` named the boxes that still blocked the prior-stack window. They
reported up to .18 rad/s while their poses moved at most 6 um per 0.1 s step. A real .18 rad/s turn
moves a box edge about .25 mm in that time, so Isaac's instantaneous cargo velocity is contact-solver
chatter, not motion. It is not specific to a frozen pose.

`67c54a1913` replaces the rest test with `measured_motion`:

- Velocity and angular velocity are the pose change since the previous sample divided by the elapsed
  ticks (12 ticks = 0.1 s).
- Every stable window keeps that reference sample.
- The verifier recomputes the same values from the recorded poses. Raw readings stay in the report.
- The .01 m/s and .1 rad/s limits are unchanged. Sliding or toppling still moves the pose and fails.

Regressions:

- `learning/envs/isaac/test/test_stack_settling.py::test_measured_motion_is_the_pose_change_over_the_sample_step`
- `test_a_fixed_pose_with_a_reported_speed_is_at_rest`

## Evidence and limits

- ce56: fixed poses with a repeated .014/.021 m/s.
- b326: per-box diagnosis with micrometre pose steps against .10-.18 rad/s readings.
- Run `2cdbdd56df3851aeb9ff2701e2014bdd` at `bb39f438a5` then accepted all nine gapped containers.
  Final row gaps were 3.22-4.00 mm, with no unstable box, SDK exit 0, video, import and owned cleanup.
- An earlier note here called fa6f's 18 um drift "real micro-motion". That was wrong. Over the ~5000
  ticks since the last window it is a few um per step, the same chatter.
- Limits: one seed-42 IK-reference condition in simulation. Not a statement about the physical arm.

## Next time

- Before blaming a threshold, compare the reported velocity with the pose change between samples.
  If the pose does not move, the velocity is not motion.
- Do not reach for sleep thresholds here: cargo sleep is off (threshold 0) in this scene, and the
  simulation is deterministic per seed, so an identical rerun means a setting had no effect.
- Keep raw velocities in reports. Apply the correction in the judge, not in the sampler, so a
  reviewer can reproduce it.
