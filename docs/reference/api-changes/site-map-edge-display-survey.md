---
surface: fleet
kind: additive
slug: site-map-edge-display-survey
date: 2026-11-26
title: 현장 지도 도로 측량 표시선
history: Additive: rosy.site_map/1 edge display_polyline + display_source (survey), GET /api/fleet/site-map/active 가 측량표에서 덧붙임
---
`GET /api/fleet/site-map/active`: edges may carry `display_polyline` + `display_source` (kind `survey`, `surveyed_at`, `plane`, `anchors`, `stored_until?`, `note?`), a display-only measured line. Fleet adds it on read from its floor-survey table when map id, ends and `from`/`to` match; the stored body and `sha256` are unchanged, and a draft that carries the pair saves it. Routing, snapping and editing keep `polyline`. Consumers: Fleet 관제 지도(`map/map-view.js`), 현장 지도(`sitemap/site-map.js`) and their evidence line. Absent: no survey line is drawn and the evidence line says `측량선 없음`. (v1.next)
