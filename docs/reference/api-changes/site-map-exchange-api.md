---
surface: core
kind: additive
slug: site-map-exchange-api
date: 2026-11-23
title: CORE site-map exchange endpoints and float32 grid_id rounding parity
history: Additive: GET/POST /api/v1/map/site, host site_map.{status,stage,activate}, float32 grid_id rounding parity
---
- `GET /api/v1/map/site` (viewer) and `POST /api/v1/map/site` (LOCALIZE_ASSIST): stage and safely activate a yaw=0 P5 site-aligned master map via Host Agent `site_map.{status,stage,activate}` after proving zero velocity >= 2.0 s and no active navigation/line-follow/docking/swarm goal.
- `occupancy_map_id` / `occupancy_grid_id` round float32 `resolution` to 6 decimals and normalize `-0.0 -> 0.0` so CORE matches sealed Nav2 `manifest.json` `grid_id`.
