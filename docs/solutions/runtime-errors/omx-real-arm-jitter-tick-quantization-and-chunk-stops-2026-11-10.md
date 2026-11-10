---
title: Real OMX arm jitter from cleared servo profiles, tick-quantized slow steps, and unblended chunk stops
date: 2026-11-10
category: runtime-errors
module: deploy/robot/omx (omx-ai-follower-tuning.json, guarded_native.py, chunk_runner.py, grasp_planner.py, cell_pipeline_io.py)
problem_type: runtime_error
component: development_workflow
symptoms:
  - "Visible shaking/jittering in real OMX camera videos while MuJoCo real2sim videos remain smooth"
  - "57-90% sent_stall (integer tick quantization stalls) on shoulder_lift/wrist_flex and 41-47 direction reversals per transit in trace-arm_b-20261110-200027.jsonl"
  - "5 Hz loop-period ripple (p95_dt 52-60 ms on a 30 Hz loop) and 2.5 s settle pauses / 25 s full-height folds on local hover adjustments"
root_cause: wrong_assumption
resolution_type: code_fix
severity: high
tags: [omx, jitter, chunk-runner, guarded-native, motion-profile, servo-tuning]
applies_when: "streaming 30 Hz joint targets or multi-chunk pick-and-place trajectories on real OMX followers"
---

# Smooth hardware interpolation and blended chunk streaming on real OMX arms

**What happened.** Real camera videos from the 2026-11-10 OMX tier-stack runs showed visible shaking and stop-and-go pauses across transits and vertical descents, whereas the MuJoCo `real2sim` runs were completely smooth.

**Root causes measured in `trace-arm_b-20261110-200027.jsonl` and `session.jsonl`.**
1. **Cleared servo profiles (`Profile_Acceleration = 0`, `Profile_Velocity = 0`) + integer tick quantization.** `guarded_native.connect_passive` keeps a session servo profile in `PROFILE_ACC = (5, 100)` / `PROFILE_VEL = (15, 200)` only when `record_session` writes both `"acc"` and `"vel"`. Because `omx-ai-follower-tuning.json` and the site `caps.json` omitted `"acc"` and `"vel"`, every motor ran with `profile_acc = 0` and `profile_vel = 0` (step goals). At slow joint speeds (`0.1-0.3` encoder ticks per 33 ms frame), `int(v)` truncation in `guarded_native.commit` produced `57.3%-89.3%` `sent_stall` on `shoulder_lift` and `71.9%-90.5%` on `wrist_flex`, snapping by 1 tick after 3-9 stalled ticks and ringing at high P-gain (`41-47` present-position reversals per transit).
2. **5 Hz unicast PWM read stall in `guarded_native._check_effort`.** Reading `Present_PWM` with 5 separate `follower.read("Present_PWM", name)` packets every `0.2 s` added ~18 ms of serial latency every 6th tick (`p95_dt = 52-60 ms` on a 33.3 ms loop).
3. **Trapezoid jerk step in `motion_profile.retime`.** While `flow()` used half-cosine (`eased`) acceleration, `retime()` (used by `grasp_planner.py` for `descend_*` and `lift_*`) still used `trapezoid()`, stepping acceleration from `0` to `amax` in one tick (`110 units/s^3` jerk).
4. **Fragmented chunk execution and local-hover full-height folding.**
   - `transit_path` only used direct `flow()` when `max(abs(a - b)) <= 8.0`; a 12-24 mm `cell_feel` / `cell_reach` shift changed `elbow_flex` by `9.6-13.5` units, causing a full fold to `TRANSIT` (`shoulder_lift = -27`) that took `25.3 s` per retry.
   - At the end of a loaded chunk where static gravity droop was `2.05-2.20` units (`> SETTLE_TOL = 2.0`), `chunk_runner` waited the full `SETTLE_S = 2.5 s` timeout even after the body joints had come to rest, and `FifoCell.act` added `100 ms` polling sleeps per command.

**Fix.**
- `omx-ai-follower-tuning.json`: add `"acc": 8, "vel": 20` on body motors `11..15` so every session ramps smoothly between integer-tick goals in hardware.
- `guarded_native.py` & `motor_health.py`: read `Hardware_Error_Status` (30 Hz) and `Present_PWM` / `Present_Temperature` / `Present_Input_Voltage` / `Torque_Enable` (5 Hz) via batch `sync_read` on `DynamixelMotorsBus`, cutting per-tick serial reads from 7 packets to 2 and 5 Hz health sample reads from 30+ unicast packets to 5 `sync_read` packets.
- `motion_profile.py`, `chunk_library.py`, `grasp_planner.py`: upgrade `retime()` to half-cosine `eased_progress`, add `blend_chunks` / `chain_path` to overlap consecutive body chunks without dead stops, and raise `transit_path`'s local-hover direct-flow threshold from `8.0` to `16.0` units.
- `chunk_runner.py`, `cell_pipeline_io.py`, `omx_incident.py`: settle immediately when the body is still within the measured droop floor (`SETTLE_TOL + min(pace_floor, 0.8)`), reuse `last_present` for `live.json`, support `chain <step1> ; <step2> ...`, reduce FIFO status polling sleep from `0.1 s` to `0.02 s`, and guard `omx_incident.decide` against non-integer error strings in `torque_after` on USB disconnect.
