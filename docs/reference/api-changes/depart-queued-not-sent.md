---
surface: fleet
kind: additive
slug: depart-queued-not-sent
date: 2026-11-21
title: Auto departure: a queued exit goal is not SENT
---
- `GET /api/fleet/pipeline/unload-release`: `departure` may now stay `state: "SENDING"` with `reason: "GOAL_QUEUED_NOT_ACCEPTED"` and `queue_reason` (the console queue reason, e.g. `LOCALIZATION_UNTRUSTED`) when the exit goal was only queued by Fleet. The queued goal is withdrawn in the same tick; the next tick checks every release condition again. `queued_since` holds the first queue time; if no goal is accepted within 120 s of it (`DEPART_QUEUE_WAIT_S`, same as D-1060 `MAX_QUEUE_AGE_S`), `departure` becomes `state: "HELD"`, `reason: "DEPART_WAIT_EXPIRED"` and an operator re-arms. An accepted goal clears `queued_since`. `SENT` now means the robot accepted the goal (before, a queued goal was also recorded as `SENT`).
- Pipeline auto events: `auto_depart` may carry `result: "WAITING"` (once per wait) with the queue reason in `why`, and `result: "HELD"`, `why: "DEPART_WAIT_EXPIRED"` once when the wait expires.
