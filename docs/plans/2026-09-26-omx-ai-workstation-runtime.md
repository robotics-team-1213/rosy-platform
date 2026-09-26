# OMX-AI Workstation Runtime Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prepare a reproducible, disabled-by-default OMX-AI workcell runtime with arm-control and camera-stream foundations without coupling it to the Pinky Pro runtime.

**Architecture:** Keep ROBOTIS `open_manipulator` as the actuator and robot-model authority; Rosy OS owns the workstation image, explicit device admission, profile validation, local camera/calibration data path, and later integration boundary. Build a separate amd64 workstation OCI image from immutable Jazzy source revisions; keep `deploy/robot`'s Raspberry Pi ARM64 product image unchanged.

**Tech Stack:** ROS 2 Jazzy, ROBOTIS `open_manipulator` 5.1.2, `ros2_control`, Docker/Compose for development/build candidate, Python/YAML host contracts, UVC `usb_cam` candidate pending camera selection. Field actuator packaging follows the D-246 gate below.

**Host placement clarification (D-281 proposal, 2026-09-26):** The current OCI image and Compose hardware shell are development/ROS-SIM and build candidates, not an accepted field actuator runtime. Accepted D-246 keeps device control/safety native and restricts containers that directly own UART/video devices. For the first field candidate, plan one native systemd control instance per OMX-AI workcell; one Ubuntu host may run two instances if graph, device, stop/recovery, and concurrent-load tests pass. Before P1/DEVICE delivery, either document and implement that native path or make an explicit new ADR decision that supersedes D-246 for an OMX container, backed by physical stop/recovery evidence. See [host placement design](2026-09-26-site-host-placement-design.md). This clarification does not enable the disabled OMX profile.

---

## Decisions and deployment options

| Option | Advantages | Limits | Use |
|---|---|---|---|
| Install on Ubuntu 24.04 host | Direct USB/udev access and quickest diagnosis | Host package state drifts; mixes ROSY and vendor dependencies | Keep as a documented recovery/development fallback |
| Use ROBOTIS's published container as-is | Closest to vendor guide and fast to start | Current Docker Hub tag trails the source release; vendor Docker recipe uses broad `/dev`, Zenoh, RealSense, and Physical AI services | Reference only; don't deploy unchanged |
| Build a separate Rosy OMX workstation image from pinned upstream sources | Reproducible source set, narrow serial/camera device grants, keeps Pinky image and OMX workstation independent | Needs a Linux workstation build/runtime and an explicit RMW decision before cross-process ROS integration; hardware shell is not a D-246-approved field actuator runtime | **Recommended first development delivery** |

Do not extend the current `deploy/robot` ARM64 `io` target into the OMX workstation image. That target serves Pinky Pro hardware, uses CycloneDDS, and has a different device/runtime boundary. The OMX workstation image is a separate OCI image; it is not a Raspberry Pi disk image. A native installed workstation can remain available for diagnosing container and USB permission problems.

## Confirmed upstream inputs

- ROBOTIS official source release: `open_manipulator` 5.1.2, commit `0a4af6a923b8b7d80b8c20506d1839c54d2e993e`.
- Required Jazzy sources are resolved to immutable commit IDs in `deploy/omx/stack.lock.yaml`; do not clone a moving branch at image build time.
- The official 5.1.2 follower launch accepts `port_name`, but defaults to `/dev/ttyACM0`; leader defaults to `/dev/ttyACM2`. The official setup guide recommends stable `/dev/serial/by-id/` identity. Rosy must resolve operator-selected by-id identities on the host and grant only those concrete serial devices to the container.
- The official follower AI controller configuration uses `joint1` through `joint5` and `gripper_joint_1` at 100 Hz. Keep this as an upstream reference only: the shipped Rosy profile has no measured joint map and does not expose a controller contract.
- ROBOTIS's image recipe sets `RMW_IMPLEMENTATION=rmw_zenoh_cpp` and `ROS_DOMAIN_ID=30`, while Rosy device runtime uses CycloneDDS. Keep the first OMX workcell isolated; do not assume mixed-RMW discovery. Any bridge or shared command surface needs an explicit topic/action allowlist and a separate API/ADR decision.
- The camera model is not yet selected. Prepare a generic local `image_raw` + matching `CameraInfo` path and optional image transport. Do not pull RealSense/Orbbec SDKs into the baseline by assumption. Keep browser preview behind D-152's low-rate, authenticated preview contract.

## Implementation sequence

### P0a — Source and profile preparation

1. Pin the upstream repositories in `deploy/omx/stack.lock.yaml` and add a host test that rejects missing/non-immutable revisions.
2. Set the selected target to `omx_ai` while keeping `enabled: false`, empty joint mapping, driver plugin, serial identity, and capability contract.
3. Keep the generic adapter's disabled profile valid with an empty joint map; enabled configurations still require a complete unique joint mapping, package, and hardware plugin.
4. **Implemented locally:** build a workstation-specific Dockerfile from ROS Jazzy using only the locked vendor sources. It resolves full commit SHAs, installs ROS dependencies and runs `colcon`; it does not copy the upstream recipe's broad `/dev`, RealSense, AI training, agent, or Zenoh defaults. Camera packages remain deferred until hardware selection.

### P0b — Runtime admission and ROS graph

1. **Implemented locally:** Linux preflight resolves separate leader/follower by-id entries, rejects identical devices, verifies character-device type and read/write access, and emits only the two resolved paths. It never guesses `/dev/ttyACM*`.
2. **Implemented locally for serial only:** the opt-in hardware Compose shell binds those two exact devices, with no privileged mode or wildcard `/dev` access. Camera grants remain deferred until a camera identity is selected.
3. **Implemented locally as shells only:** separate opt-in hardware and software-only Compose profiles are inert interactive shells. No vendor driver, mock hardware, or simulator starts yet. Keep vendor mock bringup gated until exact ROS-SIM dependencies and launch behavior are verified.
4. Run official follower/leader launch in ROS-SIM after proving the supported mock path. Validate the graph and command ownership without claiming DEVICE acceptance.

### P1 — Arm command/control baseline

1. Wrap the vendor trajectory action with one command owner, bounded goals, stale-state rejection, cancel/timeout HOLD, and explicit operator recovery.
2. Never allow leader teleop, MoveIt, rule-based pick, or learned policy to command concurrently.
3. Keep stop behavior as unverified until real communication loss, power loss, stop, and restart tests are measured with an independent physical stop.

### P2 — Camera stream and calibration

1. Add a separately enabled camera source keyed by persistent device identity, source frame, calibration revision, and capture timestamp.
2. Publish a bounded latest-frame path and synchronized `CameraInfo`; measure actual format/FPS/drop/latency on the selected camera.
3. Save intrinsics, table plane, camera-to-arm/TCP transforms, and independent 3x3 validation results under a calibration revision.
4. Keep raw local workcell video out of CORE dashboard and Fleet paths.

### P3+ — Pick, wrist camera, and learning

Follow D-273: rule-based fixed workcell pick first, then wrist RGB and synchronized demo data, then ACT comparison. No Pinky mounting or mobile manipulation in this plan.

## Acceptance boundaries

- **SOURCE/LOCAL:** lock validation, profile validation, Docker/Compose static policy, and host tests.
- **ROS-SIM:** exact locked Jazzy image builds, vendor launch graph, action ownership, camera topics, fault/timeout behavior in simulation.
- **ARTIFACT:** immutable multi-arch or workstation-specific image digest and dependency manifest.
- **DEVICE:** actual OMX-AI revision, two serial interfaces, power, safe stop/recovery, selected camera, measured timing and calibration.
- **FIELD:** fixed workcell task acceptance; separate from Pinky or fleet operation.

No source or simulator success enables the OMX capability. Keep `omx.enabled: false` until D-273's device acceptance evidence exists.

## Official references

- [ROBOTIS OMX software overview](https://ai.robotis.com/omx/software_omx.html)
- [ROBOTIS OMX Physical AI Tools setup](https://ai.robotis.com/omx/setup_guide_physical_ai_tools.html)
- [ROBOTIS official `open_manipulator` 5.1.2 release](https://github.com/ROBOTIS-GIT/open_manipulator/releases/tag/5.1.2)
- [ROBOTIS OMX-AI follower launch at 5.1.2](https://github.com/ROBOTIS-GIT/open_manipulator/blob/5.1.2/open_manipulator_bringup/launch/omx_f_follower_ai.launch.py)
- [ROBOTIS OMX-AI follower controller config at 5.1.2](https://github.com/ROBOTIS-GIT/open_manipulator/blob/5.1.2/open_manipulator_bringup/config/omx_f_follower_ai/hardware_controller_manager.yaml)
- [ROBOTIS official container Dockerfile at 5.1.2](https://github.com/ROBOTIS-GIT/open_manipulator/blob/5.1.2/docker/Dockerfile)
