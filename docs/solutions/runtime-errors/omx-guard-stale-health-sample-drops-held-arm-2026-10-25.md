---
title: The guard turned torque off on a held, extended arm because one bus read stalled the loop past 0.5 s
date: 2026-10-25
category: runtime-errors
module: deploy/robot/omx (guarded_native.py teacher mode, motor_health.py, chunk_runner.py)
problem_type: runtime_error
component: deployment
symptoms:
  - "chunk_runner exits with ValueError: stale motor health sample (>0.5 seconds) from motor_health.sample"
  - "record_session ends safe_end True, exit_code 1, torque 0 on 11-16 while the arm was holding over the box"
  - "the arm stays where it was, resting on the box, torque off"
root_cause: shared_bus_latency_spike
resolution_type: code_fix
severity: high
tags: [omx, guard, teacher-mode, motor-health, usb-hub, dynamixel, fleet-pc, arm-s]
applies_when: "a guarded OMX session faults with a stale sample while the arm holds still, or a new loop adds reads on the follower bus beside the guard"
---

# Guard stale-sample fault drops a held arm

## Problem

Arm S, first real run of `guarded_native` teacher mode under `chunk_runner` (2026-10-25). The arm held 15 mm above the box after a lateral alignment. 13 minutes after the last command, with nobody sending anything, the guard raised `stale motor health sample (>0.5 seconds)` and, by design, turned torque off. The extended arm settled onto the box.

## Cause

The motor-health log (`motor-health-<ns>.jsonl` beside the session) shows the guard's samples at a steady 0.234 s for 11 minutes (minute maxima 0.237–0.238 s), then isolated spikes: 0.281, 0.283, 0.354, 0.339, 0.428 and finally 0.622 s, which broke the 0.5 s bound. Each spike is one control-loop iteration blocked on a bus read. The follower boards sit on the Fleet PC's USB hub that already dropped both boards once (2026-10-24).

The guard reads Present_PWM for five joints, and the monitor the gripper, about 5 times a second. `chunk_runner` read Present_PWM, Present_Current and Present_Temperature on the same bus every 3 ticks (10 Hz), so the loop issued about twice the transactions the guard needed and each spike had twice the chance to land.

## Fix

`chunk_runner` reads its motor health once per `HEALTH_PERIOD_S` (1 s) and takes one fresh read for a grasp verdict (the jaws just stopped, so the 1 s sample may predate it). Its stall and temperature stops now act within about 1 s; the guard's own effort stop (90 % of PWM_Limit for 1 s) is unchanged. `test_the_runner_reads_motor_health_about_once_a_second_beside_the_guard` fails when the period goes back to 3 ticks (mutation checked).

The guard's rule stays: a stale sample is a fault, and a fault is torque off. Lowering the load makes a spike past 0.5 s less likely; it does not make the hub reliable. A powered hub or a direct cable (impossible today because of cable length) is the device-side fix.

## Recovery that worked

The arm rests where it stopped, torque off. With a person at the power switch:

1. Start a new session (`record_session.py --chunks …`). The guard seeds at the present pose and aligns without a jump.
2. Lift clear with the jaws open first (`jog elbow_flex.pos -5 wrist_flex.pos 4` reverses a 15 mm top-down descent). `park` closes the jaws before it rises and would grab a box between them.
3. `park`, then `stop`. Check `safe_end`, torque 0 and caps restored in the session record.

## Tooling trap found on the way

A command client that opens the FIFO blocking (`open(fifo, "w")`) waits forever once the runner is gone, and hands its command to the next runner that opens the FIFO. A stale `park` sat waiting this way. Open with `O_WRONLY | O_NONBLOCK` so it fails at once, and kill any waiting writer before starting a runner.

## Same hub, second failure: one corrupt status packet (2026-10-27)

The guard's per-cycle `sync_read("Present_Position")` raised `ConnectionError: Failed to sync read 'Present_Position' ... after 1 tries. [TxRxResult] Incorrect status packet!`, and the session ended with torque off. On 2026-10-27 this happened in three arm S sessions (02:41, 03:19, 13:5x). Twice the arm was parked; the third time it was 2 cm above the floor during a touch survey and dropped onto it. The read had no retry, so one bad packet ended the session.

The fix is `READ_RETRY = 2` on the guard's leader and follower position reads. A read is safe to repeat, and a bus that is really gone still fails closed after the retries. `test_a_corrupt_status_packet_is_read_again_and_a_dead_bus_still_stops` checks it: 1 or 2 bad packets pass, 3 stop with torque off. The writes are not retried; a failed write is still a fault.

The device-side cause is the same unpowered hub. Retries hide single packets, not a dying link. If `Incorrect status packet` or comm -3001 shows up in several sessions a day, fix the hub or the cable instead of raising the retry count.

Recovery from a low pose that worked: start a new session; the guard seeds at the present pose. Then `park`. It folded home slowly from 2 cm above the floor.

## Next time

- Before a long hold over an object, expect that the guard may drop the arm; keep holds short or hold at transit height.
- Do not add follower-bus reads in a loop that the guard already samples; reuse what the guard reads.
- Evidence: Fleet PC `~/rosy-test/omx-record-prep-20261019/session-guard-*.log` and `motor-health-1792915715103460629.jsonl`.
