---
surface: core
kind: additive
slug: nav2-bound-route
date: 2026-11-26
title: Nav2 route with expected map grid
---
`GET /api/v1/system/capabilities` advertises `navigation.bound_route: true`. `POST /api/v1/navigation/bound-route` accepts the fields of `/navigation/route` and requires `expected_map_grid_id`. CORE checks the grid under its map-grid gate before taking the navigation owner. A mismatch returns 409 `NAVIGATION_MAP_GRID_CHANGED`. A successful reply includes `map_grid_id`. Existing `/navigation/route` clients keep their request and response format.
