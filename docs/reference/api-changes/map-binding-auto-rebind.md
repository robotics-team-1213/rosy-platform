---
surface: fleet
kind: additive
slug: map-binding-auto-rebind
date: 2026-11-28
title: Map binding auto-rebind after a same-raster map swap
history: Additive (D-1022): GET /api/fleet/robots/{robot_id}/map-binding gains auto_rebind
---
Additive (D-1022): `GET /api/fleet/robots/{robot_id}/map-binding` gains `auto_rebind` (`{code, detail, at}` or null) — the last Fleet auto-rebind attempt. When a robot's map file is swapped but its raster frame is not (same origin, resolution, width, height within 1e-6; at most max(12, 2 % of the bound grid's occupied cells) cells of another class, and the bound grid is not within that budget of its own 180-degree turn or mirror), the standing IDLE robot is re-bound by Fleet as `fleet:auto-rebind` (old transform, ceiling-camera fix at most 2 s old as hold-out, site map revision unchanged); `code` is `APPROVED` or the refusal reason: `GRID_SIGNATURE_MISSING`·`GRID_FRAME_CHANGED`·`GRID_CELLS_CHANGED`·`GRID_SYMMETRIC`·`NOT_STANDING`·`NO_CAMERA_HOLDOUT` (no ceiling-camera fix, or older than 2 s)·`HOLDOUT` (the store's unchanged 0.05 m hold-out)·`SITE_REVISION_CHANGED`·`STATE_CHANGED`·`ROBOT_UNREADABLE`; the grid signature is stored with the binding row but not exposed by any route; audit action `map_binding_auto_rebind`. Site config `fleet.trip.map_auto_rebind` (default true) turns it off. The version number is assigned at landing.
