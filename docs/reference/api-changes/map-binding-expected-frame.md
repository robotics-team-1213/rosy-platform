---
surface: fleet
kind: additive
slug: map-binding-expected-frame
date: 2026-11-26
title: Map binding approval checks the measured frames
---
POST /api/fleet/robots/{robot_id}/map-binding accepts optional expected_frame with site_map_id, site_map_version, and robot_grid_id. Fleet rejects a changed active site revision (409 MAP_BINDING_SITE_CHANGED) or robot grid (409 MAP_BINDING_GRID_CHANGED) before writing a binding. Omitting expected_frame keeps the existing approval behavior.
