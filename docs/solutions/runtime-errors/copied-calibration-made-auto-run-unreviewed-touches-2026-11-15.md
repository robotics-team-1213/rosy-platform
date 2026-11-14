---
title: A copied scratch calibration made cell_calibrate auto run steps nobody reviewed
date: 2026-11-15
module: deploy/robot/omx cell_calibrate auto
problem_type: runtime_error
component: omx calibration
severity: high
symptoms:
  - "A run reviewed as 'one remap point' instead drove a surface probe to the belt (about 200 mm reach) and then towards the pallet, where it stopped on contact."
  - "The run log shows todo [surface belt, surface pallet] instead of [remap, regions]."
root_cause: implicit_step_selection
resolution_type: code_fix
applies_when:
  - "Running cell_calibrate auto on a real arm with a config or calibration copied from an earlier run."
  - "Any D-911-reviewed plan that covers only some of auto's steps."
tags: [omx, d-911, calibration, remap, surface-probe, arm_b]
---

# Name the reviewed steps: auto runs whatever check finds stale

## What happened
On 2026-11-15 at 01:26, arm_b was to make one reviewed hover mark (plan F). The run's folder was made by copying plan E's calibration file and reference image. Plan E's remap had just refreshed both.

`check` therefore found the map present and the camera unmoved. `stale` then returned the next stale steps, which were surface touches on belt and pallet, and `auto` ran them:
- **Belt:** an extended reach of about 200 mm, with no contact.
- **Pallet:** in transit, wrist_roll passed -30, inside the wrist-holder interference band, and the arm stopped on light contact (PWM -60/300).

The arm retreated and parked. The runner recorded the stop as "touched surface_z 0.1527", which is not a real surface height. Fleet opened an incident and held arm_b.

## Fix
- `cell_calibrate.py auto --only remap regions` runs only the named step kinds. Steps outside the list are dropped even when `check` finds them stale (commit a522d43589).
- Until that is deployed, a scratch run starts from an empty calibration file. `check` then reports `missing_map`, and `stale` returns only `remap` and `regions`.
- Confirm `todo` with a `check` dry run before any `auto` on the real arm.

## How it was verified
- The rerun with an empty calibration showed `todo [remap, regions]` in `check` and ran only the hover. Source: the workspace record 2026-11-13 omx-camera-intrinsics-options, last sections.

## Next time
- Treat `auto` as "do everything stale", not "do the step I planned".
- Pass `--only` for every supervised run.
- Never copy a calibration or reference file from a finished run into a new run's folder.
- A surface value written by a stopped probe is the stop height, not a surface. Discard it.
