---
title: Multi-arm record-config classification must use profile hash binding before instance_id lookup
date: 2026-11-23
category: logic-errors
module: deploy/robot/omx/bench_record_inspect.py
modules: [deploy]
problem_type: logic_error
component: bench_record
severity: high
symptoms:
  - "record-config-arm-a.json showed false camera_issues: top(arm_s_top): 비활성 카메라 and side: 장치 없음(/dev/v4l/by-id/rosy-arm_a_jieli)"
  - "Browser Teleop Prepare and Record buttons were disabled on Arm A even though Arm A follower, leader, and cameras were ready"
root_cause: shared_identifier_collision
resolution_type: code_fix
tags: [omx, bench_record, camera_roles, arm_a, arm_s, instance_id, ui]
applies_when:
  - "When multiple physical OMX arms share the same LeRobot robot.id / instance_id (e.g. omx_follower_arm)"
  - "When bench_record_inspect maps record-config*.json files back to an arm for camera registry validation"
---

# Multi-arm record-config classification must use profile hash binding before instance_id lookup

## Problem

On `rosy-arm-cell`, both `arm-a-robot-profile.json` and `arm-s-robot-profile.json` bind to `instance_id == "omx_follower_arm"`, while their USB serial ports (`robot_config_sha256`) identify the distinct physical arms.

`BenchInspectMixin.choices()` inverted `instances` via `{v: k for k, v in instances.items()}` in `ARMS` iteration order (`arm_a`, `arm_b`, `arm_s`), causing `inv_inst["omx_follower_arm"]` to overwrite `"arm_a"` with `"arm_s"`. Every `record-config-arm-a.json` was therefore passed to `inspect_config_cameras(cfg_j, "arm_s", reg)`, which checked `arm_s_top` (disabled in `omx-cameras.json`), failed to rebind `side`, falsely tried to rebind `arm_a_wrist` to `rosy-arm_s_wrist`, and disabled all start/prepare buttons in the web UI.

## Root cause

Inverting `arm -> instance_id` drops collisions whenever two profiles share an `instance_id`. Meanwhile, `self._arm_binding(arm, configs, ...)` already validates each config against every arm's signed `robot_config_sha256` (which hashes the unique USB port and camera map), producing an authoritative 1:1 ownership map (`cfg_owner`).

## Solution

1. Extract `resolve_config_arm(name, robot, cfg_owner, inv_inst)` in `deploy/robot/omx/bench_record_guard.py`.
2. Compute `arm_bindings` before inspecting `config_meta`, build `cfg_owner = {c: a for a in ARMS for c in arm_bindings[a]["configs"]}`, and pass `cfg_owner` into `resolve_config_arm` so signed profile ownership wins first, filename (`arm-a` / `arm-b` / `arm-s`) wins second, and `inv_inst` is only a legacy fallback.
