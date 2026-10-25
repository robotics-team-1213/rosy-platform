---
title: A taught OMX value is right for the plan and device it was taught with, not for every plan
date: 2026-10-25
category: logic-errors
module: deploy/robot/omx (cell_pipeline.py, cell_choices.py, chunk_runner.py, cell_perception.py)
problem_type: logic_error
component: deployment
symptoms:
  - "reset placed the box at the top-down plan's start, then judged it 'off the start' (top pixel ~4 cm from the profile reference)"
  - "coarse map stopped at 'grip closed': asked 40, then 47; the follower jaws stopped at 48.4-48.6 and pushed at the PWM cap"
  - "a 25 degree yaw read from the top camera turned the jaws onto the box corners"
root_cause: value_reused_outside_its_plan
resolution_type: code_fix
severity: high
tags: [omx, arm-s, taught-values, calibration, gripper, yaw, choices]
applies_when: "an OMX tool reuses a value from a leader demonstration, a taught chunk, a profile reference or a camera estimate in a different plan or on a different device"
---

# Taught values belong to their plan

## Problem

On 2026-10-25, the arm S cell pipeline (top-down chunks, coarse map, self-calibration) reused three values that had worked elsewhere:

- The profile's top reference pixel (134.5, 239.5). The taught (wrist-twisting) replay succeeded from it on 2026-10-24. The top-down plan's start is the arm point (72, 106) mm, which the top camera shows at about (160, 215), roughly 4 cm away. Reset placed the box correctly twice and still judged it "off the start", and the seat retried.
- The taught gripper closed value 46.6 is a leader value. The follower jaws end at about 48.5. Asked for 40, the gripper pushed at its PWM cap with no stop, because teacher mode bounds neither gripper following error nor gripper effort. Asked for 47, the jaws never "arrived", so the coarse map timed out.
- The top camera's box yaw comes from a ~30 px blob, which is rough. A box the arm itself placed is already square to the jaws, so a 25° turn put the jaws on its corners and the guard stopped.

## Fix

- `cell_choices.py`: each value is a set of candidates with source (taught, measured, sim) and real outcomes. The one with the best record for that purpose is used; the others are kept. Names carry the purpose, for example `pinky.start_pixel@topdown`, `gripper.closed@follower`, `pinky.grasp_yaw@topdown`. Taught values are not dropped: a taught value that keeps working beats a newer one that failed (`test_a_taught_value_that_keeps_working_beats_a_newer_one_that_failed`).
- After the arm itself places the box at the start, the pixel it shows becomes a measured candidate. Every candidate gets that outcome.
- `chunk_runner` never asks the gripper below the taught closed value. `grip_to` accepts jaws that stop and stay put as arrived.
- The grasp yaw starts with the site's yaw. The camera turn has to earn its place through outcomes, and it is capped at 10° until the wrist view is learned.

## Evidence

The real reset placed the box at the start twice (189 and 201 mA holding). After the change, the ledger recorded taught start 0/1, measured 1/1, gripper 46.6 0/1, 48.6 1/1. Tests: `test_omx_cell_choices.py`, `test_taught_and_measured_start_references_compete_and_the_one_that_held_is_used`, `test_jaws_that_stop_short_at_their_end_count_as_arrived`, `test_a_grip_below_the_taught_closed_value_is_held_at_closed`, `test_the_grasp_yaw_keeps_the_site_yaw_until_the_camera_turn_has_earned_it_and_is_capped_before_the_wrist_learns`. Record: `docs/validation/omx-arm-s-real-cell-pipeline-2026-10-25/`.

## Next time

Before reusing a value, ask which plan and which device it came from. If those differ, offer it as one candidate and let real outcomes decide. Do not let any source win by default, measured values included.
