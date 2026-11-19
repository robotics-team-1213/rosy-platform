---
title: Pinky Pro multi-bay berthing needs centerline LiDAR axial gap and exposed rail_entry_m
date: 2026-11-12
last_updated: 2026-11-12
category: runtime-errors
module: operations/fleet/fleet/server/ledger and middleware/core/api/core_api_web/api/v1/docking.py
problem_type: runtime_error
component: docking_and_navigation
symptoms:
  - "During forward departure from middle charging bay C2 (rosy_45), PINKY_PRO.translation_gap(pts, reverse=True) changed by only 0.0075 m over 0.103 m of physical motion, triggering a false body_not_moving abort."
  - "POST /api/v1/docking/types with compact bay staging_offset_m <= 0.45 m failed with HTTP 400 VALIDATION_ERROR: rail_entry_m must be positive and short of staging_offset_m."
root_cause: logic_error
resolution_type: code_fix
severity: medium
tags: [pinky-pro, docking, berthing, lidar, charging-bay, fleet]
---

# Pinky Pro multi-bay berthing needs centerline LiDAR axial gap and exposed rail_entry_m

## Problem

When undocking and berthing Pinky Pro robots across adjacent 3D-printed charging bays (`C1`, `C2`, `C3`, spaced `180 mm` center-to-center on `world_261026`), two issues blocked compact multi-bay berthing:

1. `PINKY_PRO.translation_gap(pts, reverse=True)` evaluates minimum clearance across the full body corridor width `|y| <= half_width_m + margin` (`±0.080 m`, `160 mm` total width). In the middle bay (`C2`, `rosy_45`), as soon as the robot moved `+0.103 m` forward, the adjacent bay guide rail and neighbor robot parked in `C1` (`rosy_46`) entered the outer edge of the `±0.080 m` rear corridor at `x ≈ -0.17 m` (`rg_wide = 0.1104 → 0.1294 m`), masking the true Bay C2 rear stop-face distance (`rg_center = 0.2280 m`).
2. `DockTypeRequest` in `middleware/core/api/core_api_web/api/v1/docking.py` omitted `rail_entry_m`, leaving `DockType.rail_entry_m` pinned to its `0.45 m` default and rejecting any compact bay `staging_offset_m <= 0.45 m`.

## Symptoms

- On `rosy_45` (Bay C2), forward departure aborted at `odom = 0.103 m` with `RuntimeError: body_not_moving during forward departure: odom=0.103m, lidar_delta=0.0075m`, even though the overhead camera (`ceiling_north` 3x ROI) and centerline LiDAR rays (`rg_center = 0.2280 m`) confirmed the robot had physically moved `+0.1176 m` out of Bay C2.
- Pulling off the Bay C2 charger at `7.575 V` caused battery sag under motor load to `7.32 V` (`10.5%`, `critical`), latching `EMERGENCY` (`source: battery_policy`).
- Creating `charge_bay_rear` via `POST /api/v1/docking/types` with `staging_offset_m = 0.32` returned `HTTP 400 VALIDATION_ERROR: rail_entry_m must be positive and short of staging_offset_m`.

## Solution

1. **Separate wide collision guarding from axial stop-face distance (`centerline_axial_gaps`)**:
   - Keep `PINKY_PRO.translation_gap(pts)` (`±0.080 m`) for wide collision guarding, and compute axial progress / rear stop-face distance over a narrow centerline strip `|y| <= 0.025 m` (`50 mm` width) in `operations/fleet/fleet/server/ledger/berth_parking_routes.py:66`.
2. **Expose `rail_entry_m` in `DockTypeRequest`**:
   - Added `rail_entry_m: float = 0.45` to `DockTypeRequest` in `middleware/core/api/core_api_web/api/v1/docking.py:64` so compact bays (`rail_entry_m = 0.085 m`, `staging_offset_m = 0.20 m`) validate cleanly.
3. **Recovery & Live Verification**:
   - Released `rosy_45`'s `battery_policy` latch via Administrator `POST /api/v1/safety/release` (D-502 Decision 2 & 4) and executed the two-phase berthing funnel (`ALIGNING` outside `rail_entry_m = 0.085 m`, then `REVERSING_IN_RAILS` with `angular = 0.0` inside the rails).
   - Verified on live hardware:
     - `rosy_46` (Bay C1): `+0.2001 m` LiDAR forward departure -> `REVERSING_IN_RAILS` (`ω = 0.0`) -> `0.5 mm` position error, `-0.25°` heading error, `IDLE`.
     - `rosy_45` (Bay C2): `+0.1805 m` centerline LiDAR forward departure -> `REVERSING_IN_RAILS` (`ω = 0.0`) -> `3.4 mm` stop-face error (`rg_wide = 0.1138 m` vs `0.1104 m`), `+0.33°` heading error, `IDLE`.
   - Unit regression tests added in `operations/fleet/test/test_berth_parking_routes.py`.

## Prevention

- In multi-bay or tight-corridor docking (`bay spacing <= 200 mm`), never use full-body-width `translation_gap` (`±0.080 m`) as the axial distance to the rear stop face; always measure axial progress along the narrow centerline strip (`|y| <= 0.025 m`) while keeping wide `translation_gap` for obstacle/collision stop checks.
- Before commanding an undock-and-berth cycle on a charging robot, check unloaded vs loaded battery voltage; if `voltage < 7.60 V`, expect load sag across the `7.40 V` critical threshold and use D-502 Administrator `/api/v1/safety/release` to immediately berth back onto the charging contacts.
