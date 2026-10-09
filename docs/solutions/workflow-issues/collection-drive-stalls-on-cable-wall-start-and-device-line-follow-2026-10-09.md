---
title: A collection drive stalls when the robot starts with a cable attached or against a wall, and the device line follower cannot cover the track
date: 2026-10-09
category: workflow-issues
module: PC field scripts and CORE CAMERA_LINE on Pinky robots during D-563 ceiling-BEV label collection (rosy-pinky-8kcn, 260919 track)
problem_type: workflow_issue
component: development_workflow
severity: medium
applies_when:
  - "an agent starts a real-robot drive to collect recordings for map-projected labels"
  - "the robot was just handled on site (cable unplugged, picked up, set down)"
  - "a script waits for LiDAR clearance before moving"
  - "CORE CAMERA_LINE is used to move the robot around the arena"
symptoms:
  - "CAMERA_LINE stopped at once with obstacle_ahead (gap 0.054-0.057 m) while the front camera showed open road"
  - "the nearest LiDAR point stayed at 0.091 m for more than 2 minutes and the script kept waiting for 0.15 m"
  - "guard.py refused forward, rotation and reverse by 1-4 mm (0.032<0.033, 0.091<0.093, 0.036<0.040)"
  - "six CAMERA_LINE runs each ended in 3-6 s with camera_line_not_visible, stuck_back_off, then LOST camera_reselection_required"
  - "an unguarded teleop script was blocked by the Claude Code auto-mode classifier as a security weakening"
tags: [field-driving, data-collection, lidar, clearance, charging-cable, camera-line, d-563, d-574, pinky]
---

# A collection drive stalls when the robot starts with a cable attached or against a wall, and the device line follower cannot cover the track

## Problem

On 2026-10-09 the D-563 ceiling-BEV collection drive on 8kcn produced about 15 minutes of recordings in which the robot barely moved. The ceiling recorder and `rosy_rec.sh` both ran; only the driving failed. Decision record: D-574.

## Root cause

Four independent blockers, met one after another:

1. **A charging cable was plugged into the robot.** It lay just in front of the body, so the LiDAR reported a 5 cm obstacle. Because the cable is attached to the robot, it travels with the robot and never clears.
2. **The robot was set down about 5 cm from the arena wall** after the cable was unplugged. The constant 0.091 m reading was that wall, not a person's hand.
3. **The shared RobotBody guard refuses by millimetres.** It works as designed, but with the robot against the wall, every move except a reverse arc was off by 1–4 mm.
4. **The device CAMERA_LINE follows one white line** (D-378 E1). Facing a wall, or with no line in view, it stops (`camera_line_not_visible`), backs off (`stuck_back_off`) and gives up (`LOST`). It cannot drive the whole arena on its own.

The agent also lost time to two mistakes of its own: it waited on a reading that never changed, and it tried to remove the guard. The auto-mode classifier blocked the second attempt. That is the correct boundary: only a user permission rule may relax a guard.

## Solution

- Unplug the cable (done on site).
- Back out from the wall with a **guarded reverse arc**, which the guard allows because the rear was clear (1.25 m). `arc.py 8kcn -0.03 0.35 3` gave forward 0.06 m and rotation clearance 0.119 m, after which turns and forward moves passed:

```python
# X:\DevTemp\v13-drive\arc.py — every 10 Hz command goes through guard.safe_teleop
safe_teleop(robot, linear=-0.03, angular=0.35)   # reverse while swinging the nose away from the wall
```

- Collection drives are driven by a person with Pilot; the agent records and watches the coverage on the ceiling BEV (D-574 1).

## Prevention

Before any agent-driven drive, check four things and fix whichever fails before you drive:

1. No cable is attached to the robot (check the ceiling image).
2. The minimum LiDAR range in every direction is at least the rotation clearance + 5 cm.
3. The robot is near the road centre and faces along the road.
4. CD auto-update is held.

A distance that does not change for more than a minute is a fixed object. Look at the ceiling and front frames and move the robot out; do not wait. Never weaken a guard unless the user has added an explicit permission rule.
