---
title: Explicit chunk_runner stop cut torque while extended without folding home, and empty-jaw park tripped jaw-push on arm_s
date: 2026-11-12
category: runtime-errors
module: deploy/robot/omx (chunk_runner_commands.py, chunk_runner_settle.py, chunk_runner_run.py)
problem_type: runtime_error
component: development_workflow
symptoms:
  - "Sending an explicit 'stop' command to chunk_runner while the arm was at standby or an extended waypoint immediately returned False and turned off torque without folding to home ('folded': false)"
  - "Running 'park' on arm_s with empty jaws aborted mid-air with 'contact in park: the jaws stopped 2.4 units short at PWM -150 of 300: something is in them'"
  - "Holding an extended pose on arm_s with i_gain=50 on elbow_flex/wrist_flex triggered 'pushing at rest' wind-up, and rising from p_horiz/b_far at >0.05 units/tick tripped shoulder_lift strain (>2.0 units at PWM -313 of 600)"
root_cause: missing_safety_step_on_explicit_stop
resolution_type: code_fix
severity: high
tags: [omx, chunk-runner, park, stop, torque-off, arm-s, gripper-closed]
applies_when: "ending a hardware chunk_runner session via 'stop' or executing park / upward crane-lift returns on OMX followers"
---

# Hardware auto-fold to `home` before `stop` torque-off and `arm_s` empty-jaw / lift calibration

## Symptoms

1. **Immediate torque-off without folding to `home` on explicit `"stop"`.** While `check_runner_idle` in `chunk_runner_settle.py` folded the arm to `home` via `park` after `IDLE_PARK_S` of inactivity before stopping, sending an explicit `"stop"` command in `chunk_runner_commands.py` (for example from a caller script's `finally:` block after an aborted chunk or at `standby`) immediately returned `False`, causing `chunk_runner.py` and `record_session.py` to disable torque while the arm was still extended (`"folded": false`).
2. **Empty-jaw contact hold during `park` on `arm_s`.** On `arm_s`, physical empty-jaw contact occurs at `48.86` units. When a chunk library configured `"gripper_closed": 46.5` (copied from `arm_a`/`arm_b`), `park_path` commanded the empty jaws to `46.5`; they stopped `2.36` units short (`> windup.jaw_gap = 2.0`) at `PWM -150`, tripping `joint_push.pushing` (`"contact in park: the jaws stopped 2.4 units short"`).
3. **Extended-pose I-gain wind-up and upward `shoulder_lift` lag on `arm_s`.** Pausing at an extended hover pose (`b_far_above_pick`) with `i_gain: 50` on `elbow_flex` (ID 13) and `wrist_flex` (ID 14) wound up integral effort past `PWM 250` at rest (`pushing at rest`), and lifting `shoulder_lift` from `-4.3` / `+6.5` back to `-27.0` at `0.06+ units/tick` exceeded `2.0 units` lag at `PWM -313 of 600`.
4. **Full-Speed OpenRB-150 USB 2.1 Hub TT contention.** When the Full-Speed (`12 Mbps`) `OpenRB-150` (`3-1.1`) re-enumerates behind the shared USB 2.1 Hub (`3-1`) while both High-Speed UVC cameras (`3-1.3`, `3-1.4`) stream concurrently, Transaction Translator contention can stall `device descriptor read/64, error -110`; if the board stays powered by the external 12V SMPS, cycling the 12V rail (with UVC streams paused) resets the MCU USB SIE.

## Root Cause

- `dispatch_runner_command` in `deploy/robot/omx/chunk_runner_commands.py` treated `"stop"` as an unconditional loop exit (`return False`), bypassing `park_path` even when `operating_context["scope"] == "hardware"` and the arm was far from `home`.
- During an ungrasped (`not runner.holding`) fold, commanding `gripper_closed` below the follower's physical empty-jaw contact triggers the jaw-obstruction guard.

## Fix & Verification

1. **Auto-fold to `home` on hardware `"stop"` (`chunk_runner_commands.py`, `chunk_runner_settle.py`, `chunk_runner_run.py`).**
   - When `"stop"` (or `"stop fold"`) arrives and `fold_on_stop` is active (`operating_context.get("scope") == "hardware"` or `runner.fold_on_stop`), if a `home` chunk exists in `runner.library["chunks"]`, the arm is farther than `SETTLE_TOL` from `home[-1][:5]`, and no hard fault or overload-hold is active, `dispatch_runner_command` queues `park_path` from the current pose to `home[-1]` (preserving `runner.target[5]` when `not runner.holding` so empty jaws never pinch-fault during shutdown) and sets `runner._stop_after_park = line`.
   - Once `check_chunk_settled` settles the `park` chunk at `home`, it emits the final `"stop"` status (`folded=True`, `reason="folded home before stop, torque goes OFF"`) and sets `runner._stopped = True` so `Runner.run` exits only after folding to `home`.
2. **`arm_s` library and servo caps calibration.**
   - Use `i_gain: 0` on `shoulder_lift`, `elbow_flex`, and `wrist_flex` (IDs 12, 13, 14) on `arm_s`, set `"gripper_closed": 48.5` (within `0.4` units of `48.86` physical contact), keep upward `shoulder_lift` step sizes `<= 0.032 units/tick`, and fold to `home` in script `finally:` blocks before sending `"stop"`.
3. **Verification.**
   - Unit test `test_hardware_stop_while_extended_folds_home_before_turning_torque_off` in `test/test_omx_chunk_runner.py` (`78 passed`).
