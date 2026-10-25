---
title: Under the guard, any contact on an OMX descent became torque off with the arm extended
date: 2026-10-25
category: runtime-errors
module: deploy/robot/omx (chunk_runner.py, cell_pipeline.py, guarded_native.py teacher mode)
problem_type: runtime_error
component: deployment
symptoms:
  - "ValueError: wrist_flex: following error >5 motor degrees during descend_place or descend_pick"
  - "record_session safe_end True, exit_code 1, torque 0 with the arm resting on the box or the Pinky edge"
root_cause: no_response_below_the_guard_fault
resolution_type: code_fix
severity: high
tags: [omx, guard, teacher-mode, contact, calibration-grid, arm-s]
applies_when: "a guarded OMX descent can touch the object, the tray or a neighbour, or a placement grid is planned on a surface"
---

# A contact on the descent became a guard torque-off

## Problem

Arm S under the guard's teacher mode (2026-10-25). Two descents touched something:

1. A tray calibration point 15 mm toward the Pinky. The box's centre was on the tray, but its edge overhung the Pinky frame.
2. A grasp turned 25° by a rough camera yaw, which put the jaws on the box's corners.

Each time, the wrist was pushed past the guard's 5° following-error bound. The guard turned torque off, which is its rule, and the extended arm came down where it stood. The second time, the box later left the tray and the camera's view.

## Cause

Nothing responded below the guard's bound. The chunk runner's own following-error stop (25 units for 1 s) is far looser than the guard's, so the first response to any contact was a hard stop with torque off. The placement plan also tested only the box's centre against the surface, never its footprint.

## Fix

- Soft contact in `chunk_runner`: during descend, grasp and release chunks, a body joint that lags the command the guard actually sent by more than 1.5 units (≤ 2.7°) for 2 ticks counts as pressing on something. The runner holds where it is with torque on. `retreat` replays the chunk's played frames in reverse, and `park` clears the contact state. Mutation check: with detection off, `test_a_soft_contact_holds_with_torque_on_then_retreats_along_its_path_and_parks` fails. `test_normal_following_lag_is_not_a_contact` guards against false stops.
- `cell_pipeline`: on a soft contact it retreats, parks, logs the case, and the judge seat decides a retry. Calibration grid points must keep the whole box (half a box inside `flat_px`) on the flat zone, judged by the coarse map before the arm goes there. The grid is centred on that zone with 10 mm spacing, using an affine map.
- `cell_pipeline --stage recover --person-at-switch` codifies the recovery done by hand: seed at the present pose, lift clear (jaws kept closed if a box is held), place the box at the start or fold home. It refuses without the confirmation.

The guard's own rule is unchanged.

## Recovery that worked (4 times)

With a person at the switch: start a session (the guard seeds at the present pose), close the jaws if a box is held, `jog elbow_flex.pos -5 wrist_flex.pos 4` (reverses a 15 mm top-down descent), then place at the start or `park`, then `stop`. Each recovery ended with `safe_end` true.

## Next time

- The soft contact thresholds are untested on the real arm. Watch for false stops on the first runs.
- Plan placements by footprint, not by centre.
- A box that leaves the top camera's view cannot be found by any camera on this PC (the `arm_a_wrist` service has no device; the LG camera is the laptop's own). Keep placements well inside the tray.
