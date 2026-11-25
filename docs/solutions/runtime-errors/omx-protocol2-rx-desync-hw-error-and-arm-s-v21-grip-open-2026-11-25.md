---
title: OMX Protocol 2.0 +1-transaction RX desync false hardware error and arm_s v2.1 narrow base grip_open
date: 2026-11-25
category: runtime-errors
module: deploy/robot/omx (guarded_native_probe.py, guarded_native_effort.py, chunk_runner_interrupt.py, cell_directive_compiler.py)
problem_type: runtime_error
component: omx-guard-and-area-xyz
symptoms:
  - "arm_s tripped ValueError('shoulder_pan: hardware error') at s=0.941 of run park during area_xyz_pick despite pre-fault pwm=5, temp=38 C, hw_error=0"
  - "Interrupt HOLD logged garbage torque readback {shoulder_pan: 145, shoulder_lift: 250, elbow_flex: 129, wrist_flex: 9, wrist_roll: 114, gripper: 89} while post-session register_probe read all torque_enabled=0 and latched={}"
  - "area-xyz-area-arm_s-floor-to-floor-a0.library.json planned grip_open=54.7 (< 30 mm white-jaw opening 58.1), colliding on top of the 30 mm container at z=40.4 mm"
root_cause: protocol2_rx_desync_and_base_plan_grip_open_override
resolution_type: code_fix
severity: high
tags: [omx, dynamixel, protocol2, crc16, usb-hub, openrb-150, hardware-error, grip-open, arm_s]
applies_when: "Dynamixel Protocol 2.0 sync_read consumes stale packets on shared USB hub/OpenRB-150 CDC-ACM, or uncalibrated arm_s v2.1 jaws compile with a narrow base_plan['grip_open']"
---

# OMX Protocol 2.0 RX Desync False Hardware Error & `arm_s` v2.1 `grip_open`

## Symptoms
1. During `POST /jobs/area_xyz_pick` (`20261125-013042-68063f`), `arm_s` planned `above_pick` / `descend_pick` with `gripper = 54.7` (`~27.5 mm`, narrower than a `30 mm` container on v2.1 white jaws), struck the box top at `z = 40.4 mm`, retreated, and opened cleanly.
2. During `run park` (`s = 0.941`, `state = [24.88, -25.03, 17.95, 45.4, -18.14, 49.33]`), `guarded_native_effort.check_hardware_errors()` raised `ValueError("shoulder_pan: hardware error")`, cutting torque while extended (`HOLD-arm_s.json`, incident `c41646da2a2d423581fc5897edbaec68`).
3. Immediately after, `_guard_stopped()` reported `torque reads {'shoulder_pan': 145, 'shoulder_lift': 250, 'elbow_flex': 129, 'wrist_flex': 9, 'wrist_roll': 114, 'gripper': 89}`, while `register_probe.py` and `omx_incident` confirmed all 6 motors had `hardware_error: 0` and `torque_enabled: 0`.

## Root Cause
- **Protocol 2.0 +1-transaction RX desync + missing SDK/guard validation:** On the shared USB 2.1 Hub / OpenRB-150 CDC-ACM link, a delayed prior reply packet shifted RX framing by +1 transaction (+6 status packets). Dynamixel Protocol 2.0 `readRx` validates CRC and `PKT_ID` without verifying `PKT_LENGTH == length + 4` or a register tag:
  - Calculating Protocol 2.0 CRC-16 (`poly 0x8005`, init `0`) on the 11-byte `Torque_Enable = 0` Write-Ack Status Packet (`FF FF FD 00 [ID] 04 00 55 00 [CRC_L] [CRC_H]`) yields `CRC_L` = `145, 250, 129, 9, 114, 89` for IDs `11..16` — an exact 6/6 byte match.
  - `check_hardware_errors()` treated any non-zero integer `1..255` (including impossible XL430/XL330 bits outside `0x3D`, e.g., `145 = 0x91`) as an unrecoverable hardware error without RX drain or unicast confirmation.
- **Narrow `base_plan["grip_open"]` precedence:** In `cell_directive_compiler.build_plan_from_directive()`, uncalibrated `arm_s` with `tcp_x_m >= 0.073` updated `cal["grip_open_30mm"] = 58.1`, but `raw_open` preferred `plan["grip_open"]` over `cal["grip_open_30mm"]` whenever `base_plan["grip_open"]` was non-`None` (Note: `omx-tools-fd623aa584` on `rosy-arm-cell` already yields `58.15` when `grasp-plan-arm-s-live.json` has `58.5`, while this fix guarantees `>= 58.1` even when a narrow `54.7` base plan is passed).

## Fix
1. **`deploy/robot/omx/guarded_native_probe.py`**: Masked `Hardware_Error_Status` with `HW_ERROR_VALID_MASK = 0x3D` (bits 0,2,3,4,5) in `is_valid_hw_status()` and `is_hardware_fault()`, and logged the raw byte in `probe_hardware_errors()`.
2. **`deploy/robot/omx/guarded_native_effort.py`**: In `check_hardware_errors()`, reject invalid/desynced bytes (`!is_valid_hw_status`) as recoverable `TelemetryReadError` after `_drain_rx()` (`port_handler.clearPort()`), and on a valid fault bit with `port_handler` present, drain RX and confirm once with unicast `read("Hardware_Error_Status", name)` before declaring an unrecoverable fault.
3. **`deploy/robot/omx/chunk_runner_interrupt.py`**: In `_guard_stopped()`, if any `Torque_Enable` value is not in `(0, 1)`, call `port_handler.clearPort()` and retry `sync_read` once.
4. **`deploy/robot/omx/cell_directive_compiler.py`**: For uncalibrated `v21_arm_s` (`samples == 0`, `tcp_x_m >= 0.073`), take `max(cal["grip_open_30mm"], plan["grip_open"])` (and likewise for `grip_release`) unless `grip_open_override` is explicitly set.

## Operational Recommendation
- Move the `arm_s` OpenRB-150 USB controller off the unpowered USB 2.1 Hub shared with High-Speed UVC cameras onto a dedicated host root port or powered hub.
