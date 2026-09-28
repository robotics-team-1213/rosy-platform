# Isaac Sim 6.1 integration

`description/` remains the robot model source. `prepare_urdf.py` renders its xacro with the simulation collision geometry and without Gazebo plugins. `run_rosy.py` imports that URDF with the Isaac Sim 6.1 importer and creates ROS 2 graphs for one robot: `/rosy_01/cmd_vel` subscription, `/rosy_01/odom`, `/rosy_01/joint_states`, global `/tf`, and one global `/clock` publisher. The USD and URDF are generated artifacts, not repository source.

## Requirements

- Ubuntu 24.04 with ROS 2 Jazzy `xacro` and an Isaac Sim 6.1 installation on a supported NVIDIA GPU host. Check the [official system requirements](https://docs.isaacsim.omniverse.nvidia.com/6.1.0/installation/requirements.html) before installing. The GPU runtime is not part of this repository or the Pinky Pi image.
- Source the ROSY Jazzy workspace for `xacro` package lookup. Before running Isaac Sim, follow its [ROS 2 bridge setup](https://docs.isaacsim.omniverse.nvidia.com/6.1.0/installation/install_ros.html). Set `ROS_DOMAIN_ID=41` for `rosy_01` and use the same RMW implementation for CORE and Isaac Sim.
- Choose an output directory outside the repository. On this Windows workspace, generated files belong only under `X:\DevTemp\`; on the Linux GPU host, use a scratch directory outside the checkout.

## Run on the GPU host

```bash
source /opt/ros/jazzy/setup.bash
export ROSY_REPO=/path/to/rosy-os
source "$ROSY_REPO/src/install/setup.bash"
export ROS_DOMAIN_ID=41
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp  # or use the same supported RMW as CORE
python3 "$ROSY_REPO/src/sim/isaac_sim/prepare_urdf.py" --output /scratch/rosy-isaac/rosy.urdf
cd /path/to/isaac-sim
./python.sh "$ROSY_REPO/src/sim/isaac_sim/run_rosy.py" \
  --urdf /scratch/rosy-isaac/rosy.urdf \
  --output-dir /scratch/rosy-isaac/usd --namespace rosy_01 --headless
```

Set `ROSY_REPO` to the real ROSY checkout path and build its Jazzy `src` overlay first. If the 6.1 asset transformer produces more than one articulation or base footprint prim, inspect the imported USD and pass `--robot-prim` and `--chassis-prim`. The runner stops with a clear error when discovery is ambiguous.

Run a single CORE instance in the same namespace and domain. Verify `/clock`, `/rosy_01/odom`, `/tf`, `/rosy_01/joint_states`, the wheel joint names, and the number of `/rosy_01/cmd_vel` publishers before enabling motion. Configure external ROS nodes with `use_sim_time=true`. Record motion and zero-command behavior from the live simulation, not just the graph declaration. The initial integration has no LiDAR, camera, Nav2, or timeout evidence and has not been run on an Isaac Sim host.

The soccer training environment deferred by D-98 belongs to `src/site/games/games/isaac/` and is not enabled here. See [D-322](../../../docs/adr/D-322-isaac-sim-rosy-integration.md) and the [research note](../../../docs/reference/isaac-sim-integration-research.md).

## Robot model assets

- **Pinky Pro:** The checked in URDF/xacro and 19 meshes live in [`../description/`](../description/). `prepare_urdf.py` resolves these files for Isaac Sim. The official `pinklab-art/pinky_pro` model was checked at commit `014a09f289e6988894fbffde2624fdb1e257815b`; 13 meshes match byte for byte and six Collada visuals differ. Keep the ROSY model as the executable source until those visual differences are reviewed. See [`assets/README.md`](assets/README.md).
- **OMX-AI:** [`assets/open_manipulator_description/`](assets/open_manipulator_description/) contains the official ROBOTIS OMX-F follower and OMX-L leader URDFs and their referenced STL meshes. The snapshot is pinned to the same `open_manipulator` revision as `deploy/robot/omx/stack.lock.yaml`, with SHA-256 hashes in `manifest.json` and Apache-2.0 license text.

To prepare one OMX model for the Isaac URDF importer, resolve its local mesh paths into a generated file outside the checkout:

```bash
python3 "$ROSY_REPO/src/sim/isaac_sim/prepare_omx_urdf.py" \
  --model omx_f --output /scratch/rosy-isaac/omx_f.urdf
```

Use `--model omx_l` for the leader. Before opening Isaac, check the pinned file hashes, vendor URDF references, and the prepared Pinky URDF:

```bash
python3 "$ROSY_REPO/src/sim/isaac_sim/model_checks.py" \
  --pinky-urdf /scratch/rosy-isaac/rosy.urdf
```

Import and inspect one OMX model with Isaac Sim's own Python. This checks for exactly one articulation and the expected joint names in the generated USD:

```bash
cd /path/to/isaac-sim
./python.sh "$ROSY_REPO/src/sim/isaac_sim/import_omx.py" \
  --model omx_f --urdf /scratch/rosy-isaac/omx_f.urdf \
  --output-dir /scratch/rosy-isaac/omx-f-usd --headless
```

These are importable geometry and joint models; `run_rosy.py` is a Pinky mobile-base runner and does not supply an OMX articulation controller, cameras, calibrated workcell, or trained policy. Datasets and model weights depend on a selected manipulation task and are not part of the robot description snapshot.

### GPU-host acceptance still required

The Pinky URDF places wheel joint origins at ±0.04055 m, a geometric center separation of **0.0811 m**. The Gazebo drive plugin and initial Isaac controller both use **0.0961 m** as the effective `wheelDistance`. These are different quantities until measured; do not silently change either. On the GPU host, import the USD, confirm wheel axis/sign and ground contact, then compare commanded yaw with `/odom` and observed rotation. Also confirm one `/clock` publisher, TF frame IDs, command topic ownership, and zero-command/command-loss stopping before Nav2 or an extended run. The current OmniGraph path has no proven stale-command watchdog, so a successful import or host test does not clear the motion gate.
