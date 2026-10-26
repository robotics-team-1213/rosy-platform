---
title: An OMX site map extrapolated 4 cm past its points put the belt at the wall, and a TCP-only keep-out let the gripper hit it
date: 2026-10-27
category: runtime-errors
module: deploy/robot/omx (grasp_planner.py keep_out, cell_pipeline.py coarse_map, chunk_runner.py transit)
problem_type: runtime_error
component: deployment
symptoms:
  - "ValueError: wrist_flex: following error >5 motor degrees at the end of lift_place over the belt, two laps running, commands 3334 and 3352"
  - "wrist PWM climbing 71 -> 165 (P 800) and 93 -> 243 of 300 (P 1200) while its error kept growing; shoulder and elbow light"
  - "the person at the switch saw the wrist and gripper touch the white wall behind the belt"
root_cause: extrapolated_calibration_and_point_keep_out
resolution_type: code_fix
severity: high
tags: [omx, arm-s, calibration, coarse-map, keep-out, wall, transit, guard]
applies_when: "an OMX cell target (pick or place) is computed through a camera map, or a keep-out line guards a wall, rail or neighbour"
---

# An extrapolated map put the belt at the wall

## Problem

Arm S, new layout (2026-10-26/27). The jaw-marking coarse map was fitted from 5 points around the old Pinky spot (x 0.07, y 0.11). The belt place (0.150, -0.053) was read off the top camera through that map, 4-16 cm outside its points. A keep-out at x 0.17 checked only the TCP. The dry lap reached the belt, released, and on `lift_place` the wrist flexed 15° upward. That swung the wrist and gripper housing into the wall. The guard turned torque off with the gripper against the wall, twice.

## How it was told apart from a gain or torque problem

- The wrist had trailed on the belt lift before, and P 400 → 800 had fixed that. This time P 1200 did not help.
- Under contact, PWM rises **while** the error grows, and stops at the same commanded position each lap. A low gain shows a steady error at low PWM. A torque limit shows PWM pinned at the cap. Look at `motor-health-*.jsonl` before raising a gain.
- The person at the switch confirmed it ("벽에 닿음").

## Cause

1. **The map was used outside its points.** The belt map fitted afterwards from jaw points over the belt (x 0.09-0.11, y -0.023 to -0.083; leave-one-out mean 2.6 mm, max 4.9 mm) puts the wall foot at x 0.156 and the belt centre at x 0.122. The extrapolated map had both about 3 cm too far out. So the "belt centre" target was at the wall.
2. **keep_out checked a point, not the body.** The TCP stayed inside 0.17. The wrist point and the gripper housing behind it did not.
3. **The stock transit swept toward the wall.** Turning from the Pinky side (y +) to the belt (y -) passes through +x. The transit pose (shoulder -27°, elbow 18°) put the gripper body at x ≈ 0.17.

## Fix

- `grasp_planner.Planner.body_x`: keep_out now checks the TCP and the wrist point (back along the approach axis), plus `BODY_MARGIN_M` 0.035, on every chunk and on the travel between them. The margin is an estimate, marked `shortcut:` in the code. Measure the housing and replace it.
- Calibrate every working site with the arm before using its coordinates. Use the same jaw-marking map (`coarse_map` at that site, points that are reachable and inside the keep-out). Never take a target from a map more than about a point spacing outside its points.
- Planning showed the stock transit at 0.170 with the body counted. Shoulder -40°, elbow 25° passes. The library carries `transit`, so `chunk_runner` takes the same path the planner checked.
- `s_cmd.py` (cell prep helper, Fleet PC): a stale `live.json` (> 3 s) now reports "chunk_runner stopped" instead of waiting out the 300 s command timeout. This helper is not in the repo yet.

## Evidence

- Re-planning the old place (0.150, -0.053) is refused: `above_place: the wrist or gripper reaches x 0.185 m past keep_out x_max 0.17 m`.
- New place (0.112, -0.050), keep_out 0.15, transit -40/25: the plan passes.
- Remote tests: `test_omx_grasp_planner.py` and `test_omx_cell_pipeline.py`, 25 passed (cdad00dcf4).
- The real dry lap on the new place is the next run. This note will be updated with its result.

## Recovery

After the contact, a remote session start plus `park` from the torque-off pose against the wall settled with peak lag 1.86 (shoulder and elbow PWM caps 600). Ask the person at the switch first. A contact pose can be leaning on the obstacle.

## Next time

- A new or moved layout: map each site (pick, place, wall line) with the arm first. Read the wall line from the site map, not from the coarse one.
- A guard stop where PWM rises with the error: suspect contact, check the camera frame and ask the person at the switch, before tuning gains.
- Related: [omx-contact-on-descent-becomes-guard-torque-off-2026-10-25.md](omx-contact-on-descent-becomes-guard-torque-off-2026-10-25.md). Its descent contact became a torque-off too, with the arm extended.
