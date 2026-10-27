---
title: MuJoCo collides the OMX finger meshes as convex hulls that never close on a block; grip through calibrated pad capsules
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
- Isaac shows the same failure plus an unmimicked `gripper_joint_2` and soft arm drives (same record); see also
  [isaac-imported-gripper-drive-modes-must-match-gain-units](../runtime-errors/isaac-imported-gripper-drive-modes-must-match-gain-units-2026-10-25.md).
