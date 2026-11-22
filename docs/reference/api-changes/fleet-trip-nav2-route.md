---
surface: fleet
kind: additive
slug: fleet-trip-nav2-route
date: 2026-11-22
title: Fleet trip Nav2 road-following drive_mode
history: Additive: optional drive_mode nav2 on POST /api/fleet/robots/{robot_id}/trip via CORE D-1009 /api/v1/navigation/route
---
Adds optional `drive_mode: "nav2"` on `POST /api/fleet/robots/{robot_id}/trip` (single, lap, or `repeat: true`). Requires `"free"` in the robot's `base_velocity.drive_modes`, plans across site-map edges without camera line-following checks, and executes each lap's road centerline as ordered `pass`/`stop` points via CORE `POST /api/v1/navigation/route` (D-1009) re-anchored into the robot's `map` frame (D-1003) on each rollover.
