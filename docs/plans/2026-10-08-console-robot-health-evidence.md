# Console Robot Health Evidence Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Show each Pinky's current charging and battery evidence, safety stop, and useful next action in the Fleet Console without granting Fleet device administrator powers.

**Architecture:** CORE remains the source of `GET /api/v1/power/health` and the safety decision. Fleet reads that existing Viewer endpoint with its enrolled Operator token, caches each result for at most five seconds, and adds an optional read-only projection to `GET /api/fleet/state`. The roster treats missing, old, or malformed evidence as unknown. Video freshness and robot network settings retain their existing owners.

**Tech Stack:** Python asyncio/httpx/FastAPI/Pydantic; vanilla JavaScript ES modules; pytest and Node test runner.

---

### Task 1: Correct D-509 and freeze the narrow contract

**Files:** `docs/adr/D-509-console-robot-health-and-settings-boundary.md`; `docs/reference/ROSY ADR Log.md`; `docs/reference/ROSY API & Protocol Reference.md`.

1. Correct the ADR: `/power/health` gives confirmation and policy evidence but no charging sensor source; current runtime constructs an instrumented DockingConfig and D-350 Phase 1 is not proven active. A Vision preview proves arriving frames, not whether transmission is enabled. Safety release stays Admin and explicit.
2. Specify optional Fleet row fields `power_health` (existing `PowerHealthResponse` or null) and `power_health_age_s` (nonnegative seconds or null). Offline, failed, old, and unsupported reads return null. This is display evidence only; no dispatch or safety decision may consume it.
3. Keep the ADR log title/status synchronized and add an API Reference history entry. Run `python tools/harness/rosy_harness.py lint`.

### Task 2: Add the bounded read-only Fleet read

**Files:** `operations/fleet/fleet/swarm/transport.py`; `operations/fleet/fleet/server/console_view.py`; `operations/fleet/fleet/server/console.py`; `operations/fleet/fleet/server/console_routes.py`; `operations/fleet/test/fakes.py`; `operations/fleet/test/test_transport.py`; `operations/fleet/test/test_server_console.py`.

1. Write focused failures for the authenticated GET, two robots with one health failure, five-second reuse/expiry, and no cached evidence when the robot is offline or replaced. Run the selected pytest tests and confirm failure.
2. Add `RobotClient.power_health()` and `HttpRobotClient.power_health()` using the existing `_get` and shared `PowerHealthResponse` validator. Reuse the bounded asynchronous presentation cache pattern already used for CAP-001, with a five-second TTL. Expose age from Fleet's monotonic clock and reset when a robot client changes.
3. Attach `power_health` and `power_health_age_s` to copies of Fleet state rows. An unavailable read cannot fail the state gather and never causes a POST. Run the selected pytest tests and `test/known_failures.py` on the captured output.

### Task 3: Render evidence and next action

**Files:** `operations/fleet/fleet/server/web/roster.js`; `operations/fleet/test/web/console-health.test.mjs` (or an existing matching test).

1. Write one focused Node test for confirmed fresh charging, unconfirmed, missing/stale/offline and an E-Stop that remains latched after a good battery sample.
2. Display percent only with fresh battery evidence and a fresh Fleet row. Display `충전 확인` only when both CORE charging confirmation and battery freshness hold. Show unknown and a concrete sensor/CORE or dock check otherwise; show battery warning and admin safety-state review without an auto-release action.
3. Use `diagnostics_summary` from the existing state as read-only context. Run `node --test operations/fleet/test/web/` and the relevant Fleet pytest checks.

### Task 4: Contract, documentation, and verification

**Files:** `docs/logs.md`; `operations/fleet/logs.md`; generated indexes, if the harness changes them.

1. Record source/local results and explicit DEVICE/FIELD pending gates. Do not claim D-350 Phase 1, active video transmitter settings, network reconfiguration, or a physical charging proof.
2. Run focused pytest to an `X:/DevTemp/console-health-8c2d41/run.txt` file, compare with `python test/known_failures.py`, run Node tests and harness generate/lint. Inspect exact changed paths and commit them on `feat/console-health-evidence`.
3. Leave branch unmerged and unpushed; landing and push require the user's separate instruction under the shared-checkout rule.
