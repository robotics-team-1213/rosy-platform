# D-283 Console Action Groups Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement D-283 action groups in the CORE console while retaining its three-region desktop layout, always-visible E-stop, capability truth, and mobile scrolling behavior.

**Architecture:** Extend the existing `panels.yaml` registry with optional console action-group metadata and expose it in the surface manifest. The shell will create accessible tabs only for groups present in that manifest, default to `운전`, and preserve selection only for the current page lifetime. Before leaving a mounted group, panel lifecycle hooks must confirm safe departure: teleop terminal zero, line-follow `OFF`, and docking outside `DOCKING`/`UNDOCKING`. Missing status or failed stop retains the group. Desktop CSS will allocate bounded sense, observe, and act regions; mobile remains a vertical scroll stack.

**Tech Stack:** FastAPI/Pydantic, vanilla ES modules, CSS, pytest, Playwright Chromium.

---

## Task 1: Lock the registry and manifest contract — complete

**Files:** `src/runtime/api_web/core_api_web/api/ui_registry.py`, `src/runtime/api_web/core_api_web/api/ui_manifest.py`, `src/contracts/foundation/core_common/protocol/schemas.py`, and matching `src/runtime/api_web/test` modules.

Add a validated optional action-group identifier to panel registry records and surface descriptors; verify group metadata is included in revisions and unavailable capabilities omit their panels/groups.

## Task 2: Implement accessible action-group selection and safe switching — complete

**Files:** `src/hmi/dashboard/shell/mount.js`, `src/hmi/dashboard/shell/shell.js`, `src/hmi/dashboard/panels/console/teleop.js`, `src/hmi/dashboard/panels.yaml`, `src/hmi/dashboard/test`.

Group `mode` and `teleop` under `drive`, `docking` under `docking`, and `line_follow` under `line_follow`. Capability-filter docking and line-follow. Render only present groups, select drive by default, and gate departures on teleop zero, line-follow OFF, and terminal docking status. Test keyboard/tab semantics, missing groups, operation blockers, terminal zero ordering, no resumed commands, and viewer access. Manifest replacement and auth loss must also preserve the visible group when safety confirmation fails.

## Task 3: Fit the three regions at the declared desktop viewport — complete

**Files:** `src/hmi/dashboard/shell/shell.css`, `src/hmi/dashboard/test/test_surface_layout_browser.py`, and `test/test_dashboard_browser.py` where actual CORE route evidence fits existing fixtures.

At 1366×768, keep the body at zero scroll, sense internally scrollable, observe and active action content visible without clipping, and E-stop visible. At 390×844, retain the vertical scroll stack, zero horizontal overflow, and visible E-stop.

## Task 4: Record evidence and update dashboard state — complete

Append the dashboard work log, update progress only for demonstrated gates, regenerate harness indexes, and run dashboard/API tests, browser verification, harness lint, and `git diff --check`. Do not claim ROS-SIM, device, or field acceptance.

**Verification:** dashboard/API/gateway related suite 116 passed, 2 skipped; foundation suite 50 passed; `git diff --check` passed. Four FastAPI+CoreServices browser captures cover administrator/operator at 1366×768 and 390×844. Harness generation completed. Harness lint reports one pre-existing error in committed `deploy/logs.md` (the 2026-09-26 Pinky Pro OV5647 entry lacks the required `- 증거:` marker); that append-only deployment log was not changed for D-283. The remaining harness findings are warnings.
