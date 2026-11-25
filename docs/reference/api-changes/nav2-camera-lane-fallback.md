---
surface: fleet
kind: additive
slug: nav2-camera-lane-fallback
date: 2026-11-26
title: Camera continuation after a failed Nav2 route
---

For a finite named Nav2 trip with `approved_slam_required: true`, an operator may request `camera_lane_fallback: true`. Fleet attempts camera lane following after CORE reports a terminal Nav2 `FAILED` with the approved SLAM binding still current. The unfinished section must be a straight painted final lane with reviewed camera evidence on the active survey, ending at a pinned ordinary stop outside signal and crosswalk zones.

The change requires a current CORE trip lease, always-enforced line authority, a fresh camera frame, and two fresh zero-velocity samples after acknowledged cancellation. Fleet checks lease expiry again immediately before asking CORE to start the camera controller. It stops both controllers if the mode change is uncertain and reports arrival after turning the camera controller off and rechecking stationary pose. Precision stops and failures of localization itself stay under their existing recovery contracts.
