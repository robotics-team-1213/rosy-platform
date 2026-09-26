# OMX-AI Workcell Deployment Preparation

This directory builds a separate ROS 2 Jazzy workstation OCI image for a fixed
OMX-AI workcell. `stack.lock.yaml` pins the official ROBOTIS source set to
immutable revisions. It is not part of the Raspberry Pi product image.

## Current contract

- Target model: OMX-AI.
- Runtime profile: disabled; no joint map, hardware plugin, serial identity,
  camera identity, or motion command is configured.
- Vendor entry point: official ROBOTIS `open_manipulator` ROS 2 packages.
- Development/build candidate: a dedicated workstation OCI image, initially
  amd64. Keep it separate from `deploy/robot`'s Pinky Pro ARM64 product image.
- Field control candidate: one native systemd instance per workcell under
  D-246. One Ubuntu host may run two instances after graph, device, stop,
  recovery, and concurrent-load validation. The OCI shell below is not an
  accepted field actuator runtime.
- Camera source: unselected. Choose a camera and driver before adding camera
  packages to the runtime image.

See [the implementation plan](../../docs/plans/2026-09-26-omx-ai-workstation-runtime.md)
and [host placement design](../../docs/plans/2026-09-26-site-host-placement-design.md)
for deployment trade-offs, RMW boundaries, and P0-P3 acceptance gates.

## Host inventory and multi-workcell preflight

`host-inventory.yaml.example` is a disabled placement template for one or two
workcells on one host. `host_inventory.load_inventory()` parses the static
`rosy.omx-host-inventory.v1` YAML contract. `hosts` and `workcells` are keyed by
their IDs; every workcell needs an `instance_id`, a known `host_id`, and an
explicit boolean `enabled`. A disabled workcell may omit `follower` and
`leader` or set them to `null`. An enabled workcell needs two distinct,
operator-selected `/dev/serial/by-id/` entries. A selected `camera` identity
is optional until a camera is chosen. Enabled workcells on the same host may
not select the same serial or camera identity.

Keep a filled host inventory in gitignored `private/` or `/etc/rosy/omx/` on
that host. Do not put real serial identities, camera IDs, addresses, or tokens
in the tracked example. The parser does not open devices or register OMX in
Fleet. It is not wired into site Compose or an operational control service.

`preflight.resolve_host_devices(inventory, host_id, probe=...)` reuses the
single-workcell serial preflight for every enabled workcell assigned to one
host. It checks that selected entries resolve to readable and writable
character devices, then rejects real-path aliasing across workcells. Disabled
workcells and workcells on other hosts are not probed or reserved. This is a
software admission check; only a later, separately validated native control
runner may consume the returned per-workcell paths. No camera is opened by
this preflight.

## Build and shell profiles

The hardware profile takes `OMX_ROS_DOMAIN_ID` and
`OMX_ROS_AUTOMATIC_DISCOVERY_RANGE` from the Compose environment; defaults are
domain 30 and `SUBNET`. Copy `.env.example` to `.env` beside this README to set
them, then pass it with `--env-file deploy/omx/.env` when running Compose from
the repository root. RMW is fixed to `rmw_cyclonedds_cpp` by D-117. The
simulation profile uses a separate configurable domain (default 31) and forces
`LOCALHOST` discovery.

Pinky's domain is derived at device provisioning from `ROSY_ROBOT_NUMBER`
(D-33), so never change Pinky's identity to match the workstation. Matching an
OMX domain to Pinky's value alone does not authorize or guarantee a connection:
the D-273 ROS/RMW and control-boundary decision remains required. Do not use
this workstation profile to join Pinky's actuation graph directly.

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
docker compose --env-file deploy/omx/.env --profile hardware run --rm omx-hardware-shell
```

The preflight refuses guessed `/dev/tty*` paths, missing
or non-character devices, inaccessible devices, and duplicate selections.
Never use privileged mode or mount `/dev` wholesale.

The `simulation` profile starts ROBOTIS's `omx_f_follower_ai_gazebo.launch.py` from the
locked `open_manipulator` revision. That launch uses the vendor OMX-F URDF
with `use_sim:=true`, Gazebo Sim, `gz_ros2_control`, the vendor controllers,
and the `/clock` bridge. It has no serial or camera device grants. Its ROS
domain is isolated from the workstation and remains software-only; it does
not start the physical Dynamixel driver or claim device acceptance. A checked-in
A checked-in patch selects Gazebo server mode and Bullet Featherstone physics
for the gripper mimic constraint, makes simulated `ros2_control` synchronous,
and enables the vendor controller manager's URDF command limits. These are
simulation settings; the native actuator configuration remains unchanged.
The simulation launch also removes the vendor's direct
`/leader/joint_trajectory` remap. In a two-input probe, the leader topic moved
`joint1` to `-0.2` rad while an action to `+0.2` rad reported success. The
simulation therefore exposes the action path without that leader connection.
This does not implement a general command owner for native control.
Patch files are checked out with LF endings so `git apply` works in the Linux
image even when the build context comes from a Windows checkout.
Start it on a Linux workstation with a working Docker engine:

```sh
docker compose --env-file deploy/omx/.env -f deploy/omx/compose.yaml --profile simulation up --build omx-simulation
```

Stop with Ctrl-C. Verify `/joint_states`, controller state, and `/clock` from
inside the container before treating the run as ROS-SIM evidence. This profile
does not yet include a camera simulation, arm command-safety adapter, or
automated stop/fault acceptance. Camera packages and grants remain deferred
until a camera model and persistent identity are selected.

The image tag is a local development tag, not an artifact identity. Record a
content digest and dependency/build manifest before treating it as ARTIFACT
acceptance. A successful host build does not prove ARM64 Pi compatibility,
device access, arm motion, camera timing, or field acceptance.
