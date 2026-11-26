---
surface: cell
kind: additive
slug: site-not-measured-refusal
date: 2026-11-26
title: Registered cell slots refused until measured
history: Additive: SITE_NOT_MEASURED hardware refusal for registered slots
---
A designated slot registered by cell_site_register is refused with SITE_NOT_MEASURED (v1.next) until XY and Z measurements exist for its current place, yaw, surface height and tier step; layers 1 and 2 also need a measured tier step. The code is one of the hardware refusals the cell worker reports and Fleet publishes as tasks[].last_refusal.code and the plan hold_reason. Entries without a status key (pallet, belt, temp_plate_*) behave as before.
