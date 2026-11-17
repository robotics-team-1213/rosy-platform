---
title: arm_s belt placement below x=134mm rolls 30mm containers over the x=114mm front rail into the x=95mm belt-base trench, and z<55mm trips shoulder_lift following error
date: 2026-11-13
category: runtime-errors
module: deploy/robot/omx (cell_realignment_pipeline.py, cell_spec_recovery_fsm.py)
problem_type: runtime_error
component: hardware_control
symptoms:
  - "Placing a 30mm C3 container on the arm_s belt at x_mm=123.4mm (b_horiz_descend_place) caused the container's front edge (108.4mm) to overhang the 114.0mm front aluminum belt rail by 5.6mm and roll into the x=95.3mm belt-base trench upon jaw release"
  - "Commanding IK belt descent to z_mm=43.0mm pressed the fingertips into the belt surface and tripped Dynamixel Hardware Error 0x08 ('shoulder_lift: following error >5 motor degrees; command=1728, current=1786')"
  - "Adding +90 deg to wrist_roll for orthogonal-axis realignment exceeded the [-92.0, +45.0] vertical corridor when starting near +39u"
root_cause: uncalibrated_belt_front_rail_margin_and_z_floor
resolution_type: code_fix
severity: high
tags: [omx, arm-s, belt-rail, trench, realignment, following-error, wrist-roll]
applies_when: "computing IK belt placement or recovery trajectories on OMX Cell S (arm_s)"
---

# `arm_s` Belt Front-Rail Safe Clamp (`x >= 134mm`, `z >= 55mm`), Trench Extraction (`S13`), and Corridor-Safe `wrist_roll` Wrap

## Symptoms

1. **Belt-to-base trench roll-off on jaw release.** Forward kinematics on `chunks-arm-s-master-shuttle.json` (`b_horiz_descend_place`) placed the TCP at `x = 123.4mm, y = -40.1mm, z = 75.6mm`. Because the front aluminum rail of the conveyor belt sits at `x = 114.0mm` and a C3 container is `30mm` wide (`15mm` half-width), its front wall landed at `123.4 - 15.0 = 108.4mm` (`5.6mm` overhanging the rail), causing it to tip off the belt into the narrow `x = 95.3mm` trench between the belt rail and the OMX base plate (`wx_px >= 535.0` in `arm_s_wrist`).
2. **`shoulder_lift` following error (`> 5°`) during IK belt descent.** Commanding `solve_belt_ik` down to `z_mm = 43.0mm` drove `shoulder_lift` into the belt surface (`command=1728, current=1786`), tripping the hardware following-error guard.
3. **`wrist_roll` vertical corridor violation on `+90°` orthogonal rotation.** Rotating `wrist_roll` by `+90°` from `+39.6u` produced `+129.6u`, violating the `[-92.0, +45.0]` vertical corridor.

## Root Cause

- Belt IK placement did not enforce a minimum inward `x_mm` margin relative to the `114.0mm` front belt rail (`BELT_FRONT_RAIL_X_MM`) plus container half-width (`15.0mm`) and safety buffer (`5.0mm`), nor a minimum `z_mm` floor above the belt surface.
- Visual servoing previously clamped `x_min_mm = 110.0mm`, preventing the arm from reaching into the `x = 95.3mm` belt-base trench when a container rolled off.

## Fix & Verification

1. **Belt Inward Rail-Safe & Z-Floor Clamp (`clamp_belt_safe_place_pose_mm` in `cell_realignment_pipeline.py`).**
   - Enforces `BELT_SAFE_CENTER_X_MIN_MM = 134.0` (`114.0mm` rail + `15.0mm` half-width + `5.0mm` margin, keeping the container front wall at `>= 119.0mm`), `y_mm in [-45.0, -8.0]`, and `BELT_SAFE_PLACE_Z_MIN_MM = 55.0`.
   - Applied automatically in `solve_belt_ik` for all descent/place targets (`z_mm <= 82.0mm`).
2. **Belt-Base Trench Detection & Extraction (`S13_BELT_BASE_TRENCH_OR_RAIL_WEDGE`).**
   - `estimate_wrist_object_pose_2d` flags `in_belt_base_trench = True` when `wx >= 535.0px` (`x_mm < 114.0mm`).
   - Lowered `x_min_mm` to `90.0mm` (`[-11.03, -23.76, 20.48, 53.37, 39.81]` verified on live `arm_s` at `x = 95mm`), extracting via `elbow_first_rail_clear` (`z = 112mm`) to canonical inward belt pose `(134.0, -28.0, 58.0)` and escalating to fallback zones (`pinky_front_floor`, `pinky_tray`) if wedged.
3. **Corridor-Safe `wrist_roll` Wrap (`wrap_wrist_roll_to_corridor`).**
   - Normalizes target `wrist_roll` via `±90°` / `±180°` symmetry into `[-92.0, +45.0]`.
4. **Verification.**
   - Unit tests in `test/test_omx_area_xyz.py` and `test/test_omx_area_xyz_recovery.py` (`21 passed`), plus live `arm_s` hardware verification recorded on Confluence page `28902060`.
