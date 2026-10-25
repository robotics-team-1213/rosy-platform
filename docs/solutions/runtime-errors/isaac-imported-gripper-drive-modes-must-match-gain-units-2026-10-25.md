---
title: "Isaac gripper gain and effort units require explicit imported drive modes"
date: 2026-10-25
module: learning/envs/isaac
problem_type: runtime_error
component: testing_framework
severity: medium
symptoms:
  - "OMX model import and host tests passed, but cargo remained on the source support during lift"
  - "After close, measured finger angles were +0.481 and +0.1086 rad instead of a symmetric hold"
root_cause: config_error
resolution_type: code_fix
tags: [isaac-sim, omx, physx, gripper, drive-type, contact-grasp]
applies_when: "Configuring imported articulation drives for contact tasks using gains and Nm effort caps"
---

# Match imported joint drive modes to the controller's units

## Problem

The stationary Pinky-support/conveyor task imported the pinned OMX-F model and followed the commanded arm trajectory, but failed to lift cargo. Increasing arm gains and closing preload improved tracking without producing a bilateral hold. The diagnostic run `50868081e8e45752b3bf23b72f3e6d1f` recorded a large difference between the two measured finger angles; the cargo was pushed aside and remained supported.

## Root cause

The controller assigned physical spring/damper gains without declaring the imported angular drive type. In the succeeding run, reading the composed USD before configuration showed joints1–5 and `gripper_joint_1` using `acceleration`, while `gripper_joint_2` used `force`. The two fingers therefore did not share the intended actuator semantics.

Acceleration drives normalize by inertia; force drives apply effort directly. This distinction is documented in the [Isaac Sim 5.1 URDF importer](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/importer_exporter/ext_isaacsim_asset_importer_urdf.html). Do not infer drive type from a URDF joint name, a mimic declaration, or successful model import. The recorded mixed result applies to this SDK/importer/model combination, not every imported robot.

## Solution

`conveyor_task.py` explicitly authors angular `DriveAPI` type `force`, verifies the composed value, and records both imported and configured modes. The fixed fixture declares the type alongside gains and effort caps. The isolated task changes no physical robot configuration or vendor asset.

The successful run `36041b241ee25366986bb3a6262ba0be` used source `7d0cfcd6e94fd0181e324319e12c274f3e2f3890`. Relative to the preceding diagnostic, the force-mode change preserved the gains, effort caps, targets and contact acceptance criteria. Both contact lifts, unsupported transport and released settling passed; all five actual images and cleanup were checked independently. Full evidence and frozen hashes are in the [validation record](../../validation/isaac-pinky-conveyor-roundtrip-2026-10-25/result.md). This is one bounded smoke, not an estimate of general grasp reliability. The source is committed; main integration is pending at writing time.

## Prevention and recovery

Read composed drive modes and measured finger positions before tuning contact forces. Pair the selected mode with explicit gain/effort units, and require measured bilateral contact plus unassisted release/settle; controller acknowledgement and import tests cannot establish a physical grasp. Keep failures and retry under a new source/run binding after a concrete correction.

If a task fails again, use the owned runner's stop/status/fetch path and preserve its receipt. Confirm owned process/GPU release before a new run. Reinspect modes after an SDK/importer/model change rather than applying this fixture's gains to a different arm or to hardware.
