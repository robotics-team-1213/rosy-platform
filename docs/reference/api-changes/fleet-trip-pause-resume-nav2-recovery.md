---
surface: fleet
kind: additive
slug: fleet-trip-pause-resume-nav2-recovery
date: 2026-11-23
title: Fleet trip pause/resume controls and autonomous Nav2 failure recovery
history: Additive: POST /api/fleet/trips/{trip_id}/pause and /resume, Nav2 traffic holds, and autonomous Nav2 failure reroute/retry/hold recovery
---
Adds `POST /api/fleet/trips/{trip_id}/pause` (`operator`) and `POST /api/fleet/trips/{trip_id}/resume` (`named operator`, optional `blocked_edges`) to hold an open trip cleanly under its lease and resume or guide it around blocked edges. Also closes Nav2 (`drive_mode: "nav2"`) pipeline links so `step_nav2_route` honors Fleet traffic holds (`refused_at_m`), asks Fleet for alternate detours or bounded retry/hold recovery when `autonomous_robots` encounter Nav2 `FAILED` / transient `ROUTE_CONFLICT`/`YIELDING`, and compares multi-robot SLAM claims in the shared active site frame.
