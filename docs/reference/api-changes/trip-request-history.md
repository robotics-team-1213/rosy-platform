---
surface: fleet
kind: additive
slug: trip-request-history
date: 2026-11-26
title: Operator trip request history
---
The authenticated Fleet read endpoint `GET /api/fleet/trip-requests` returns the 50 latest planning and operator start receipts. Each entry in `requests` includes `at` (Unix seconds), `robot_id`, `to`, `plan_id`, `stage`, `code` and `detail`. Stages are `preview`, `plan_refused`, `start_accepted` and `start_refused`. Start receipts record the Fleet admission result. CORE navigation state provides device execution evidence. Historical plan records remain visible after upgrade and new operator start requests add their own receipts.
