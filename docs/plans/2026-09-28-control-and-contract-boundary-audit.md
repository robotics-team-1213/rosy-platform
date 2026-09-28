# Control and Shared Contract Boundary Audit Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Verify which source modules have independent owners, consumers, and build or installation boundaries before moving or splitting `runtime/sensing` or `core_common`.

**Architecture:** Preserve D-310's current source paths and ROS package names. Map each `control` responsibility and each `core_common` module to its producer, consumer, execution authority, tests, and image closure. Recommend a narrow move only when a real ownership and independent verification boundary is demonstrated.

**Tech Stack:** ROS 2 Jazzy and colcon manifests, Python imports and entry points, launch files, deployment Dockerfiles and package manifests, Markdown ADR/harness.

---

## Decision and scope

**Decision:** D-317 keeps the current tree while establishing criteria for a later, narrow source/package decision. This plan performs source and documentation auditing only. It does not change ROS package names, APIs, writers, launch behavior, Docker closure, or device configuration.

**Audited in this pass:** `runtime/sensing/package.xml` defines the `control` package. Its setup declares 15 console scripts and one `rosy.sensor_provider` entry point. Its contents include sensing, calibration, planning, safety, diagnostics, tools, and a legacy `web_node`; the package also depends on `web_common`, Nav2, and SLAM components. CORE remains the Pinky final `cmd_vel` writer. The standalone legacy safety launch must not run beside CORE.

`contracts/foundation/core_common` contains `domain/`, `protocol/`, and root modules including `intent`, `succession`, configuration, identity, and profile. Fleet and CORE both use `intent` and `succession` rules; Overhead produces `SiteSightingPayload` consumed by Fleet. Other protocol modules have their own producer/consumer paths. These uses do not establish one universal Action schema or an independently distributable package.

| Module or path | Observed production use | Meaning for placement |
|---|---|---|
| `core_common.protocol.schemas` | CORE API/events and Fleet hub/task paths | Typed CORE↔Fleet values; keep separate from site-only records by contract meaning |
| `core_common.intent` | CORE `/do` and Fleet `/do` routes | Shared fixed grammar/route selection; it does not execute or own physical actions |
| `core_common.succession` | CORE swarm manager and Fleet console | Shared algorithm used on each side; no new server or control process implied |
| `core_common.protocol.sightings` | Overhead publishes `SiteSightingPayload`; Fleet receives it | Site observation contract, distinct from robot↔Fleet envelopes |
| `core_common.protocol.vision_preview` | Overhead ingest and Fleet preview lease paths | Preview authorization/data freshness contract, not Fleet ownership of camera bytes |
| `core_common.config`, `identity`, `profile`, `domain` | CORE runtime/API and product configuration paths | Mostly device-local runtime behavior; package co-location does not make it a Fleet API |

The `fleet` manifest had a stale comment claiming its production code used only `core_common.protocol.schemas`; the source imports also use the listed intent, succession, sightings, and preview modules. This pass corrects that comment without changing the dependency or runtime behavior.

| Build/deployment surface | Observed closure | What remains unproven |
|---|---|---|
| CORE stage in `deploy/robot/Dockerfile` | `core`, `core_common`, services/events/API, HMI assets, interfaces, Pinky profile | Does not install `control`; this stage is not a full signed/native product payload proof |
| IO stage in `deploy/robot/Dockerfile` | Pinky bringup/navigation, OMX adapter/profile, `control`, `web_common` | Why OMX adapter is mandatory for every Pinky product image; exact native ARM64/Jazzy payload equivalence |
| `deploy/image/required-ros-packages.txt` | Lists both `control` and `omx_adapter` among mandatory product packages | Actual target installation/readback and whether every role needs each package |
| `deploy/site/compose.yaml` | Fleet and Overhead Vision are distinct site services | Production site host resource/fault acceptance |
| `deploy/omx/compose.yaml` | Development hardware shell and simulation profiles | Accepted operational OMX owner/runtime or workcell deployment |

**Not established:** Independent `control` package lifecycles, complete native ARM64/Jazzy image closure parity, OMX operational ownership, physical stop/readback, or field acceptance.

## Task 1: Maintain the source and package inventory

**Files:** `src/AGENTS.md`, `src/runtime/sensing/package.xml`, `src/runtime/sensing/setup.py`, `src/contracts/foundation/package.xml`, `src/site/fleet/package.xml`, module `package.xml` files.

1. Record every package's filesystem path separately from ROS package name, process, robot/workcell identity, and installed image.
2. For `control`, enumerate console entry points, `rosy.sensor_provider`, launch files, imports, ROS publishers/subscribers/services, and test ownership. **Initial result:** 15 console scripts plus one sensor-provider entry point; the package spans observers, calibration, planning, safety, diagnostics, and legacy UI.
3. Preserve the writer map: CORE owns Pinky's final `cmd_vel`; legacy `safety_node` may publish only in its standalone profile and must not run with CORE.

**Exit:** The map identifies all current entry points and active/legacy writer profiles without calling `runtime/sensing` a sensor-only package.

## Task 2: Map `core_common` module contracts

**Files:** `src/contracts/foundation/core_common/**`, `src/runtime/**`, `src/site/**`, `src/hmi/**`, API reference and package manifests.

1. Build a table with one row per module family: producer, direct consumers, serialized boundary, tests, deployment consumer, and ownership.
2. Distinguish `protocol.schemas` and device-facing envelopes from site-specific task/sighting status, shared `intent`/`succession` rules, and local CORE config/profile/identity helpers.
3. Verify actual source imports and runtime/package manifests; test-only references do not count as production consumers.
4. Do not extract code or change API schemas in this audit. Identify any third real consumer as a review trigger, not an automatic package split.

**Exit:** A reviewer can tell which exact values cross CORE/Fleet/Overhead boundaries and which are internal helper rules. **Initial result:** the consumer rows above identify distinct wire/site/helper meanings; exact serial schema, API version, and compatibility ownership remain to be checked before any package extraction.

## Task 3: Compare install and test boundaries

**Files:** `deploy/robot/Dockerfile`, `deploy/image/required-ros-packages.txt`, `deploy/image/build-native-payload.sh`, package tests, `tools/harness/rosy_harness.py`.

1. Compare CORE, IO, site, and OMX development package closures by actual copy/build/install rules.
2. Trace whether `control` entry points and debug-only `web_node` files are installed, launched, and required by each artifact; do not equate launch exclusion with package exclusion.
3. Identify which existing host tests can be run without ROS and which package/build checks need Linux/Jazzy.
4. Leave native ARM64 payload, signature/digest, installation/readback, and DEVICE/FIELD rows `NOT_RUN` until actually exercised.

**Exit:** Package inclusion/removal candidates cite the Docker/native manifest and at least one install or readback source; no folder move is approved by directory shape alone.

## Task 4: Decide whether a later move is justified

1. If no separate source owner plus independent build/test/install/run boundary is found, record **keep current paths** and leave candidates deferred.
2. If evidence supports a split, write a separate ADR and migration plan naming exact files, package dependencies, import/launch consumers, tests, images, compatibility and rollback.
3. Preserve ROS package names unless a separately reviewed API migration justifies a rename.
4. Review the device-local interpreter location per product. Keep Fleet's Mission/Step ledger, CORE's Pinky writer, and any future OMX/drone writer distinct.

**Exit:** Any move request has an evidence-backed package closure and rollback; absent that evidence, no source changes occur.

## Task 5: Keep architecture maps current

**Files:** `docs/plans/2026-09-27-rosy-platform-role-and-contract-implementation-plan.md`, this plan, `docs/adr/D-317-control-and-shared-contract-source-boundaries.md`.

1. Replace the stale `src/devices/`/`products=config only` sketch in the active platform plan with the D-310 tree.
2. Update the P0 text: D-316 now implements Pinky `attempt_id` to CORE terminal event correlation at SOURCE/LOCAL; ROS-SIM, artifact, device/stop readback, and field gates remain open.
3. Keep source layout, control authority, browser/service host, video ownership, and deployable image closure as separate axes.

**Exit:** Current plans agree with tracked paths and no historical baseline is presented as current status.

## Task 6: Verify and record

1. Run `python tools/harness/rosy_harness.py generate` and inspect generated index diffs.
2. Run `python tools/harness/rosy_harness.py lint` and focused ADR/harness contract tests. Report pre-existing dashboard-log failures without rewriting unrelated logs.
3. Run `git diff --check`; verify that only scoped ADR, plan, ADR log, progress, work log, and generated index paths changed.
4. Commit the reviewed document set as one unit and integrate it into local `main` without staging unrelated work.

**Exit:** D-317 is indexed and source evidence is linked. Documentation SOURCE/LOCAL results remain distinct from ROS-SIM, ARTIFACT, DEVICE, physical stop, and FIELD acceptance.

## Rollback

The decision and audit are documentation-only. Revert only the scoped documentation commit if its source map becomes inaccurate. Do not reset `main`, remove unrelated worktrees, or change ignored/device state.
