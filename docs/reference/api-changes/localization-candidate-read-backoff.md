---
surface: fleet
kind: additive
slug: localization-candidate-read-backoff
date: 2026-11-26
title: Localization candidate reads retain CORE backoff
---
GET /api/fleet/robots/{robot_id}/localization relays CORE candidate channel RATE_LIMITED as HTTP 429, including Retry-After and detail.retry_after_s when provided. A successful response with candidates null still means that no candidate report was available.
