---
surface: fleet
kind: additive
slug: bay-dock-prerequisites
date: 2026-11-26
title: 주차 대기 위치의 CORE 도킹 사전 진단
---

GET `/api/fleet/robots/{robot_id}/bays/{bay_id}/dock-prerequisites` reads the selected CORE dock and docking owner. It returns the robot and bay IDs, dock ID, receipt time `checked_at` (Unix seconds), and per-check error codes for `target`, `scoped_cancel` and `owner`. Null means the individual read succeeded. A parking plan whose origin is within staging tolerance carries this observation as `parking_handoff.plan_prerequisites` in its stored receipt. Wire admission independently rechecks the target, owner, staging and traffic.
