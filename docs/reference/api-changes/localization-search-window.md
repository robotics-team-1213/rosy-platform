---
surface: core
kind: additive
slug: localization-search-window
date: 2026-11-26
title: Bounded localization candidate search window
---
CORE advertises `localization.search_window: true` while its native candidate
node can receive window requests. `POST /api/v1/localization/search-window`
requires `LOCALIZE_ASSIST` and takes `expected_map_grid_id` and `center` with
finite native-grid base pose coordinates `x`, `y`, `yaw` (wrapped radians).
A signed-in client's current, independently approved grid alignment is its
responsibility. A `202 {"accepted":true}` acknowledges CORE accepted the relay. A matching grid and unresolved localization are required.
Lease checks still apply and busy or mismatched-grid requests return 409.

The robot runs its existing global search first and keeps its results. Only an
empty global result allows a bounded ±12 cm/±14° search over the supplied
window. A candidate requires agreement on two distinct recent native scans.
The server enforces local delivery expiry and cooldown. Existing candidate
readback and independent decision and post-injection verification still
apply. A window never triggers automatic pose injection or motion.
