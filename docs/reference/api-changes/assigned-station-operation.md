---
surface: fleet
kind: additive
slug: assigned-station-operation
date: 2026-11-26
title: Assigned station release and timeout hold
---

Submit the `station_stop` action with the configured `place_id` and `role` for an external load or wait stop. The task exposes `station_operation` with the assigned place, role, retained trip ID, state and deadline. A named operator can post `robot_id`, `trip_id`, `place_id` and `role` to `/api/fleet/pipeline/pinky-tasks/{task_id}/station-release`. Repeating the same release returns its stored receipt. Timeouts retain the hold. Cell S unload release checks the matching batch, final cell task, empty bed and parked arm.
