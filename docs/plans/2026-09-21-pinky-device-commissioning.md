# Pinky Pro Device Commissioning Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a fail-closed, resumable G0-G5 commissioning evidence session that is ready before the physical Pinky Pro is connected.

**Architecture:** A ROS-free Python state machine validates immutable, ordered evidence records. A thin cross-platform CLI creates sessions, records one gate at a time, reports the next legal action, and prints the exact SSH/local-console checklist without automatically moving hardware.

**Tech Stack:** Python 3.12 standard library, JSON, SHA-256, argparse, pytest, existing Rosy deploy/readback scripts.

---

### Task 1: Commissioning session state machine

**Files:**
- Create: `deploy/robot/commissioning_session.py`
- Create: `test/test_pinky_commissioning.py`

**Step 1: Write the failing tests**

Add tests for session initialization, fixed source/robot identity, G0-G5 order,
skip refusal, overwrite refusal, and canonical round-trip validation.

**Step 2: Run test to verify it fails**

Run: `python -m pytest test/test_pinky_commissioning.py -q`
Expected: collection failure because `commissioning_session.py` does not exist.

**Step 3: Write minimal implementation**

Implement `new_session`, `validate_session`, `next_gate`, and `record_gate` with
finite JSON, RFC3339 UTC timestamps, strict keys, and defensive copies.

**Step 4: Run test to verify it passes**

Run: `python -m pytest test/test_pinky_commissioning.py -q`
Expected: state/order tests pass.

### Task 2: Gate-specific fail-closed validators

**Files:**
- Modify: `deploy/robot/commissioning_session.py`
- Modify: `test/test_pinky_commissioning.py`

**Step 1: Write failing gate tests**

Cover G0 signed ARM64 identity, G1 derived DDS identity/core mode, G2 readback
digest match, G3 E-stop+zero+single publisher, G4 physical acknowledgements and
deadman trials, and G5 LiDAR/map/goal/final-zero fields.

**Step 2: Run RED**

Run: `python -m pytest test/test_pinky_commissioning.py -q`
Expected: validator tests fail because gate bodies are not implemented.

**Step 3: Implement minimal validators**

Reject extra/missing keys, booleans passed as numbers, non-finite values, identity
drift, unverified signatures, nonzero G3/G5 velocity, missing acknowledgements,
and empty evidence digest lists.

**Step 4: Run GREEN**

Run: `python -m pytest test/test_pinky_commissioning.py -q`
Expected: all gate tests pass.

### Task 3: Cross-platform CLI and evidence hashing

**Files:**
- Create: `deploy/robot/commission-pinky.py`
- Modify: `test/test_pinky_commissioning.py`
- Modify: `deploy/robot/install-pi.sh`

**Step 1: Write failing CLI tests**

Test `init`, `status`, `record`, `checklist`, atomic replacement, SHA-256 binding,
and failure-without-mutation. Assert installer copies both Python files executable.

**Step 2: Run RED**

Run: `python -m pytest test/test_pinky_commissioning.py -q`
Expected: CLI and install contract failures.

**Step 3: Implement minimal CLI**

Use argparse, `Path.replace` from a sibling temporary file, and explicit JSON
input/evidence file arguments. Never accept or execute a shell command.

**Step 4: Run GREEN**

Run: `python -m pytest test/test_pinky_commissioning.py -q`
Expected: CLI tests pass.

### Task 4: Tomorrow operator bundle

**Files:**
- Create: `docs/deployment/pinky-pro-first-device-runbook.md`
- Modify: `docs/deployment/AGENTS.md`
- Modify: `docs/deployment/raspberry-pi-runtime.md`
- Modify: `deploy/robot/AGENTS.md`
- Modify: `test/test_pinky_commissioning.py`

**Step 1: Write failing documentation contract tests**

Assert both SSH and console paths, G0-G5 commands, E-stop/down recovery, no copied
Gazebo measurements, camera/geometry/motion HOLD language, and evidence paths.

**Step 2: Run RED**

Run: `python -m pytest test/test_pinky_commissioning.py -q`
Expected: runbook contract fails because the document is absent.

**Step 3: Write the runbook**

Include pre-power checklist, exact commands, result templates, stop conditions,
network fallback, camera/ArUco/homography measurements, and end-of-day backup.

**Step 4: Run GREEN**

Run: `python -m pytest test/test_pinky_commissioning.py -q`
Expected: runbook contracts pass.

### Task 4a: Align verification with wired commissioning LAN

**Files:**
- Modify: `deploy/robot/verify/verify-pi.sh`
- Modify: `deploy/robot/verify/verify-from-windows.ps1`
- Modify: `test/test_pi_wifi_deployment.py`

Add `auto`/explicit interface selection while preserving Wi-Fi diagnostics when
a wireless interface is selected. Reject unsafe names and loopback. Verify the
API/dashboard from Windows over the exact selected interface.

### Task 5: Harness records and verification

**Files:**
- Modify: `deploy/logs.md`
- Modify: `deploy/progress.md`
- Generated: `deploy/index.md`, `STATUS.md`

**Step 1: Append the verified change record**

Record software readiness without promoting ARTIFACT/DEVICE/FIELD.

**Step 2: Generate and lint harness**

Run: `python tools/harness/rosy_harness.py generate`
Run: `python tools/harness/rosy_harness.py lint`
Expected: zero errors.

**Step 3: Run focused and full tests**

Run: `python -m pytest test/test_pinky_commissioning.py test/test_device_readback.py test/test_pi_wifi_deployment.py test/test_robot_runtime.py test/test_release_boundary_guards.py -q`
Run: `python -m pytest test -q`
Expected: zero failures.

**Step 4: Verify syntax and diff**

Run: `python -m py_compile deploy/robot/commissioning_session.py deploy/robot/commission-pinky.py`
Run: `git diff --check`
Expected: clean.
