# Camera Ground Homography Tuning Implementation Plan
> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
**Goal:** Add an optional, tunable, fail-closed camera ground homography whose status and session enable switch are visible in the dashboard.
**Architecture:** Keep image-to-ground validation in a ROS-free sensing module. The camera node owns profile loading and activation; the web node only relays a bounded enable/disable command and renders the node verdict. Existing pinhole behavior remains the default.
**Tech Stack:** Python 3, ROS 2 Jazzy/rclpy, JSON, vanilla HTML/JavaScript, pytest
---

### Task 1: Define the pure calibration contract

**Files:**
- Create: `src/core/control/control/sensing/camera_homography.py`
- Test: `src/core/control/test/test_camera_homography.py`

1. Write failing tests for approximate profiles, recomputed residuals, independent validation, image-contract mismatch, bottom-centre range, singularities, and board-relative lateral coordinates.
2. Run the focused test and confirm the missing module/API failure.
3. Implement the smallest pure evaluator and ground model that pass the tests.
4. Re-run the focused test.

### Task 2: Wire the camera node and tunable parameters

**Files:**
- Modify: `src/core/control/control/camera_detect_node.py`
- Modify: `src/core/control/config/camera.yaml`
- Test: `src/core/control/test/test_camera_homography_wiring.py`

1. Write failing source-contract tests for parameters, transient status, command topic, and default pinhole behavior.
2. Add bounded thresholds, profile loading, latched status publication, and session enable/disable commands.
3. Re-run focused tests.

### Task 3: Add dashboard status and switch

**Files:**
- Modify: `src/core/control/control/web_node.py`
- Modify: `src/core/control/web/dashboard.html`
- Test: `src/core/control/test/test_camera_homography_wiring.py`

1. Extend failing tests for the web relay and read-only checks.
2. Subscribe to the camera calibration status and expose only `enable`/`disable` POST commands.
3. Render eligibility, active state, checks, errors, validation range, and thresholds.
4. Re-run focused tests.

### Task 4: Document and verify

**Files:**
- Modify: `src/core/control/docs/camera-ground-calibration.md`
- Modify: `src/core/control/logs.md`
- Modify: `src/core/control/progress.md`

1. Document ChArUco capture, intrinsic calibration, fixed-mount ground validation, schema, and operator workflow.
2. Run focused camera tests, wider Control tests, and the repository harness generate/lint commands.
3. Record host-test evidence separately from physical Pinky Pro validation, which remains HOLD until real captures and measured distances are supplied.
