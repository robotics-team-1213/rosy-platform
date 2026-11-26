---
surface: fleet
kind: additive
slug: cell-plan-persisted-refusal
date: 2026-11-26
title: Task-specific cell plan refusal codes
---
A physically aborted step reports its own persisted and sanitized error as tasks[].last_refusal.code with op=complete, and the plan exposes the code in hold_reason. The proposal retains the requested slot. A service proposal and a dry run do not establish calibration. SITE_NOT_CALIBRATED and STAND_NOT_CALIBRATED are emitted only from the cell's actual local calibration check. The service also preserves typed structural, configuration, interlock and hardware refusals. Unrecognized hardware diagnostic text yields MEASURED_PLACEMENT_MISSING.
