---
title: Every OMX commissioning tool refused because a past session left the follower caps raised in EEPROM
date: 2026-10-24
category: runtime-errors
module: deploy/robot/omx (commissioning_limits.py, joint_tune.py, record_session.py, cell_check.py)
problem_type: runtime_error
component: deployment
symptoms:
  - "joint_tune.py: motor 15 caps {'pwm_limit': 300, 'current_limit': 500} are not the commissioning baseline; an earlier run did not restore them"
  - "all six followers read PWM Limit 300 and, on 14-16, Current Limit 500 (the caps.provisional.json values)"
root_cause: state_left_by_interrupted_session
resolution_type: code_fix
severity: medium
tags: [omx, dynamixel, eeprom, pwm-limit, current-limit, commissioning, fleet-pc]
applies_when: "joint_tune.py or record_session.py refuses with 'not the commissioning baseline', or a follower is found with caps above PWM 20 / Current 50"
---

# Follower caps left raised in EEPROM

## Problem
`record_session.py` raises the follower PWM and Current Limits for a run and restores them on every exit it controls. These registers are in EEPROM, so they survive power-off. A session that dies without running its cleanup leaves them raised: power removed, board unplugged, or the process killed. Examples are a hub drop or a reboot during a recording. On 2026-10-24 the followers read PWM 300 / Current 500. No record shows which session left them that way.

Both `joint_tune.py` and `record_session.py` correctly refuse to start from raised caps. A run that started there would treat 300 as its resting value and restore it again. The refusal only said "lower them with commissioning_limits.py", and that tool required a hand-written limits JSON, so the fix was a manual hunt.

## Fix
- `commissioning_limits.py --baseline` applies the resting caps (PWM 20, Current 50, profile acceleration/velocity 1) without a file. Its guards are unchanged: torque OFF and no hardware error on all six motors, decreasing writes only, one verified write at a time, and a journal plus receipt in a new `--output` directory.
- The refusals in `joint_tune.py` and `record_session.py` name `--baseline`.
- `cell_check.py` reports raised caps per motor together with the exact command, before any motion tool runs.

## Recovery
1. Confirm torque OFF (`register_probe.py` or `cell_check.py`).
2. Run `commissioning_limits.py --device <follower by-id> --baseline --output <new dir>`. Success means `"configuration_verified": true`.
3. Run `cell_check.py` again. The caps checks must read `resting`.

## Not the same problem
In `joint_tune.py` a `hold: did not settle` on a loaded joint (12 at PWM 150: 732↔733) is not this problem. A one-tick oscillation at torque ON deliberately counts as not stable (`test_startup_never_sends_a_move_until_the_hold_is_observed_stable[jitter]`). It means the joint is barely holding. Raise its PWM while searching for caps. Do not loosen the stability rule.

## Evidence
Fleet PC 2026-10-24 20:34 refusal, then the `commissioning_limits.py` receipt in `~/rosy-test/omx-record-prep-20261019/limits-restore-*` (`configuration_verified: true`). After that, ID 15 moved +40 of +50 ticks and both caps read 20/50. Workspace record: `Rosy/docs/workspace-records/2026-10-24/omx-arm-s-first-check.md` (outside git).
