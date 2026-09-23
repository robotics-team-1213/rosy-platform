# Pinky Connection Evidence Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the existing Windows peer verifier emit bounded, machine-readable pre-G0 connection evidence without changing robot state.

**Architecture:** Add optional evidence, batch-mode, timeout, and API-port parameters to the existing PowerShell verifier. Keep exact-host verification and use injected fake SSH plus a loopback HTTP server for real process-level tests.

**Tech Stack:** PowerShell 5+, Python 3, pytest, standard-library HTTP server and subprocess.

---

### Task 1: Successful evidence record

**Files:**
- Modify: `deploy/robot/verify/verify-from-windows.ps1`
- Create: `test/test_windows_connection_evidence.py`

1. Write a failing process-level test that supplies fake route/address SSH output and two HTTP 200 responses.
2. Run the focused test and confirm the missing parameters or evidence file causes RED.
3. Add validated optional parameters, bounded SSH arguments, check records, and atomic JSON output.
4. Run the focused test and confirm GO.

### Task 2: Failure and preservation contract

**Files:**
- Modify: `deploy/robot/verify/verify-from-windows.ps1`
- Modify: `test/test_windows_connection_evidence.py`

1. Write failing tests for SSH failure producing HOLD evidence and an existing evidence path being preserved.
2. Run them and confirm RED for the expected missing behavior.
3. Add stable failure codes and no-overwrite publication.
4. Run the focused tests and existing Wi-Fi/commissioning suites.

### Task 3: Operator handoff and integration

**Files:**
- Modify: `docs/deployment/pinky-pro-first-device-runbook.md`
- Modify: `deploy/robot/AGENTS.md`

1. Add the exact pre-G0 command and state that GO proves connectivity only.
2. Run PowerShell syntax, focused tests, full root tests, and `git diff --check`.
3. Commit the implementation, record verification, and fast-forward local `main` only after all checks pass.
