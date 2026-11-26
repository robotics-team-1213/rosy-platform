---
surface: fleet
kind: additive
slug: idempotent-trip-cancel
date: 2026-11-26
title: Repeat cancellation returns the named trip receipt
---
Repeating `POST /api/fleet/trips/{trip_id}/cancel` for a canceled trip returns its current receipt, including after restart. The first cancellation keeps its operator and stop evidence. Repeating the request sends no command to a later trip on the same robot.
