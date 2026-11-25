---
surface: fleet
kind: additive
slug: robot-map-bundle-export
date: 2026-11-25
title: Read-only robot map bundle export
history: Additive: GET /api/fleet/robots/{robot_id}/map/bundle
---
Exports the configured robot CORE occupancy grid as a trinary P5 PGM and Nav2 YAML metadata. The SHA-256 verifies the PGM bytes; live map binding identifiers and robot configuration are unchanged.
