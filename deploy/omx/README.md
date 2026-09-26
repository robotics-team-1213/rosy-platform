# OMX-AI Workcell Deployment Preparation

This directory builds a separate ROS 2 Jazzy workstation OCI image for a fixed
OMX-AI workcell. `stack.lock.yaml` pins the official ROBOTIS source set to
immutable revisions. It is not part of the Raspberry Pi product image.

## Current contract

- Target model: OMX-AI.
- Runtime profile: disabled; no joint map, hardware plugin, serial identity,
  camera identity, or motion command is configured.
- Vendor entry point: official ROBOTIS `open_manipulator` ROS 2 packages.
- Candidate deployment: a dedicated workstation OCI image, initially amd64.
  Keep it separate from `deploy/robot`'s Pinky Pro ARM64 product image.
- Camera source: unselected. Choose a camera and driver before adding camera
  packages to the runtime image.

See [the implementation plan](../../docs/plans/2026-09-26-omx-ai-workstation-runtime.md)
for deployment trade-offs, RMW boundaries, and P0-P3 acceptance gates.

## Build and shell profiles

Build on a Linux ROS 2 workstation with Docker:

```sh
docker compose -f deploy/omx/compose.yaml build
```

The image fetches only repositories in the lock, checks out full commit SHAs,
installs the locked stack's arm bringup/description/Dynamixel dependencies,
and builds the selected packages with `colcon`. It leaves Gazebo, MoveIt,
vendor GUI, RealSense, and camera packages out of this base image. `hardware` is an inert
interactive shell that receives only the explicitly selected follower and
leader serial ports. Generate the device values on that Linux host with:

```sh
python3 deploy/omx/preflight.py \
  --follower /dev/serial/by-id/<selected-follower-id> \
  --leader /dev/serial/by-id/<selected-leader-id>
```

Pass the resulting `OMX_FOLLOWER_DEVICE` and `OMX_LEADER_DEVICE` values as
environment variables to:

```sh
docker compose --profile hardware run --rm omx-hardware-shell
```

The preflight refuses guessed `/dev/tty*` paths, missing
or non-character devices, inaccessible devices, and duplicate selections.
Never use privileged mode or mount `/dev` wholesale.

The `simulation` profile is currently an isolated software-only shell: it has
no serial or camera grants and does not start a simulator or mock hardware.
Vendor mock bringup stays gated until the exact OMX-AI launch and mock package
set are verified in ROS-SIM. Neither shell profile starts vendor nodes or
motion by default. Camera packages and device grants remain deferred until a
camera model and persistent identity are selected.

The image tag is a local development tag, not an artifact identity. Record a
content digest and dependency/build manifest before treating it as ARTIFACT
acceptance. A successful host build does not prove ARM64 Pi compatibility,
device access, arm motion, camera timing, or field acceptance.
