---
surface: fleet
kind: additive
slug: localization-pose-request-warning
date: 2026-11-26
title: Retain a pending pose request during localization verification
---
A robot's localization badge in `GET /api/fleet/state` includes `pose_request_needs_human: true` when the Fleet pose request needs operator review. The Console keeps this warning while CORE checks a candidate. The existing `needs_human` flag continues to represent either CORE or Fleet review.
