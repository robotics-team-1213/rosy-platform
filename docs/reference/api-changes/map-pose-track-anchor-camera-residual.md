---
surface: fleet
kind: additive
slug: map-pose-track-anchor-camera-residual
date: 2026-11-21
title: 지도 자세의 천장 추적 기준과 카메라 차이
history: Additive: `GET /api/fleet/robots/{id}/map-pose`의 `anchor_source` 값 `track`, 필드 `camera_residual_m`·`camera_residual_deg`·`camera_x`·`camera_y`·`camera_yaw`(3초 안의 카메라 관측이 없으면 null). 식별 스냅샷 로봇 행의 `mode`(`led`|`motion`|null). 설정 `fleet.map_pose.track_anchor_robots`·`track_modes`·`track_heading_min_m`, `identity.motion_match`(기본 false) (D-1062)
---

