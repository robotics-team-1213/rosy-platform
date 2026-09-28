# Control and Shared Contract Boundary Audit Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Verify which source modules have independent owners, consumers, and build or installation boundaries before moving or splitting `runtime/sensing` or `core_common`.

**Architecture:** Preserve D-310's current source paths and ROS package names. Map each `control` responsibility and each `core_common` module to its producer, consumer, execution authority, tests, and image closure. Recommend a narrow move only when a real ownership and independent verification boundary is demonstrated.

**Tech Stack:** ROS 2 Jazzy and colcon manifests, Python imports and entry points, launch files, deployment Dockerfiles and package manifests, Markdown ADR/harness.

---

## Decision and scope

**Decision:** D-317 keeps the current tree while establishing criteria for a later, narrow source/package decision. This plan performs source and documentation auditing only. It does not change ROS package names, APIs, writers, launch behavior, Docker closure, or device configuration.

**Current status (2026-09-28):** D-317 is the Accepted structure decision; this plan completes its bounded source-level audit on baseline `f1f031e2`. Tasks 1-4 below close at SOURCE/LOCAL with current evidence and an explicit keep-paths result. The recorded WSL ROS 2 Jazzy build and installed-name comparison are existing evidence; they do not establish the locked-vendor native ARM64 payload, signed artifact, device installation/readback, or field acceptance, which remain separate gates.

**Audited in this pass:** `runtime/sensing/package.xml` defines the `control` package. Its setup declares 15 console scripts and one `rosy.sensor_provider` entry point. Its contents include sensing, calibration, planning, safety, diagnostics, tools, and a legacy `web_node`; the package also depends on `web_common`, Nav2, and SLAM components. CORE remains the Pinky final `cmd_vel` writer. The standalone legacy safety launch must not run beside CORE.

`contracts/foundation/core_common` contains `domain/`, `protocol/`, and root modules including `intent`, `succession`, configuration, identity, and profile. Fleet and CORE both use `intent` and `succession` rules; Overhead produces `SiteSightingPayload` consumed by Fleet. Other protocol modules have their own producer/consumer paths. These uses do not establish one universal Action schema or an independently distributable package.

## Proposed structure and operating map (D-317 reaffirmed)

The selected structure is the existing role-based tree. A folder says where source responsibility belongs; it does not by itself say which process runs, who owns the final actuator writer, which PC hosts it, or what is installed. Those are separate maps below.

```text
Rosy OS/
├── src/
│   ├── contracts/
│   │   ├── interfaces/                 # ROS interfaces
│   │   └── foundation/                 # core_common: wire, site, domain, config helpers
│   ├── drivers/imu_bno055/             # chip-level driver
│   ├── products/
│   │   ├── pinky_pro/{profile,bringup,adc,lamp,led}/
│   │   └── omx/{profile,adapter}/       # adapter is source placement, not accepted writer
│   ├── runtime/
│   │   ├── gateway/                    # ROS package core; Pinky gateway/final base writer
│   │   ├── {events,services,api_web,navigation}/
│   │   └── sensing/                     # ROS package control; mixed legacy/current package
│   ├── site/{fleet,overhead,games}/     # site mission ledger, camera processing, game host
│   ├── hmi/{dashboard,face,web}/        # presentation assets and shared web pieces
│   └── sim/{description,gz_sim}/        # robot descriptions and Gazebo
├── deploy/
│   ├── robot/                           # robot runtime/config/build definitions
│   ├── image/                           # native Pi image and payload builder
│   ├── release/                         # payload packaging/signing/verification
│   ├── site/                            # Fleet, Vision, and proxy services
│   ├── omx/                             # development/simulation setup; production owner unresolved
│   └── sd/                              # SD provisioning and readback tools
├── firmware/                            # dock/signal MCU firmware
├── docs/                                # decisions, contracts, plans, evidence
├── tools/                               # developer and verification commands
└── reference/                           # frozen upstream source
```

| Concern | Source/process boundary | Host and deployment evidence | Authority |
|---|---|---|---|
| Pinky movement | `runtime/gateway` (`core`) consumes CORE API; `runtime/sensing` (`control`) remains a separate ROS package | Robot Pi is the product host; native systemd is the runtime target. Container Dockerfiles describe build/image slices and do not alone prove the active Pi installation | CORE alone owns final `/cmd_vel`; `control` may provide bounded inputs and legacy standalone profiles must not run beside CORE |
| Site work ledger | `site/fleet` serves Fleet API/console and owns Mission/Step state | `deploy/site` separates Fleet, Vision, and proxy services on the site host; the operator PC browser is a client and need not host those services | Fleet orders work and records uncertainty; it does not write robot actuators |
| Camera/video | `site/overhead` receives phone JPEG and performs Vision processing; Fleet UI fetches the scoped latest preview directly from Vision | Site host deployment is described by `deploy/site`; actual site installation remains unverified | Fleet does not relay raw frames; phone, site browser, and robot browser are distinct clients/paths |
| Robot HMI | `hmi/dashboard` assets are served in-process by CORE; Fleet web assets remain with `site/fleet`; `runtime/sensing/web` is diagnostic | Browser location is not service placement. Site console is served by Fleet; robot console is served by CORE | Authentication and final command checks stay with the relevant server; no browser connects directly to ROS/DDS |
| OMX arm | `products/omx/adapter` translates product-facing ROS/vendor interfaces; profile is in `products/omx/profile` | `deploy/omx` is development/simulation evidence only | No production local writer, composite interlock process, or host is accepted by this source-layout decision |
| Future drone | No source root/package reserved | Deployment waits for selected aircraft, flight stack, install boundary, and offline behavior | Do not reuse Pinky `x/y/yaw`, `RobotMode`, or invent a generic controller before final actuator authority is identified |

Rejected for now: moving all of `control` under Pinky, promoting all of `core_common` to a universal action API, or adding parallel `devices/`, `device_control/`, or `controllers/<model>/` roots. These would duplicate source responsibility without a newly demonstrated owner and independently buildable/testable/installable runtime boundary. A future split needs that evidence plus consumer migration and rollback; an empty folder or naming preference is not a trigger.

| Module or path | Observed production use | Meaning for placement |
|---|---|---|
| `core_common.protocol.schemas` | CORE API/events and Fleet hub/task paths | Typed CORE↔Fleet values; keep separate from site-only records by contract meaning |
| `core_common.intent` | CORE `/do` and Fleet `/do` routes | Shared fixed grammar/route selection; it does not execute or own physical actions |
| `core_common.succession` | CORE swarm manager and Fleet console | Shared algorithm used on each side; no new server or control process implied |
| `core_common.protocol.sightings` | Overhead publishes `SiteSightingPayload`; Fleet receives it | Site observation contract, distinct from robot↔Fleet envelopes |
| `core_common.protocol.vision_preview` | Overhead ingest and Fleet preview lease paths | Preview authorization/data freshness contract, not Fleet ownership of camera bytes |
| `core_common.config`, `identity`, `profile`, `domain` | CORE runtime/API and product configuration paths | Mostly device-local runtime behavior; package co-location does not make it a Fleet API |

The D-317 baseline already corrected the stale `fleet` manifest comment that claimed production code used only `core_common.protocol.schemas`; source imports also use the listed intent, succession, sightings, and preview modules. The correction changed neither dependency nor runtime behavior.

| Build/deployment surface | Observed closure | What remains unproven |
|---|---|---|
| CORE stage in `deploy/robot/Dockerfile` | `core`, `core_common`, services/events/API, HMI assets, interfaces, Pinky profile | Does not install `control`; this stage is not a full signed/native product payload proof |
| IO stage in `deploy/robot/Dockerfile` | Explicitly selects `sllidar_ros2`, `interfaces`, `description`, `bringup`, `navigation`, `omx_adapter`, `omx`, `control`, and `web_common` | Why OMX adapter is in every IO image; exact native ARM64/Jazzy payload equivalence |
| Native payload builder in `deploy/image/build-native-payload.sh` | Runs `colcon build --base-paths src "$SLLIDAR_SRC"`; the current tree has 24 in-tree `package.xml` manifests plus the locked vendor package, including `fleet`, `overhead`, `games`, and `gz_sim`. `build_payload_release.py` copies the payload file set into the release | Whether site/simulation packages are intentionally shipped in a Pinky release; native-builder discovery with the locked vendor, native ARM64 build, signature, and target readback remain unproven |
| `deploy/image/required-ros-packages.txt` | Lists 13 mandatory in-tree packages; `verify-package-inventory.sh` checks these as a required subset, not as an allowlist | Which additional packages are built and included in the native install/release closure |
| `deploy/site/compose.yaml` | Fleet and Overhead Vision are distinct site services | Production site host resource/fault acceptance |
| `deploy/omx/compose.yaml` | Development hardware shell and simulation profiles | Accepted operational OMX owner/runtime or workcell deployment |

**Final SOURCE/LOCAL finding:** The tracked tree has 24 ROS package manifests under the seven documented source-role roots; no tracked `src/devices/` root exists. `control` is one package with mixed observer, calibration, planning, safety, diagnostics, and legacy UI entry points. No evidence in this pass shows a separately owned, independently built/tested/installed `control` sub-package. `core_common` has distinguishable wire, site, shared-rule, and CORE-local families, but current producers/consumers do not support extracting one universal Action API. Keep the D-310/D-315/D-317 source paths and package names.

**Still not established:** Whether every package discovered by the native `colcon build --base-paths src "$SLLIDAR_SRC"` is intentionally included in the Pinky payload; native-builder `colcon list` with the locked vendor and actual ARM64 build equivalence; signed artifact and target install/readback; an operational OMX local writer/interlock and its device evidence; physical stop/readback; or field acceptance. The IO Dockerfile's `omx_adapter` inclusion also remains an explicit product-image question. These are ARTIFACT/DEVICE/FIELD decisions, not reasons to move source folders in this pass.

## Task 1: Maintain the source and package inventory (SOURCE complete)

**Files:** `src/AGENTS.md`, `src/runtime/sensing/package.xml`, `src/runtime/sensing/setup.py`, `src/contracts/foundation/package.xml`, `src/site/fleet/package.xml`, module `package.xml` files.

1. **Completed at baseline `f1f031e2`:** recorded package path/name and source-role mapping from `src/AGENTS.md`, `package.xml`, Docker copy/build selections, and `deploy/site/compose.yaml`. The tracked tree has 24 manifests, all under `contracts`, `drivers`, `hmi`, `products`, `runtime`, `sim`, or `site`; the 24-manifest figure is static source evidence, not `colcon list` output.
2. **Completed:** `runtime/sensing/package.xml` is ROS package `control`; `setup.py` declares 15 console scripts and one `rosy.sensor_provider` entry point. The package includes sensing/observers, calibration, planning, safety, diagnostics, tools, map assets, and `web_node`. `control_node` publishes only to its configurable raw command topic; standalone legacy safety/wander launch profiles are not to run beside CORE.
3. **Completed with owner fields explicit:** the reviewed manifests and setup metadata do not prove independent accountable owners or release/support units for `control` sub-responsibilities. Record these as `unknown`, rather than treating maintainer contact tags or directory names as ownership.
4. **Preserved:** CORE owns Pinky's final `cmd_vel`. The source folders do not alter that authority.

**Exit:** Met for SOURCE/LOCAL. The inventory identifies current entry points and active/legacy writer profiles without calling `runtime/sensing` sensor-only or inferring independent ownership.

## Task 2: Map `core_common` module contracts (SOURCE complete)

**Files:** `src/contracts/foundation/core_common/**`, `src/runtime/**`, `src/site/**`, `src/hmi/**`, API reference and package manifests.

1. **Completed:** checked production imports and package manifests; test-only imports are excluded from consumer claims. The module-family matrix above records the consumers that define placement.
2. **Completed:** `protocol.schemas` contains typed CORE↔Fleet values; `protocol.sightings` carries Overhead→Fleet observations; `protocol.vision_preview` supports a scoped Fleet↔Vision preview lease/profile; `intent` and `succession` are local shared rules called by CORE and Fleet; `config`, `identity`, `profile`, and most `domain` helpers are CORE-side runtime behavior. Fleet's Mission/Step status remains site-owned.
3. **Completed for current source contracts:** D-18/API Reference and current producers/consumers distinguish these meanings. Actual compatibility with every deployed external client is not asserted by source imports and remains part of release/API validation.
4. **Decision:** no extraction or schema change. Additional consumers trigger review, not automatic package splitting.

**Exit:** Met for SOURCE/LOCAL. A reviewer can distinguish the current wire values, site-only values, preview lease values, shared local rules, and CORE-local helpers. No universal Action contract is evidenced.

## Task 3: Compare install and test boundaries (SOURCE complete; ARTIFACT pending)

**Files:** `deploy/robot/Dockerfile`, `deploy/image/required-ros-packages.txt`, `deploy/image/build-native-payload.sh`, `deploy/image/verify-package-inventory.sh`, `deploy/release/build_payload_release.py`, package tests, `tools/harness/rosy_harness.py`.

1. **Completed static comparison:** CORE Docker stage builds `core`, `pinky_pro`, `web_common`, and `dashboard` with its declared dependencies and excludes `control`. IO explicitly selects vendor `sllidar_ros2` plus eight in-tree packages: `interfaces`, `description`, `bringup`, `navigation`, `omx_adapter`, `omx`, `control`, and `web_common`. The native builder passes the whole tracked `src` root and the locked vendor package to `colcon`; the 13 names in `required-ros-packages.txt` are a minimum required subset, not an allowlist. The source tree contains site and simulation manifests, so intended native-product inclusion is not established here.
2. **Completed static trace:** `control/setup.py` installs launch files, `web/*.html`, map assets, and its entry points. `web_node` is a package/install surface even where a production launch excludes it; launch exclusion is not package exclusion.
3. **Completed Linux/Jazzy source-build evidence (existing D-310 record):** WSL ROS 2 Jazzy `colcon build --base-paths src` completed 24 packages, and the 24 source package XML names matched the installed ament index names. The evidence and X: build location are recorded in `docs/validation/d310-source-candidate-2026-09-27.md`. This validates the source workspace build/install overlay used there; it is not the locked-vendor native payload builder or a device install.
4. **Still NOT_RUN:** native-builder `colcon list` with the locked vendor, native ARM64 payload, signature/digest equivalence, target installation/readback, and DEVICE/FIELD acceptance. The native builder requires aarch64 and uses a vendor source closure not represented by that WSL build. No change to native inclusion policy is made without those closure and rollback checks.

**Exit:** Met for the current source/build manifests and the recorded WSL Jazzy source build. Whether every package discovered by the native builder belongs in a Pinky release is an unresolved product-release policy and stays an explicit ARTIFACT gate; this audit does not silently prune packages. Target installation/readback remains NOT_RUN and is not required to close this source audit.

## Task 4: Decide whether a later move is justified (decision complete: keep current paths)

1. **Decision recorded by Accepted D-317:** keep current paths. No new independent source owner and build/test/install/run boundary was found for a `control` split or `core_common` extraction.
2. Defer any future split until an owner, independently testable/buildable/installable unit, image closure, consumers, compatibility, and rollback are all evidenced. Then open a narrow superseding ADR and migration plan; do not reserve future roots now.
3. Preserve all ROS package names. A source folder change is not authorization for package/API renaming.
4. Keep device-local interpretation at the product adapter/runtime boundary when the product API and final writer are proven. Fleet retains Mission/Step; CORE retains Pinky movement; OMX local writer and drone authority remain unaccepted/deferred.

**Exit:** Met: the structure proposal is to retain the current seven source-role roots and current package names; no source move was justified. Accepted D-317 is the ADR decision, so a duplicate ADR is deliberately not created. This does not decide OMX production ownership, drone layout, or native package release policy.

## Task 5: Keep architecture maps current (baseline complete; current map reconciled)

**Files:** `docs/plans/2026-09-27-rosy-platform-role-and-contract-implementation-plan.md`, this plan, `docs/adr/D-317-control-and-shared-contract-source-boundaries.md`.

1. The active platform plan already uses the D-310 tree; the tracked source tree confirms there is no `src/devices/` package root.
2. The P0 text retains D-316's Pinky `attempt_id`→CORE terminal event correlation as SOURCE/LOCAL and leaves ROS-SIM, artifact, device/stop readback, and field gates separate.
3. This plan now presents one proposed tree with separate source-role, authority, host, and image-closure maps, including D-318's Fleet↔Vision preview path.

**Exit:** Met at baseline `f1f031e2`: the plan tree agrees with `git ls-tree` and current D-275/D-310/D-315/D-317/D-318 boundaries. D-318's source change does not change robot command ownership or make the browser PC the site server.

## Task 6: Verify and record (this plan's verification pending)

1. **Completed:** `python tools/harness/rosy_harness.py generate` exited 0 and added this journal entry to the recent-records section of `docs/index.md`.
2. **Completed:** `python tools/harness/rosy_harness.py lint` reported 0 errors and 17 existing metadata/freshness warnings. `python -m pytest test/test_network_topology_contracts.py test/test_harness_contracts.py -q` passed 78 tests; its 17 warnings are the same harness freshness notices. Focused path checks passed: Fleet/Overhead preview suites 46 passed; sensing launch contracts 2 passed. No unrelated module metadata was edited to hide warnings.
3. **Completed:** `git diff --check` passed. Only this plan, `docs/logs.md`, and generated `docs/index.md` changed. The Accepted ADR and ADR log were not edited because D-317 already owns this decision.
4. This pass is recorded separately from D-317's original integration at `edcf2818`; the audit branch began at `f1f031e2` and must be rebased onto current local `main` before integration.

**Exit:** D-317 remains the structure ADR; its plan now contains the complete source tree proposal, evidence-backed `keep current paths` result, and open artifact/device gates. Documentation SOURCE/LOCAL results remain distinct from ROS-SIM, ARTIFACT, DEVICE, physical stop, and FIELD acceptance.

## Rollback

The structure decision remains D-317. This completion changes only the audit plan, work journal, and generated index. If the source map becomes inaccurate, revert only this scoped documentation commit; do not move packages, edit native release inclusion, reset `main`, remove peer worktrees, or change ignored/device state.
