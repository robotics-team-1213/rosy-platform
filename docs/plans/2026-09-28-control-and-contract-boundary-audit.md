# Control and Shared Contract Boundary Audit Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Verify which source modules have independent owners, consumers, and build or installation boundaries before moving or splitting `runtime/sensing` or `core_common`.

**Architecture:** Preserve D-310's current source paths and ROS package names. Map each `control` responsibility and each `core_common` module to its producer, consumer, execution authority, tests, and image closure. Recommend a narrow move only when a real ownership and independent verification boundary is demonstrated.

**Tech Stack:** ROS 2 Jazzy and colcon manifests, Python imports and entry points, launch files, deployment Dockerfiles and package manifests, Markdown ADR/harness.

---

## Decision and scope

**Decision:** D-317 keeps the current tree while establishing criteria for a later, narrow source/package decision. This plan performs source and documentation auditing only. It does not change ROS package names, APIs, writers, launch behavior, Docker closure, or device configuration.

**Current status (2026-09-28):** D-317 and the initial architecture-map update are integrated into local `main` at `edcf2818`. Tasks 1-4 remain the bounded source-boundary audit; the tables below are initial evidence, not a completed closure decision. Task 5 and the baseline integration in Task 6 are complete.

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
| IO stage in `deploy/robot/Dockerfile` | Explicitly selects `sllidar_ros2`, `interfaces`, `description`, `bringup`, `navigation`, `omx_adapter`, `omx`, `control`, and `web_common` | Why OMX adapter is in every IO image; exact native ARM64/Jazzy payload equivalence |
| Native payload builder in `deploy/image/build-native-payload.sh` | Runs `colcon build --base-paths src "$SLLIDAR_SRC"`; the current tree has 24 in-tree `package.xml` manifests plus the locked vendor package, including `fleet`, `overhead`, `games`, and `gz_sim`. `build_payload_release.py` copies the payload file set into the release | Whether site/simulation packages are intentionally shipped in a Pinky release; Linux/Jazzy discovery, native ARM64 build, signature, and target readback remain unproven |
| `deploy/image/required-ros-packages.txt` | Lists 13 mandatory in-tree packages; `verify-package-inventory.sh` checks these as a required subset, not as an allowlist | Which additional packages are built and included in the native install/release closure |
| `deploy/site/compose.yaml` | Fleet and Overhead Vision are distinct site services | Production site host resource/fault acceptance |
| `deploy/omx/compose.yaml` | Development hardware shell and simulation profiles | Accepted operational OMX owner/runtime or workcell deployment |

**Not established:** Independent `control` package lifecycles; whether the broad native source closure and Docker IO package selection are intentional; actual native ARM64/Jazzy build/payload equivalence; OMX operational ownership; physical stop/readback; or field acceptance.

## Task 1: Maintain the source and package inventory (open)

**Files:** `src/AGENTS.md`, `src/runtime/sensing/package.xml`, `src/runtime/sensing/setup.py`, `src/contracts/foundation/package.xml`, `src/site/fleet/package.xml`, module `package.xml` files.

1. Record filesystem path, ROS package name, process, robot/workcell identity, and installed image for `control`, `core_common`, their direct production consumers, and the deployment dependencies needed to trace their closure. Expand only when a specific dependency requires more context.
2. For `control`, enumerate console entry points, `rosy.sensor_provider`, launch files, imports, ROS publishers/subscribers/services, and test ownership. **Initial result:** 15 console scripts plus one sensor-provider entry point; the package spans observers, calibration, planning, safety, diagnostics, and legacy UI.
3. Record the evidence source for each claimed source owner and release/support responsibility. Use applicable ownership guidance or release/support records; package maintainer tags alone are contact metadata, not proof of an independent owner. Mark unsupported claims `unknown`.
4. Preserve the writer map: CORE owns Pinky's final `cmd_vel`; legacy `safety_node` may publish only in its standalone profile and must not run with CORE.

**Exit:** The map identifies all current entry points and active/legacy writer profiles without calling `runtime/sensing` a sensor-only package.

## Task 2: Map `core_common` module contracts (open)

**Files:** `src/contracts/foundation/core_common/**`, `src/runtime/**`, `src/site/**`, `src/hmi/**`, API reference and package manifests.

1. Build a table with one row per module family: producer, direct consumers, serialized boundary, tests, deployment consumer, and ownership.
2. Distinguish `protocol.schemas` and device-facing envelopes from site-specific task/sighting status, shared `intent`/`succession` rules, and local CORE config/profile/identity helpers.
3. Verify actual source imports and runtime/package manifests; test-only references do not count as production consumers.
4. Do not extract code or change API schemas in this audit. Identify any third real consumer as a review trigger, not an automatic package split.

**Exit:** A reviewer can tell which exact values cross CORE/Fleet/Overhead boundaries and which are internal helper rules. **Initial result:** the consumer rows above identify distinct wire/site/helper meanings; exact serial schema, API version, and compatibility ownership remain to be checked before any package extraction.

## Task 3: Compare install and test boundaries (open)

**Files:** `deploy/robot/Dockerfile`, `deploy/image/required-ros-packages.txt`, `deploy/image/build-native-payload.sh`, `deploy/image/verify-package-inventory.sh`, `deploy/release/build_payload_release.py`, package tests, `tools/harness/rosy_harness.py`.

1. Compare CORE, IO, native payload, site, and OMX development package closures by actual copy/build/install rules. The native builder runs `colcon build --base-paths src "$SLLIDAR_SRC"`; record its 24 in-tree package manifests plus vendor, compare them with Docker selections, and determine whether the site/simulation packages are intended in a Pinky release. Treat the manifest count as static evidence until Linux/Jazzy `colcon list` confirms discovery. The required list is a minimum subset, not an exclusion list.
2. Trace whether `control` entry points and debug-only `web_node` files are installed, launched, and required by each artifact; do not equate launch exclusion with package exclusion.
3. Identify which existing host tests can be run without ROS and which package/build checks need Linux/Jazzy.
4. Keep static source/package-set comparisons distinct from native ARM64 build, signature/digest, target installation/readback, and DEVICE/FIELD evidence. Mark the latter `NOT_RUN` until exercised.

**Exit:** Each inclusion/removal candidate cites the Docker/native manifest and repository source showing its copy/build/install path. This source-level exit does not require target-device readback; native ARM64 build, signature/digest, installation/readback, and DEVICE/FIELD remain separate gates. No folder move is approved by directory shape alone.

## Task 4: Decide whether a later move is justified (open)

1. If no separate source owner plus independent build/test/install/run boundary is found, record **keep current paths** and leave candidates deferred.
2. If evidence supports a split, write a separate ADR and migration plan naming exact files, package dependencies, import/launch consumers, tests, images, compatibility and rollback.
3. Preserve ROS package names unless a separately reviewed API migration justifies a rename.
4. Review the device-local interpreter location per product. Keep Fleet's Mission/Step ledger, CORE's Pinky writer, and any future OMX/drone writer distinct.

**Exit:** Any move request has an evidence-backed package closure and rollback; absent that evidence, no source changes occur.

## Task 5: Keep architecture maps current (complete in `edcf2818`)

**Files:** `docs/plans/2026-09-27-rosy-platform-role-and-contract-implementation-plan.md`, this plan, `docs/adr/D-317-control-and-shared-contract-source-boundaries.md`.

1. Replace the stale `src/devices/`/`products=config only` sketch in the active platform plan with the D-310 tree.
2. Update the P0 text: D-316 now implements Pinky `attempt_id` to CORE terminal event correlation at SOURCE/LOCAL; ROS-SIM, artifact, device/stop readback, and field gates remain open.
3. Keep source layout, control authority, browser/service host, video ownership, and deployable image closure as separate axes.

**Exit:** Current plans agree with tracked paths and no historical baseline is presented as current status.

## Task 6: Verify and record (baseline integration complete in `edcf2818`)

1. Run `python tools/harness/rosy_harness.py generate` and inspect generated index diffs.
2. Run `python tools/harness/rosy_harness.py lint` and focused ADR/harness contract tests. Record exact current results and warnings; do not rewrite unrelated module logs to hide failures.
3. Run `git diff --check`; verify that only scoped ADR, plan, ADR log, progress, work log, and generated index paths changed.
4. The initial D-317 document set was committed and integrated into local `main` as `edcf2818`; follow-up audit findings require their own scoped review and commit.

**Exit:** D-317 is indexed and source evidence is linked. Documentation SOURCE/LOCAL results remain distinct from ROS-SIM, ARTIFACT, DEVICE, physical stop, and FIELD acceptance.

## Rollback

The decision and audit are documentation-only. Revert only the scoped documentation commit if its source map becomes inaccurate. Do not reset `main`, remove unrelated worktrees, or change ignored/device state.
