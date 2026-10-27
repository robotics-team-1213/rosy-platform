---
title: Simulated OMX fingers (MuJoCo hulls, Isaac imported collision and mimic) never close on a block; grip through calibrated pad capsules
date: 2026-10-27
category: logic-errors
module: tools/sim/omx_mujoco_backend.py (D-877); tools/sim/omx_grasp_probe.py
problem_type: logic_error
component: simulation
symptoms:
  - "omx_grasp_probe on MuJoCo: every arm goal SUCCEEDED, the gripper reached its 0.380 rad close target, the block never moved (xy change ~1e-16 m)"
  - "an offline check at TCP yaw 0 lifted the block, the live run at the job's pick yaw 1.571 did not"
root_cause: wrong_api
resolution_type: code_fix
severity: high
framework_version: MuJoCo 3.3.7, vendor open_manipulator 0a4af6a9 OMX-F meshes
tags: [mujoco, convex-hull, gripper, grasp, friction-cone, isaac, d-877, d-866]
applies_when:
  - "a simulator backend imports the OMX-F (or any hooked-finger) URDF meshes as collision"
  - "a grasp in MuJoCo or Isaac closes to its target without stopping on the item"
---

## Symptom

The grasp probe ran cleanly (goals SUCCEEDED, joint states and object poses live) but the block stayed put. The
gripper closing all the way to the width-matched target (0.380 rad) instead of stopping near contact (0.407 rad for
30 mm) was the tell: the fingers never touched the block.

## Cause

1. MuJoCo collides every mesh as its **convex hull**. Each OMX-F finger hull spans pivot to tip, and the two hulls
   overlap at every opening (geom distance −1.8 mm from 1.0 to 0.25 rad). Nothing like the fingertip pads exists
   in collision, so the calibrated jaw gap (`cell_profile.yaml` `gripper.jaw`) means nothing.
2. The default **pyramidal friction cone** let a squeeze that should hold (~4 N on a 0.2 N block) slip.
3. A misleading offline check: at TCP yaw 0 the hulls squeezed the block's 40 mm sides and lifted it, which looked
   like a fix. The block is turned 90° in the world file; the job's pick yaw (1.571) squeezes the 30 mm sides,
   where the hulls never close. Always test at the yaw the teacher uses (`compile_job(...)` pick step).

## Fix

- Finger meshes become visual only (`contype = conaffinity = 0`). Each finger collides through one **capsule
  across the finger** (radius 1.5 mm) whose inner surface sits on the calibrated contact point; link7 mirrors
  link6's y. A box pad was 4 mm too narrow: its corner turns with the finger. With the capsule, the MuJoCo jaw gap
  matches the calibration within 0.4 mm from 12 to 90 mm.
- `option.cone = elliptic`, `impratio = 10`; stiff `solref` 0.002 on pads and movable objects.

## Verification

`tools/sim/run_omx_backend_conformance.sh mujoco 240x320 5 grasp` on the model PC: 5/5. The block rose 51 mm on a
50 mm lift, the gripper held at 0.406 rad, and set back it rested within 1 mm. The conformance check still passes
(real-time factor 1.003). Record: `docs/validation/omx-sim-grasp-2026-10-27/`.

## Next time

- Measure the collision jaw gap against `profile.jaw_gap_m(q)` (`mujoco.mj_geomDistance` between the finger geoms)
  before tuning friction or gains.
- The pad definition lives in `tools/sim/omx_cell_world.py` (`PAD_RADIUS`, `PAD_HALF_LENGTH`, `jaw_contact_point()`); both
  backends use it, so a recalibrated contact point moves both.

## Isaac (same day, resolved)

Isaac 5.1 failed the same probe for three stacked reasons; each hid the next:
1. Imported drives: arm and `gripper_joint_1` on acceleration drives, `gripper_joint_2` undriven. Force drives with
   the 2026-10-25 cargo fixture gains fixed arm tracking (see
   [isaac-imported-gripper-drive-modes-must-match-gain-units](../runtime-errors/isaac-imported-gripper-drive-modes-must-match-gain-units-2026-10-25.md)).
2. The imported `PhysxMimicJointAPI` referenced the lead joint's rotX (its axis is Z), damping ratio 0.005. Correcting
   both still left the fingers uncoupled. Removing the mimic and setting `gripper_joint_2`'s target each frame to the
   mirror of the measured `gripper_joint_1` made them symmetric (0.380/-0.380).
3. The imported finger collision then closed past the 30 mm block. The same calibrated capsule pads fixed it: 5/5.
4. "Held" is not enough: Isaac held at 0.385 rad, below the teacher's `contact_held` floor (0.3935), because the pads
   sank ~1 mm per side into the block (more solver iterations did not help). A 1 mm pad rest offset and a stiff
   follower finger (the real gripper is one motor) bring the held angle to 0.405-0.408, matching Gazebo's 0.407.
   Compare the held angle with the calibrated one, not only lifted/not lifted.

Read back the composed joint attributes (drive type, mimic axis, damping) and the measured finger pair before tuning
anything; a probe that only reports "not held" cannot tell these apart. Record:
`docs/validation/omx-sim-grasp-2026-10-27b/`.
