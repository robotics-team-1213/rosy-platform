---
surface: core
kind: additive
slug: docking-dock-reframe
date: 2026-11-28
title: Dock map-tag reframe
history: POST /docking/docks/{id}/reframe re-tags a dock after a same-frame map swap
---
Operators can use `POST /api/v1/docking/docks/{dock_id}/reframe` to move a dock's map identity tags (`map_id`, `metadata.map_epoch`, `commissioned_grid_id` and generation) to the current native frame after a same-frame map swap. The pose does not change, so only a caller that has verified the pose in that frame (Fleet, through its approved site binding) should use it. Auth: operator.

Body: `robot_id`, `map_id`, `map_grid_id`, `map_generation` (the frame now), `expected_map_id` and `expected_grid_id` (the dock's stored `map_id` and `commissioned_grid_id`, null if none), `binding_id` (must equal the dock's `metadata.binding_id` when it has one) and `new_binding_id` (stored on the dock).

Errors: `404 NOT_FOUND` for an unknown dock. `409 MAP_FRAME_CHANGED` when the robot, grid or generation differs from the body, the dock database frame differs from `map_id`, or the dock's tags or binding differ from the expected ones. `409 STATIONARY_REQUIRED` when the robot is not localized, idle and standing still, or a native owner holds a run. The commission gates apply.
