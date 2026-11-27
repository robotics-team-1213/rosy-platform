---
surface: fleet
kind: additive
slug: fleet-master-map-exchange
date: 2026-11-23
title: Fleet bidirectional master-map exchange endpoints
history: Additive: GET /robots/{id}/map/bundle, PUT/GET /site-map/master-grid, POST /robots/{id}/master-map/push
---
- `GET /api/fleet/robots/{robot_id}/map/bundle` (viewer): convert robot `GET /api/v1/map` snapshot into a verified trinary P5 PGM/YAML bundle + canonical `grid_id`.
- `PUT/GET /api/fleet/site-map/master-grid` (named operator PUT / viewer GET): store and fetch the SQLite-persisted yaw=0 master occupancy grid bound to the active site map version.
- `POST /api/fleet/robots/{robot_id}/master-map/push` (named operator): push the stored master grid to CORE `POST /api/v1/map/site` with optional activation.
