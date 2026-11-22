---
surface: fleet
kind: additive
slug: named-stop-fleet-trips
date: 2026-11-21
title: 정차점 정밀 정차와 자동 재주차
history: Additive: 이름 있는 정차점 trip, POST /api/fleet/trips/{trip_id}/correction-clearance, 사이트 맵 precision_stop, 운영자 없는 미세 재주차
---
Fleet named-stop precision trips (v1.next): `SitePlace.precision_stop`, trip `detail.named_stop_precision`, and `POST /api/fleet/trips/{trip_id}/correction-clearance` (named operator; one scoped CORE re-park). A REPARK verdict inside CORE's fine re-park caps (`core_common.stop_pose.REPARK_MAX_FORWARD_M` / `REPARK_MAX_LEFT_M`) is corrected by the trip itself (`detail.named_stop_auto_repark`, `fleet.trip.named_stop_auto_corrections`, default 1). Outside the caps, past the limit, or under e-stop, hold, lost lease, no LOCALIZED map pose, stale pose or a refused corridor it stays HOLD and the operator route stays open.
