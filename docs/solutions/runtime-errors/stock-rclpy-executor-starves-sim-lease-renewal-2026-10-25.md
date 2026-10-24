---
title: A ROS process that also renews a policy lease must spin on OwnerMultiThreadedExecutor, not the stock one
date: 2026-10-25
category: runtime-errors
module: middleware/robot_execution/local/test/policy_chain_vla_gazebo.py (D-866 P0); SimPolicyChain lease worker
problem_type: runtime_error
component: testing_framework
symptoms:
  - "Gazebo P0 SmolVLA probe: owner HOLD policy_lease_expired_or_invalid / policy_authority_stale mid-run, child then 403 ARM_POLICY_FORBIDDEN"
  - "Fleet server answered lease exchanges in <=5 ms; the probe's client saw a 21-43 ms median and up to 0.93 s"
  - "renewals took 0.56-0.98 s against the 0.75 s the worker leaves (1 s lease, renew at 3 x 0.25 s remaining)"
root_cause: concurrency
resolution_type: code_fix
severity: high
framework_version: ROS 2 Jazzy rclpy 7.1.x, Python 3.12, Gazebo Harmonic headless
tags: [rclpy, multithreadedexecutor, gil, lease, fleet, sqlite, fsync, gazebo, d-866, d-854]
applies_when:
  - "a process spins an rclpy executor and also runs a deadline-bound thread (lease renewal, watchdog, HTTP client)"
  - "a Gazebo/remote_sim probe exercises SimPolicyChain or CoreArmPolicyPort"
---

# A ROS process that also renews a policy lease must spin on OwnerMultiThreadedExecutor, not the stock one

## Problem
The D-866 P0 probe runs the OMX owner, CORE's policy port, two Gazebo cameras and the SimPolicyChain lease worker in one Python process. The worker renews a 1 s Fleet lease when 0.75 s remain, with three HTTP exchanges bounded at 0.25 s each. Stop and revoke cases failed at random: the lease expired before the arm reached the case under test.

## What Didn't Work
- Relaxing contract timing, thread limits, 5 Hz cameras, recording from port return values: each removed a real cost but the lease still expired.
- `sys.setswitchinterval(0.0005)`: client exchange median went from 21-25 ms to 31-43 ms. Its revert commit failed silently (the amend only renamed it), so it stayed on until review; the third round passed without it.
- Reading `PermissionError('SIM lease renewal failed closed')`: `renew()` raises `from None`. The real check is in `error.__context__`; record it.

## Root Cause
Two separate costs, found by measuring each one instead of guessing:
1. **Disk fsync.** The lab AI PC disk was 95% full with I/O pressure; a Fleet store transaction used 1 ms CPU but 40-55 ms wall, and one lease POST hit 0.32 s. Fixture SQLite stores now live in `/dev/shm` (fsync unchanged) and are copied into the evidence.
2. **The stock `MultiThreadedExecutor`.** `py-spy record --gil` showed 82% of GIL samples in its `_wait_for_ready_callbacks` loop on the main thread; callbacks themselves were negligible. The lease worker's HTTP hand-backs waited behind it. The product owner already ships `omx_adapter.ros_owner_executor.OwnerMultiThreadedExecutor` (yields the GIL each turn, rclpy 7.1.12 scheduling gaps), and `RosArmCommandRuntime`'s docstring says to use it. The probe had copied the stock executor from `policy_chain_gazebo.py`.

## Solution
- Spin on `OwnerMultiThreadedExecutor(num_threads=4)`.
- Fixture SQLite (Fleet, execution journal, stop fence) in `/dev/shm`.
- Instrumentation kept in the probe: per-exchange start/elapsed, renewal wake time, remaining lease, fetch vs session phase, hidden cause, a 10 ms heartbeat for process stalls, GC pauses.

A side effect: the owner executor raised joint intake to ~97 Hz. The session keeps 64 observations (~0.66 s), so a 2.5 s late action was refused as `policy_candidate_scope_or_observation` (source evicted) instead of `policy_action_stale`. The stale case now uses action age 0.4 s and a 0.5 s delay; normal steps measured 0.12-0.15 s observe-to-submit.

## Verification
AI PC, 12-core/10 GB scope, NVIDIA EGL, RTF 0.75-0.80. After the fix all three cases passed in three rounds (the last without the switch-interval change): Fleet exchange median 5-6 ms, worst renewal 0.25 s (budget 0.75 s), 1-11 heartbeat stalls over 50 ms per run, none over 0.1 s (was 33, up to 0.11 s). Before: renewals to 0.98 s, stalls to 0.11 s. Evidence: `docs/validation/omx-vla-policy-chain-2026-10-25/`.

## Prevention
- Any process that hosts a lease worker or other deadline thread next to rclpy uses `OwnerMultiThreadedExecutor` (or a single-threaded/events executor), never the stock `MultiThreadedExecutor`.
- When a deadline thread misses, measure server vs client time, then `py-spy --gil`, before changing bounds. Do not relax the 1 s lease or 0.25 s transport bound for a test.
- Keep a stale-action probe's delay inside `observation_history_capacity / joint rate`.
- Open: the production CORE (`middleware/core/gateway/core/node.py`) spins the stock `MultiThreadedExecutor`; if it ever hosts a lease worker the same starvation applies.
