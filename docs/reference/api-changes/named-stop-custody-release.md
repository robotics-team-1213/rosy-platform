---
surface: fleet
kind: additive
slug: named-stop-custody-release
date: 2026-11-21
title: Operator release of a named-stop custody claim
history: POST /api/fleet/robots/{robot_id}/named-stop-custody/release; named_stop_custody row field
---
Additive, fail-closed. A named operator releases the site-wide named-stop custody claim. Body: `reservation_id` (from the robot row `named_stop_custody`), `reason` (3-500 chars), and optional `physical_isolation` (`method`: `power_off` | `hardware_estop_latched` | `removed_from_site`, `robot_physically_isolated: true` (strict boolean), `evidence`: 3-500 chars; legacy `operator_saw_robot_standing_still` is rejected with 422). Fleet stops the robot first (and ends its trip/lease), then verifies fail-closed proof before writing the audit row (`site map events`, action `named_stop_custody_release`) and releasing custody. Without `physical_isolation`, stop cancel must succeed and live CORE readback must prove standstill (`NAMED_STOP_CANCEL_FAILED`, `NAMED_STOP_PROOF_REQUIRED`). With `physical_isolation`, `hardware_estop_latched` requires live CORE `mode=EMERGENCY`, `safety.estop=true`, `line_follow.mode=OFF`, and fresh zero-velocity proof (fails closed if offline/unconfirmed), while `power_off`/`removed_from_site` require unreachability across stop cancel and repeated state probes (`PHYSICAL_ISOLATION_CONTRADICTED`). `503 AUDIT_UNAVAILABLE` releases nothing. `409`: `NAMED_STOP_CLAIM_CHANGED`, `ROBOT_REQUEST_IN_FLIGHT`, `NAMED_STOP_CANCEL_FAILED`, `NAMED_STOP_PROOF_REQUIRED`, `PHYSICAL_ISOLATION_CONTRADICTED`, `NAMED_STOP_RELEASE_NOT_STORED`. The robot row gains `named_stop_custody` (`reservation_id`, `age_s`, `missing_proof`, `motion_refused_site_wide`, `operator_action`) while a claim exists.
