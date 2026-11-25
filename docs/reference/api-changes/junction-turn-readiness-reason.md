---
surface: core
kind: additive
slug: junction-turn-readiness-reason
date: 2026-11-26
title: Junction turn readiness reason
history: Explain the current junction-turn capability refusal
---
The optional base_velocity `junction_turn_reason` field in `GET /api/v1/system/capabilities` explains a false `junction_turn`. It reports `keep_corner_unavailable`, `enforce_unavailable`, `site_floor_unconfigured`, `ir_guard_disabled`, `ir_stale`, `ir_centre`, `ir_not_admissible`, `body_clearance_unconfigured`, or `scan_stale`. If multiple gates fail, it reports the first refusal. Older CORE may omit the field. The capability still changes with live evidence. This field is for diagnosis and grants no motion authority.
