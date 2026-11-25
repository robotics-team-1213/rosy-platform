---
surface: fleet
kind: additive
slug: trip-junction-turn-refusal-reason
date: 2026-11-26
title: Lane trip junction turn refusal reason
history: Keep the CORE junction readiness reason in lane trip refusals
---
When Fleet refuses a lane trip with `TRIP_MODE_UNSUPPORTED` and `detail.reason: JUNCTION_TURN_UNSUPPORTED`, `detail.junction_turn_reason` carries the optional current CORE reason from `base_velocity`. With older CORE it is omitted. Admission and Nav2 routing continue to use their existing checks.
