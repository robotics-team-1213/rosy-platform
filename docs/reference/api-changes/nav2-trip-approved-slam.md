---
surface: fleet
kind: additive
slug: nav2-trip-approved-slam
date: 2026-11-26
title: Approved SLAM for named Nav2 trips
---
`POST /api/fleet/robots/{robot_id}/trip` accepts `approved_slam_required: true` for a named destination with `drive_mode: "nav2"`. Fleet plans and checks progress with the fresh CORE pose transformed by the active approved binding. The plan records `nav2_binding_id`. Start and execution require that same binding and a fresh pose. Planning responds with `TRIP_POSE_UNTRUSTED` and `reason: APPROVED_SLAM_POSE_REQUIRED` when those inputs are unavailable.

Sites with `fleet.trip.map_binding_required: true` apply this behavior to all named Nav2 trips. On other sites the caller opts in per trip. The robot card exposes the option as Nav2 with an approved SLAM pose.

Bound trips require CORE capability `navigation.bound_route`. Fleet refuses unsupported CORE with `NAV2_BOUND_ROUTE_UNSUPPORTED` and submits eligible points to the grid-checked CORE endpoint.
