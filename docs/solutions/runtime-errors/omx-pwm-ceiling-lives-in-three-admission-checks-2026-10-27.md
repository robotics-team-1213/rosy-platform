---
title: Raising an OMX PWM cap needs the ceiling changed in three admission checks, and reach error can be a P gain, not torque
date: 2026-10-27
category: runtime-errors
module: deploy/robot/omx (record_session.py, guarded_native.py, motor_health.py)
problem_type: runtime_error
component: deployment
symptoms:
  - "shoulder_lift at 0.23 m reach: 78 % of PWM 300 and a following error > 5 deg (guard stop)"
  - "after caps.json 12/13 = 600: 'shoulder_lift: invalid PWM_Limit 600' from guarded_native, then 'invalid motor health configured limits' from motor_health; one refusal per session start"
  - "at PWM 600 the shoulder used 47 % yet still trailed 4.66 deg"
root_cause: duplicated_ceiling_and_low_factory_gain
resolution_type: code_fix
severity: medium
tags: [omx, arm-s, pwm, p-gain, guard, motor-health, caps]
applies_when: "an OMX caps.json value or session gain is raised past what earlier sessions used"
---

# A PWM ceiling lives in three places

## Problem

The user chose to raise the arm S shoulder and elbow (XL430) above PWM 400 for far reach. `record_session.load_caps` was changed to allow 600. The session started, wrote the caps, and was refused before any motion, twice: first by the guard, then by the motor health monitor. Each refusal cost a deploy and a session start. Both ended with safe_end true.

## Cause

The 400 ceiling was written separately in each admission check:

| Check | Where |
|---|---|
| caps file | `record_session.load_caps` (`PWM_MAX`, now `XL430_PWM_MAX` 600 for XL430) |
| guard admission | `guarded_native.NativeJointMotion` (now `PWM_ADMIT_MAX` per joint) |
| health admission | `motor_health.MotorHealth.admit` (now 600 for joints the guard admitted) |

Once torque was enough (47 % of 600), the shoulder still trailed 4.66°. Its factory Position P Gain is 640, the lowest on the arm (elbow 1500). The session gain `"p"` in caps.json (now 1200 for ID 12, 1200 for the wrist ID 14) is restored to the value found when the session ends.

## Fix and evidence

- Raised each ceiling per joint model. The XL330 wrist stays at 400. Remote tests on 28c51e2cc1: 288 passed across the guard, health, session, runner, bimanual and two-arm suites.
- Real arm: session admitted with `ID12 PWM=0/600`. The local map at the container finished, with shoulder at most 47 % and 4.66°.

## Next time

- Before raising a cap, grep every admission bound at once: `git grep -n "PWM_Limit\|pwm_limit" deploy/robot/omx | grep "<=\|MAX"`. Do not find them one session start at a time.
- When a joint trails with PWM well under its cap, read its P gain (`joint_tune.SerialBus(port, id).read("p_gain")` with torque off) before raising PWM.
- The session cleanup path writes only torque and caps. A session gain goes back through the ordinary write. Otherwise the session ends safe_end false (fixed in record_session on 2026-10-26).
