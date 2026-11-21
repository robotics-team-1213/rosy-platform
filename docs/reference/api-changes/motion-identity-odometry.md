---
surface: fleet
kind: additive
slug: motion-identity-odometry
date: 2026-11-21
title: Motion identity reads wheel odometry
history: Motion identity (identity.motion_match) compares the camera track with the robot odom_pose displacement instead of a LOCALIZED map pose; an odometry epoch change or stale odometry starts over. No wire change.
---

