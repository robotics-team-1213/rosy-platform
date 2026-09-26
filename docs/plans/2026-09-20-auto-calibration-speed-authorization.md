# Auto Calibration Speed Authorization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add fail-closed geometry/sensor and motion-envelope certification, then carry a measured adaptive linear-speed cap through the Control-to-CORE policy handoff without authorizing unmeasured higher physical speeds.

**Architecture:** Keep estimation and certificate validation in ROS-free Control modules. A candidate becomes active only after independent holdout evidence, and an active motion envelope remains bound to the geometry certificate digest and operating-condition bands. The sensor-only Control producer computes a live, reducing-only cap; CORE remains the sole final `cmd_vel` owner and applies that cap with every other safety limit.

**Tech Stack:** Python 3 dataclasses/JSON/hashlib/pytest, ROS 2 Jazzy Control handoff, C++17 BNO055 driver contract tests.

---

### Task 1: Geometry and sensor certificate contract

**Files:**
- Create: `src/core/control/control/control/commissioning_certificate.py`
- Create: `src/core/control/test/test_commissioning_certificate.py`

**Step 1: Write the failing tests**

Cover finite bounded wheel multipliers, uncertainty fields, excitation rank, raw-evidence digests, candidate status, independent holdout session identity, digest binding, defensive copies, and rejection of direct candidate activation.

**Step 2: Run tests to verify they fail**

Run: `python -m pytest src/core/control/test/test_commissioning_certificate.py -q -p no:cacheprovider`

Expected: collection failure because `control.control.commissioning_certificate` does not exist.

**Step 3: Write minimal implementation**

Implement canonical SHA-256 digesting, `make_geometry_candidate`, `promote_geometry_candidate`, and `validate_geometry_certificate`. Promotion must require a distinct holdout session, finite residual limits, a matching candidate digest, and `holdout.passed is True`.

**Step 4: Run tests to verify they pass**

Run: `python -m pytest src/core/control/test/test_commissioning_certificate.py -q -p no:cacheprovider`

Expected: PASS.

### Task 2: Motion envelope certificate and adaptive governor

**Files:**
- Modify: `src/core/control/control/control/commissioning_certificate.py`
- Create: `src/core/control/control/control/adaptive_speed.py`
- Create: `src/core/control/test/test_adaptive_speed.py`

**Step 1: Write the failing tests**

Specify direction-specific speed bins with `command_to_decel_p99_s`, positive conservative deceleration lower bound, stop-distance upper bound, lateral-error upper bound, condition bands, active geometry digest, and independent holdout. Specify a governor that never increases a request, stops on unknown/expired evidence, selects only measured bins, uses the conservative required-distance equation, continuously reduces inside a certified bin, and immediately downgrades on drift or condition-band mismatch.

**Step 2: Run tests to verify they fail**

Run: `python -m pytest src/core/control/test/test_adaptive_speed.py -q -p no:cacheprovider`

Expected: collection failure because the governor API does not exist.

**Step 3: Write minimal implementation**

Add motion-envelope candidate/promotion validation and implement `OperatingConditions`, `RuntimeEvidence`, `SpeedDecision`, and `limit_command`. Keep `HOLD`, `LIMITED`, and `CRAWL` available, but reject any active bin above `0.014 m/s` unless the caller explicitly supplies a higher hardware ceiling; the repository default will remain `0.014 m/s`.

**Step 4: Run tests to verify they pass**

Run: `python -m pytest src/core/control/test/test_adaptive_speed.py src/core/control/test/test_commissioning_certificate.py -q -p no:cacheprovider`

Expected: PASS.

### Task 3: Carry the live speed cap through the Control-to-CORE handoff

**Files:**
- Modify: `src/core/control/control/control/command_gate.py`
- Modify: `src/core/control/control/control/policy_handoff.py`
- Modify: `src/core/control/control/safety/node.py`
- Modify: `src/core/control/test/test_command_gate.py`
- Modify: `src/core/control/test/test_policy_handoff.py`
- Modify: `src/core/core/test/test_control_policy_link.py`

**Step 1: Write the failing tests**

Add tests that a finite nonnegative `linear_limit` is snapshot-bound, cannot enlarge a request, preserves curvature only when both components can be proportionally limited, rejects malformed limits, expires with the observation lease, and arrives in CORE's `SafetyDecision` before final clipping.

**Step 2: Run tests to verify they fail**

Run: `python -m pytest src/core/control/test/test_command_gate.py src/core/control/test/test_policy_handoff.py src/core/core/test/test_control_policy_link.py -q -p no:cacheprovider`

Expected: failures showing the handoff has no live numeric cap.

**Step 3: Write minimal implementation**

Add the optional cap to `GateSnapshot` and `ControlPolicyProducer.publish`. Clamp the candidate in `CommandPolicy.evaluate`; missing commissioned envelope remains the existing `0.014 m/s` profile ceiling. The sensor-only node may publish only a reducing cap derived from current evidence and must invalidate the policy on malformed output.

**Step 4: Run tests to verify they pass**

Run the same command and expect PASS.

### Task 4: Expose BNO055 calibration and self-test evidence

**Files:**
- Modify: `src/hardware/imu_bno055/src/bno055_device.hpp`
- Modify: `src/hardware/imu_bno055/src/bno055_device.cpp`
- Modify: `src/hardware/imu_bno055/src/main_node.cpp`
- Modify: `src/hardware/imu_bno055/config/bno055.yaml`
- Modify: `src/hardware/imu_bno055/launch/bno055.launch.py`
- Modify: `src/hardware/imu_bno055/test/test_package_contract.py`
- Modify: `src/hardware/imu_bno055/test/test_driver_faults.py`

**Step 1: Write the failing host contract test**

Require status reads for `CALIB_STAT`, `ST_RESULT`, `SYS_STATUS`, `SYS_ERR`, and temperature, structured health publication, and covariance parameters that default to unknown rather than three hard-coded `0.01` matrices.

**Step 2: Run tests to verify they fail**

Run: `python -m pytest src/hardware/imu_bno055/test/test_package_contract.py -q -p no:cacheprovider`

Expected: assertions fail on missing health-register and covariance contracts.

**Step 3: Write minimal implementation**

Add a bounded `Health` register snapshot, publish its fields in `sensors/imu/status`, and make the three covariance diagonals explicit parameters. Use ROS unknown-covariance conventions when no measured covariance is configured. Do not reinterpret BNO `CALIB_STAT=3` as robot calibration success.

**Step 4: Run host tests and retain ARM64 HOLD**

Run: `python -m pytest src/hardware/imu_bno055/test/test_package_contract.py src/hardware/imu_bno055/test/test_driver_faults.py -q -p no:cacheprovider`

Expected: package tests pass; injected driver tests skip unless `BNO055_TEST_EXECUTABLE` is provided. Record that C++ build/live-chip acceptance remains DEVICE HOLD.

### Task 5: Documentation, harness, and regression verification

**Files:**
- Modify: `src/core/control/logs.md`
- Modify: `src/core/control/progress.md`
- Modify: `src/hardware/imu_bno055/logs.md`
- Modify: `src/hardware/imu_bno055/progress.md`
- Modify: `docs/logs.md`

**Step 1: Record exact evidence boundaries**

Document source/local verification separately from ROS-SIM, ARM64 artifact, Device, physical stopping, and FIELD acceptance. State explicitly that no higher speed is active.

**Step 2: Run focused and package suites**

Run the new focused tests, existing calibration/profile/space-speed tests, the full Control suite, core safety/policy tests, and the IMU package contracts.

**Step 3: Regenerate and lint the harness**

Run: `python tools/harness/rosy_harness.py generate`

Run: `python tools/harness/rosy_harness.py lint`

**Step 4: Inspect the final diff**

Run: `git diff --check` and `git status --short`. Verify that unrelated map-v2 worktree changes remain untouched and only explicit auto-calibration paths are staged if a commit is requested.

## Execution record (2026-09-20)

- Tasks 1-4 implemented test-first. Focused Control: `37 passed`; CORE: `895 passed, 11 skipped`; IMU host: `4 passed, 10 skipped`.
- Full Control: `1018 passed, 26 skipped, 2 failed`; both failures are the unchanged startup-profile fixture omitting the already-required `web_port` launch value.
- Harness generation passed. Harness lint is still blocked only by four pre-existing malformed headings in `docs/logs.md` plus stale-verification warnings.
- `git diff --check` passed. Existing map-v2 simulator changes and probe files remain untouched.
- No higher speed is active. ARM64 build, live BNO055, measured stop-envelope collection, ROS-SIM, Device, complete-map traversal, supervision, and FIELD acceptance remain explicit HOLDs.
