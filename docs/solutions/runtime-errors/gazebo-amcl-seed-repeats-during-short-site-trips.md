---
title: Gazebo initial-pose seeding can overlap a short Pinky trip
category: runtime-errors
problem_type: runtime_error
date: 2026-11-23
tags: [gazebo, pinky, nav2, amcl, site-map]
---

# Gazebo initial-pose seeding can overlap a short Pinky trip

The 261026 C2→P2 diagnostic returned `ARRIVED` in three runs. Gazebo model-pose odometry placed the final robot 169–191 mm away from P2. The 150 mm diagnostic limit failed. The launcher reported Nav2 active in time to dispatch the goal, while its automatic AMCL seeder was still publishing C2 as the initial pose. The AMCL logs showed 32 initial pose updates in each run. The pose being checked by Nav2 could therefore diverge from the physical model during the drive.

In `tools/sim/world_pinky_smoke.py`, start with `seed_initialpose:=false`. Submit the C2 pose once through CORE after `bt_navigator` becomes active, then wait for CORE's pose to reflect the seed before submitting the navigation goal. Keep Gazebo model-pose odometry as independent arrival evidence. On exact commits `78b19cb7ce` and `6f9243dd15`, the stationary final position was 107 mm and 77 mm from P2 respectively, within the original 150 mm diagnostic limit. The last run observed CORE at C2 before sending the goal.

Reproduce with [the single-Pinky diagnostic](../../../tools/sim/world_pinky_smoke.py) under the remote simulation runner. To diagnose a regression, compare AMCL's `initialPoseReceived` timestamps with the goal dispatch and check the final physical pose independently. The designated pink-guide departure uses the [D-1013 pit-out flow](../../adr/D-1013-charge-bay-pink-line-pit-flow.md).
