---
title: "Isaac OMX fixed joint must own the fixed-base articulation root"
date: 2026-10-29
category: runtime-errors
module: learning/envs/isaac
problem_type: runtime_error
component: simulation
severity: high
root_cause: articulation_root_on_rigid_body_selects_floating_base_topology
resolution_type: code_fix
tags: [isaac, sdk62, omx, articulation, fixed-base, gravity-compensation]
applies_when: "Importing the pinned OMX-F model with SDK 6.2 for a fixed workbench"
---

# Import success does not establish a fixed robot base

The mapped two-arm task imported seven actuated joints per arm and accepted
position commands, but the shoulder drifted by approximately 0.48 rad in one
second. Changing parking, gains and torque caps did not solve the drift.

SDK 6.2's converter applied `PhysicsArticulationRootAPI` on `link0`. Its
`world_fixed` joint was outside that body's hierarchy and initially referred to
a nonphysical model Xform. A rigid-body root explicitly selects floating-base
topology. Adding an empty world endpoint alone did not change that selection.

The native metatype reported `fixed_base=False`. Its gravity force vector began
with base forces, including 5.482 N in Z. The legacy joint-gravity accessor selected
the first seven generalized components; these were not seven joint compensation
torques for a floating base. Feeding that vector to the arm made the diagnosis
harder. Check topology before using inverse dynamics or changing gains.

## Correction and evidence

For this fixed workbench, author the world endpoint explicitly, move
`PhysicsArticulationRootAPI` from `link0` to `world_fixed`, and apply the
articulation settings on that joint. Construct the robot through its model root
and require the native metatype's `fixed_base` readback before moving.

- Source `66db7cba87efd68bcb63fc498754663c5167225f`, run
  `5595c6b686035cfab90716d48118da1b`: the endpoint change alone still reported
  `fixed_base=False`; the new guard stopped the task.
- Source `30110634c2566a1566cf5a5171c978d1bd2cf08e`, run
  `3a0755127fc85e619e85ea7ebc3aa2aa`: both native metatypes reported true.
  Initial joint errors were below 0.0001 rad, and the first 90 mm bar passed
  bilateral free lift, release, lower support and persistent settling. Later
  layers failed to grasp; this evidence does not establish full stacking.

Both runs confirmed owned process/GPU cleanup. The successful first-layer raw
report and actual images are in the workspace artifact snapshot documented in
[the execution record](../../validation/omx-map-stacking-2026-10-29/result.md).

The [NVIDIA articulation rules](https://docs.omniverse.nvidia.com/kit/docs/omni_physics/108.0/dev_guide/rigid_bodies_articulations/articulations.html)
distinguish fixed-joint roots from floating rigid-body roots. Preserve the
intended base mode; this correction must not anchor mobile robots.

## Related import checks and recovery

The same investigation found an extra default 1 kg body for the visual-only TCP
and an active imported `NewtonMimicAPI` competing with measured-follower control.
The mapped task imports a derived physical tree without the TCP marker, restores
its nonphysical frame, and disables the imported Newton mimic. Those corrections
are separate from the root-topology comparison above. The original vendor model
and hardware configuration remain unchanged.

When a new importer or model is used, check native fixed-base state, body masses,
drive units, mimic constraints and measured motion. Keep failed run receipts.
Stop/fetch through the owned runner and confirm cleanup before retrying. Revert
only the task branch's scene overrides if necessary; do not replace the installed
SDK or relax contact acceptance to recover a passing result.

The final continuation, source `dc2f2f05c5`, run
`74098c1235c4589cbdc9104852b6f186`, retained this fixed-root correction and passed
three nominal 90×30×90 mm stacking trials with native contact evidence and owned
cleanup. Additional collider and 240 Hz contact-integration changes were needed;
the root correction alone did not establish the complete task. See the execution
record for the failed intermediate runs and separate PPO outcome.
