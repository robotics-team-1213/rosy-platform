---
surface: fleet
kind: additive
slug: depart-queued-not-sent
date: 2026-11-21
title: Auto departure: a queued exit goal is not SENT
---
- `GET /api/fleet/pipeline/unload-release`: `departure` may now stay `state: "SENDING"` with `reason: "GOAL_QUEUED_NOT_ACCEPTED"` and `queue_reason` (the console queue reason, e.g. `LOCALIZATION_UNTRUSTED`) when the exit goal was only queued by Fleet. The queued goal is withdrawn in the same tick; the next tick checks every release condition again. `SENT` now means the robot accepted the goal (before, a queued goal was also recorded as `SENT`).
- Pipeline auto events: `auto_depart` may carry `result: "WAITING"` (once per wait) with the queue reason in `why`.
