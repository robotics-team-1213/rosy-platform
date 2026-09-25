# ROSY OS Architecture Documentation v0.1

ROSY OS is a **Distributed Robotics & Physical AI Operating Platform** built initially for **Ubuntu + ROS 2**.

## Core Principles

1. ROSY OS is not a replacement for Ubuntu.
2. ROSY OS is a distributed runtime and orchestration layer above Ubuntu + ROS 2.
3. Every node installs only the ROSY components it actually needs.
4. Device, Edge, Compute, AI, and Control roles are separated through installable profiles.
5. ROSY must continue safe local operation even when the central control plane is unavailable.
6. Existing ROS 2 and vendor drivers should be wrapped and standardized rather than rewritten unnecessarily.

## Initial Platform

- Ubuntu 24.04 LTS
- ROS 2 Jazzy
- x86_64 / ARM64
- NVIDIA CUDA / TensorRT where required
- Intel OpenVINO where required

## Primary Profiles

- `rosy-profile-control`
- `rosy-profile-pinky`
- `rosy-profile-omx`
- `rosy-profile-edge`
- `rosy-profile-gpu`
- `rosy-profile-vision`
- `rosy-profile-rfid`
- `rosy-profile-dev`

Profiles may be combined on one node.

## Core Domain Model

ROSY OS uses six primary domain objects:

1. Node
2. Device
3. Component
4. Capability
5. Asset
6. Task

## Document Index

| No. | Document | Purpose |
|---|---|---|
| 00 | ROSY OS Vision & Definition | Product and technical definition |
| 01 | Target Architecture | Overall target architecture |
| 02 | Domain Model | Node / Device / Capability model |
| 03 | Runtime Architecture | Common runtime architecture |
| 04 | Device Adapter Specification | Device adapter/plugin model |
| 05 | ROS 2 Interface Specification | Topic/Service/Action conventions |
| 06 | Device State & Lifecycle | Standard states and lifecycle |
| 07 | Capability Model | Capability abstraction |
| 08 | Task & Workflow | Task and workflow orchestration |
| 09 | Composite Robot | Pinky + OMX and composite assets |
| 10 | Compute Fabric | Gram + RTX cluster architecture |
| 11 | AI & Physical AI | AI/VLA/policy architecture |
| 12 | Dataset & Learning Pipeline | Teach-Record-Train-Deploy loop |
| 13 | Current-to-Target Migration | Refactoring plan |
| 14 | Verification & Acceptance | v1 validation criteria |
| 15 | Ubuntu Modular Installation | Package/profile installation design |
| 16 | Interface Design Principles | Human-facing surfaces: shared laws, per-surface grammar |

## Current mapping (2026-09-17)

`docs/architecture` is the **target** distributed OS. v1 maps those terms onto the live Pinky CORE + D-62 slices stack (D-65). Contract documents win on API, modes, `cmd_vel`, and identity: [CORE SRS](../spec/ROSY%20CORE%20SRS.md) §1.3, [ADR log](../reference/ROSY%20ADR%20Log.md) (D-62, D-65, D-67–D-71), [alignment design](../plans/2026-09-16-concept-runtime-alignment-design.md), [concept ADR plan](../plans/2026-09-17-concept-folder-adr-plan.md). Live glossary: [CONCEPTS.md](../../CONCEPTS.md).

| Concept | v1 mapping | ADR | Status |
|---|---|---|---|
| 00 Vision & definition | CORE SRS product scope | D-15, D-65 | live contract |
| 01 Target architecture | CORE + D-62 slices; Fleet console v1 is REST gather | D-1, D-62, D-71, **D-81** | hub listen / FleetAgent outbound not v1-blocking |
| 02 Domain model | CONCEPTS.md Node / Device / Component / Capability / Asset / Task | D-65 | live |
| 03 Runtime architecture | `core` process; no `rosy-runtime-*` apt | D-1, D-69 | live |
| 04 Device adapter | `bringup`, `omx_adapter` (disabled) + YAML manifests | D-57, D-69 | live |
| 05 ROS 2 interface | REST/WS is the external API; TaskKind sinks to internal ROS | D-65, D-71, **D-74** | concept `/rosy/{device_id}/…` is **not** the API |
| 06 Device state & lifecycle | `RobotMode` operational; inventory `device_state` derived | D-67 | live |
| 07 Capability | CAP-001 on `/capabilities`; descriptors on inventory | D-11, D-68 | live |
| 08 Task & workflow | `TaskKind` atomic REST; missions on Fleet | D-12, D-70 | live actions; workflow **not v1** |
| 09 Composite robot | single-device Asset only | D-55, D-71 | **not v1** |
| 10 Compute fabric | — | D-71 | **not v1** |
| 11 AI & Physical AI | vision/ai catalog only | D-41, D-71 | **not v1** |
| 12 Dataset & learning | — | D-71 | **not v1** |
| 13 Current-to-target | Phase 0–3 live; 4–5 = D-71 | D-65, D-71 | Phase 0–3 live |
| 14 Verification | Device validation ARTIFACT/DEVICE/FIELD; ARTIFACT builder is native Pi; ROS-SIM needs colcon install; crossing is Fleet mediation | D-71, D-78–D-80, D-83–D-85, D-87–D-89, **D-93** | Device GO not claimed; D-35 waits on Task 14 |
| 15 Ubuntu modular install | D-62 slices, not apt/`rosyctl` | D-62, D-69, D-71 | apt path **not v1** |
| 16 Interface design principles | operator console is CORE `/dashboard`; L2 is a vocabulary table not a shared CSS file | D-23, D-68, D-71, D-72, D-75, D-77, **D-92** | L1 colour + evidence live; G4 DEVICE HOLD |

## First Refactoring Priority

Start with:

1. `00_ROSY_OS_Vision_and_Definition.md`
2. `01_ROSY_OS_Target_Architecture.md`
3. `02_ROSY_Domain_Model.md`
4. `13_ROSY_Current_to_Target_Migration.md`
5. `15_ROSY_Ubuntu_Modular_Installation.md`

These five documents should be treated as the initial architecture baseline.
