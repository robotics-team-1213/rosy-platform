---
surface: core
kind: additive
slug: leased-road-speed
date: 2026-11-26
title: Leased speed ceilings for Nav2 road routes
---
CORE advertises navigation.route_speed_authority. Authenticated route and bound-route requests may opt into road_speed_controlled with an owned goal lease. The route starts with zero wheel authority. The sending token renews its precise correlation ID with speed_grant containing issued_at and expires_at in Unix seconds and a nonnegative limit_mps. CORE rejects stale, future, unordered and over-two-second grants. Ordinary lease renewals do not extend the speed grant. The device caps forward and reverse translation while preserving curvature, and expired or zero grants hold rotation as well.

Fleet requests this authority for Nav2 trips with an approved binding, a required binding, or active site rules. It includes every mapped stripe in the reachable distance, respects the active maximum speed and minimum following distance, and records the limit, reason, owner and expiry in trip detail. The speed grant expires within 1.5 seconds of the oldest relevant pose. A moving trip with a stale peer pose holds on the ring. The Nav2 local controller and the existing traffic blocks, obstacle checks and safety limits remain in force.
