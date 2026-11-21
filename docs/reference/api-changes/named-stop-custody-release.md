---
surface: fleet
kind: additive
slug: named-stop-custody-release
date: 2026-11-21
title: Operator release of a named-stop custody claim
history: POST /api/fleet/robots/{robot_id}/named-stop-custody/release; named_stop_custody row field
---
Additive. A named operator releases the site-wide named-stop custody claim that CORE could not prove stopped. Body: reservation_id (from the robot row named_stop_custody), operator_saw_robot_standing_still (must be true), reason. Fleet stops the robot first, best effort, then audits (site map events, action named_stop_custody_release) and releases. The stop is the console cancel (lease entry removed, stop generation bumped, navigation cancel, re-park stop when armed, the robot's trip ended); the audit row is written before the release. 503 AUDIT_UNAVAILABLE releases nothing. 409: NAMED_STOP_CLAIM_CHANGED, ROBOT_REQUEST_IN_FLIGHT, NAMED_STOP_RELEASE_NOT_STORED. The robot row gains named_stop_custody (reservation_id, age_s, missing_proof, motion_refused_site_wide, operator_action) while a claim exists.
