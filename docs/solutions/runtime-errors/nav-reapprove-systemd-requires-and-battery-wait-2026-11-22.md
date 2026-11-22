---
title: rosy-nav-reapprove systemd Requires and missing filtered_voltage wait strand Pinky in motor mode after CORE restarts
date: 2026-11-22
last_updated: 2026-11-22
category: runtime-errors
module: deploy/robot/pinky_pro/native/rosy-nav-reapprove.service, deploy/robot/pinky_pro/native/navigation_reapprove.py
problem_type: runtime_error
component: pinky_native_commissioning
symptoms:
  - "rosy-nav-reapprove.service receives SIGTERM from systemd immediately after POST /api/v1/navigation/approval/begin restarts rosy-core.service, stranding the robot in ROSY_RUNTIME_MODE=motor, phase=MEASURING, with a 4h navigation-approval hold."
  - "POST /api/v1/navigation/approval/trial/start fails with 409 CHARGING_UNKNOWN right after begin() restarts CORE even when battery_status.charging is False."
root_cause: systemd_dependency_and_incomplete_readiness_predicate
resolution_type: code_fix
severity: high
tags: [pinky-pro, systemd, nav-reapprove, d-986, battery, core-restart]
---

# `rosy-nav-reapprove.service` `Requires=` and missing `filtered_voltage` wait strand Pinky in `motor` mode

## Problem

Two defects broke automatic post-release navigation re-approval (D-986 addendum) on live Pinky robots (`geg6` during `2026.11.21-221` deployment):

1. `rosy-nav-reapprove.service` declared `Requires=rosy-core.service`. During `reapprove()`, `POST /api/v1/navigation/approval/begin` (and later `seal`) intentionally restarts `rosy-core.service` to enter/exit `ROSY_RUNTIME_MODE=motor`. Because systemd stops any active unit that `Requires=` a restarting unit, systemd immediately sent `SIGTERM` to `rosy-nav-reapprove.service` mid-`begin()`, leaving the robot stranded in `motor` mode and `MEASURING` phase.
2. CORE's `_require_unplugged()` (`middleware/core/api/core_api_web/api/v1/navigation_approval.py`) raises `409 CHARGING_UNKNOWN` whenever `battery_status.charging is not False` OR `battery_status.filtered_voltage is None`. `navigation_reapprove.py`'s `reapprove()` waited only for `battery_status.charging is False` after the `begin()` restart without checking `filtered_voltage is not None` or `/api/v1/power/health` `battery.evidence == "fresh"` and `level == "ok"`.

## Solution

- Changed `deploy/robot/pinky_pro/native/rosy-nav-reapprove.service` from `Requires=rosy-core.service` to `Wants=rosy-core.service` (keeping `After=rosy-core.service rosy-auto-update.service`), so CORE restarts during `begin`/`seal` no longer terminate the oneshot runner.
- Updated `navigation_reapprove.py` so `Core.req` keeps `tls=True` across restart-induced TLS EOFs once TLS has succeeded (`_tls_confirmed`), `pair()` checks CORE reachability before issuing a login code, and `run()` handles an unreachable CORE cleanly with exit `0`.
- Added `_battery_ready_for_trial(robot, health)` in `deploy/robot/pinky_pro/native/navigation_reapprove.py` and updated `reapprove()` to wait until `battery_status.charging is False`, `battery_status.filtered_voltage is not None`, and `/api/v1/power/health` reports `battery.evidence == "fresh"` and `level == "ok"` before calling `trial/start`.
- Added unit tests in `test/test_navigation_reapprove.py` covering `Wants=rosy-core.service` (and absence of `Requires=`), TLS retention across restart EOFs, CORE-down handling in `run()`, and battery readiness polling before the five D-986 trials.

## Verification

- Observed failure live on `geg6` (`rosy_42`) on `2026.11.21-221`: systemd terminated `rosy-nav-reapprove.service` during `begin()`, and manual loopback `trial/start` initially returned `409 CHARGING_UNKNOWN` until fresh unplugged voltage was observed, after which the official 5-trial D-986 flow sealed cleanly.
- Verified with remote pytest (`test/test_navigation_reapprove.py`, `test/test_native_systemd_contract.py`, `test/test_native_delta_delivery.py`).

## Prevention

- Never use `Requires=` on a oneshot service whose workflow calls CORE endpoints that restart the required service (`Wants=` + `After=` preserves ordering without self-termination).
- Readiness helpers in client runners must check the exact same tuple of fields that the server gate validates (`charging`, `filtered_voltage`, and `power/health` freshness).
