# Source Folder Roles and Runtime Ownership Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the current source tree and its operator/agent maps describe the same ownership boundaries, and define evidence required before adding or moving source roots.

**Architecture:** Keep the D-310 source layout and existing ROS package names. Clarify that `products/` classifies model-specific source, `runtime/` contains current robot-side runtime code, `site/` contains site services, and `deploy/` determines host/image closure; none alone establishes final command authority or physical acceptance. Audit mixed packages before deciding any further move.

**Tech Stack:** ROS 2 Jazzy/colcon package inventory, Markdown ADRs and plans, repository harness generation/lint, PowerShell and Git worktrees.

---

## Status and scope

**Decision:** [D-315](../adr/D-315-source-folder-responsibility-and-runtime-authority.md) accepts the current role meanings and new-root criteria. This plan synchronizes the source maps and preserves implementation/package names.

**Completed on 2026-09-28:** Current `package.xml` locations, selected deployment consumers, UI/video service ownership, and old source-root residue were inspected. This pass does not restructure ROS packages, change APIs, alter deploy files, or clean ignored local state.

**Deferred:** A possible split or rename of `runtime/sensing` is not required to resolve the documentation drift. The ROS package is named `control` and includes sensing, calibration, planning, safety, proposal, and diagnostic paths. A separate source and consumer audit must precede any move.

## Current source map

```text
src/
├─ contracts/{foundation,interfaces}/
├─ runtime/{gateway,services,events,api_web,navigation,sensing}/
├─ products/
│  ├─ pinky_pro/{profile,bringup,adc,lamp,led}/
│  └─ omx/{profile,adapter}/
├─ drivers/imu_bno055/
├─ site/{fleet,overhead,games}/
├─ hmi/{dashboard,face,web}/
└─ sim/{description,gz_sim}/
```

Package names remain the names in each `package.xml`: for example, `runtime/gateway` is `core`, `runtime/sensing` is `control`, `hmi/web` is `web_common`, and `site/overhead` is `overhead`.

## Task 1: Establish source and deployment roles

**Files:** `src/**/package.xml`, `deploy/robot/Dockerfile`, `deploy/site/compose.yaml`, `src/runtime/sensing/AGENTS.md`, D-275, D-305 and D-310.

1. List each tracked ROS package path and declared package name. Distinguish path, ROS package, process, physical robot identity and image/host consumer.
2. Trace CORE dashboard serving, Fleet console serving, Overhead frame processing, and their distinct input/output boundaries. Record that a browser workstation is not automatically the server host.
3. Trace `runtime/sensing` launch and package references. Record `cmd_vel_raw` proposal paths separately from CORE's final `cmd_vel` owner. Keep old package names and paths until this audit shows an independently testable/installable boundary.
4. Treat ignored `.omc` and Python cache directories below retired source paths as local residue. Do not clean or stage them as source.

**Exit:** A reader can tell where code is grouped, what process owns behavior, where deployment is selected, and which evidence remains unproven.

**Result:** Completed for the current reviewed tree. Source mapping is summarized in D-315 and this plan.

## Task 2: Record the folder interpretation rule

**Files:** `docs/adr/D-315-source-folder-responsibility-and-runtime-authority.md`, `docs/reference/ROSY ADR Log.md`, `docs/progress.md`.

1. State the folder roles without claiming all `runtime/` code is reusable or all `products/` code owns final commands.
2. Set the gate: a new root or move needs a real source owner plus consumer/build/test/deploy evidence and a migration of live path references.
3. Preserve D-310, D-305, D-275 and existing package identity. Make no empty `devices`, `device_control` or `controllers/<model>` scaffolding.
4. Add the ADR to the log and docs progress; regenerate generated indexes rather than editing them by hand.

**Exit:** Accepted decision covers taxonomy only; no command owner, artifact or device gate is promoted.

**Result:** Completed. D-315 is Accepted within that scope.

## Task 3: Synchronize reader-facing structure maps

**Files:** `README.md`, `AGENTS.md`, `src/AGENTS.md`, `src/site/AGENTS.md`, `src/hmi/AGENTS.md`, `docs/plans/AGENTS.md`.

1. Replace the retired `src/devices/` tree in `README.md` with the current roots and current children, including `site/overhead` and `hmi/dashboard`.
2. Update root and `src/` guidance to name the source roots, package-name distinction, current CORE writer, and deployment-vs-source rule.
3. Update `src/site/AGENTS.md` for `fleet`, `overhead`, and `games`; keep ROS-free claims scoped to the packages whose manifests/code establish them.
4. Update `src/hmi/AGENTS.md` for the CORE-served dashboard, LCD package, and shared `web_common` assets. State physical directory names separately from ROS package names.
5. Add this plan to the plans map. Do not rewrite dated historical evidence or old ADR context as if it described current paths.

**Exit:** `rg` and a direct read show no current map pointing to removed `src/devices/` or omitting present top-level source areas.

**Result:** Completed.

## Task 4: Check documentation generation and consistency

**Files:** `docs/index.md`, `docs/logs.md`, updated source maps.

1. Append one dated work-log entry and update docs progress only for the D-315 documentation gate.
2. Run `python tools/harness/rosy_harness.py generate` and `python tools/harness/rosy_harness.py lint` from the repository root.
3. Run the focused ADR/harness contract tests listed in `docs/AGENTS.md`; report pre-existing failures separately.
4. Review `git diff --check`, generated index drift, and changed-path scope before commit.

**Exit:** D-315 and its plan are discoverable; generated indexes are fresh; documentation checks report their actual result.

**Result:** Harness generate completed and refreshed docs/index.md. Focused tests: 73 passed, 3 failed in dashboard progress.md and logs.md contract data on the base commit (invalid last_verified date, missing HOLD blocker, missing evidence bullet); test_network_topology_contracts.py passes within the run. Harness lint reports those same 3 errors plus 19 existing stale-metadata warnings. The new D-315 paths and links are present in the generated index.

## Follow-up gate: decide whether `runtime/sensing` should split

Do not execute this as an implied part of D-315. Open a separate plan only if the audit establishes distinct owners and at least one real boundary in process launch, independent tests, package dependencies, installation closure, or deployment lifecycle. That plan must enumerate imports, launch files, entry points, topic writers, image consumers, and rollback paths. Preserve `control` ROS package name unless an API migration is separately justified. CORE remains the final Pinky `cmd_vel` writer.

## Rollback

This pass changes documentation only. Revert the scoped documentation commit if the source map becomes inaccurate; do not reset shared `main` or delete ignored local tool/cache state.
