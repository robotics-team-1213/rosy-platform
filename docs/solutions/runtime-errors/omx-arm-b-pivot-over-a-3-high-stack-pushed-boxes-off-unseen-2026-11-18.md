---
title: arm_b's pivot over a 3-high ship stack pushed two boxes off and raised no incident
date: 2026-11-18
category: runtime-errors
module: deploy/robot/omx (cell_calibrate_auto.over_target, cell_pivot, cell-params pivot.over_*)
problem_type: runtime_error
severity: high
tags: [omx, arm_b, pivot, over_target, stacks, contact]
applies_when: a pivot, hover or look is planned over a site whose box tops vary with stacking
related: omx-arm-b-dropped-on-the-stack-and-the-fixed-recover-lift-pressed-it-down-2026-11-03.md (the first over-target pivot accident)
---

## Symptom
- On 2026-11-18 at 03:16, `cell_calibrate auto --only pivot-near` ran arm_b at pallet (0.1503, -0.1285).
  - The arm stopped with "yaw arc 109.8 < 110".
  - The second run (03:23) stopped with "jaw sides disagree 6.7 mm".
- Neither run raised an incident, and the report said "touched nothing".
- The pivot frames show what happened. Between `00/try-*-open.jpg` (yaw -110) and `01/try-00-closed.jpg` (yaw -87.5), the orange top box and the pink box under it were pushed off the 3-high stack. The orange ended up tilted toward arm_a.
- Every later pivot and dry run was then judging a scene that had already changed.

## Cause
- `over_target` judged clearance with `pivot.over_top_mm` 71 mm. That value is the top of 2-high columns, measured on 11-01.
- The 3-high stack's top is about 104 mm above the plane.
  - With view 0.125 m and surface_z -0.01, the planner computed 48 mm of clearance.
  - The real gap was about 20 mm. FK z of the jaws settled at 0.117-0.123, and the jaws open during the pivot.
  - Even counting three tiers of 32.4 mm, the gap is only about 31 mm on paper, which is too thin for a jaw that opens and swings.
- Pushing a box of about 20 g does not show in servo load. The contact and wind-up incidents therefore never fired.

## Fix
- `cell_calibrate_auto.over_target` now returns False on any `stacks` site.
  - The pivot must find a clear point, or it refuses.
  - Test: `test_a_pivot_never_goes_over_a_ship_stack` in `test/test_omx_cell_calibrate.py`.
- The cell params were also changed: `cell-params-stack.json` now has `pivot.over_target` 0, with evidence.
- No guard was weakened.

## Recovery and checks
- When a pivot over boxes fails, compare the first closed frame with a later one before trusting any mark or rerunning it.
  - The frames are in `work/pivot-frames/<site>-<stamp>/NN/try-*-closed.jpg`.
  - A moved box is visible there even when no incident was raised.
- A person restacks the ship. The arms do not re-pick a box that is tilted against another.

## Apply when
- The pivot, a hover, or any look move happens over a site whose tops vary with stacking.
- A light object can move without load: servo-side contact detection does not prove "touched nothing". Check the frames.
