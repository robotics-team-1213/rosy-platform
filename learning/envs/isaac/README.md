# Isaac Sim 5.1/6.x integration

`middleware/devices/pinky/description/` remains the robot model source. `prepare_urdf.py` renders its xacro with the simulation collision geometry and without Gazebo plugins. `run_rosy.py` selects the installed 5.1 legacy or 6.x modern importer and creates ROS 2 graphs for one robot: `/rosy_01/cmd_vel` subscription, `/rosy_01/odom`, `/rosy_01/joint_states`, global `/tf`, and one global `/clock` publisher. The USD and URDF are generated artifacts, not repository source.

D-434 keeps the model PC on Isaac Sim 5.1. Its bounded diagnostic runs headless at 640×480 with anti-aliasing disabled. The runner excludes the GUI menu during initial startup; the importer can enable that dependency later. Keep normal extension shutdown so exceptions and failed cleanup remain visible. The SDK repair pins in `requirements-sdk-5.1.txt` apply to a separate SDK environment, not Isaac Lab.

## Requirements

- Ubuntu 24.04 with ROS 2 Jazzy `xacro` and the separately managed Isaac Sim SDK on a supported NVIDIA GPU host. See [D-434](../../../docs/adr/D-434-model-pc-and-site-pc-roles.md) for the accepted host/version/resource boundary. The GPU runtime is not part of this repository or the Pinky Pi image.
- Source the ROSY Jazzy workspace for `xacro` package lookup. Before running Isaac Sim, configure its ROS 2 bridge. Set `ROS_DOMAIN_ID=41` for `rosy_01`; CORE retains its configured CycloneDDS transport, and the SDK's bridge transport must interoperate with it.
- Choose an output directory outside the repository. On this Windows workspace, generated files belong only under `X:\DevTemp\`; on the Linux GPU host, use a scratch directory outside the checkout.

## Run on the GPU host

```bash
source /opt/ros/jazzy/setup.bash
export ROSY_REPO=/path/to/rosy-platform
export ISAAC_PYTHON=/path/to/isaac-sdk-venv/bin/python
source "$ROSY_REPO/install/setup.bash"
export ROS_DOMAIN_ID=41
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp  # or use the same supported RMW as CORE
python3 "$ROSY_REPO/learning/envs/isaac/prepare_urdf.py" --output /scratch/rosy-isaac/rosy.urdf
"$ISAAC_PYTHON" "$ROSY_REPO/learning/envs/isaac/run_rosy.py" \
  --urdf /scratch/rosy-isaac/rosy.urdf \
  --output-dir /scratch/rosy-isaac/usd --namespace rosy_01 --headless
```

Set `ROSY_REPO` to the real ROSY checkout path and build its Jazzy overlay first. Use the SDK Python, not the system Python; an extracted SDK can also provide `python.sh`. If the importer produces more than one articulation or base footprint prim, inspect the imported USD and pass `--robot-prim` and `--chassis-prim`. The runner stops with a clear error when discovery is ambiguous.

Run a single CORE instance in the same namespace and domain. Verify `/clock`, `/rosy_01/odom`, `/tf`, `/rosy_01/joint_states`, the wheel joint names, and the number of `/rosy_01/cmd_vel` publishers before enabling motion. Configure external ROS nodes with `use_sim_time=true`. Record motion and zero-command behavior from the live simulation, not just the graph declaration. This runner has no LiDAR, camera, map scene, Nav2, Fleet or RL environment.

The soccer training environment deferred by D-98 belongs to `operations/apps/games/games/isaac/` and is not enabled here. See [D-322](../../../docs/adr/D-322-isaac-sim-rosy-integration.md) and the [research note](../../../docs/reference/isaac-sim-integration-research.md).

## Robot model assets

- **Pinky Pro:** The checked in URDF/xacro and 19 meshes live in [`middleware/devices/pinky/description/`](../../../middleware/devices/pinky/description/). `prepare_urdf.py` resolves these files for Isaac Sim. The official `pinklab-art/pinky_pro` model was checked at commit `014a09f289e6988894fbffde2624fdb1e257815b`; 13 meshes match byte for byte and six Collada visuals differ. Keep the ROSY model as the executable source until those visual differences are reviewed. See [`assets/README.md`](assets/README.md).
- **OMX-AI:** [`assets/open_manipulator_description/`](assets/open_manipulator_description/) contains the official ROBOTIS OMX-F follower and OMX-L leader URDFs and their referenced STL meshes. The snapshot is pinned to the same `open_manipulator` revision as `deploy/robot/omx/stack.lock.yaml`, with SHA-256 hashes in `manifest.json` and Apache-2.0 license text.

To prepare one OMX model for the Isaac URDF importer, resolve its local mesh paths into a generated file outside the checkout:

```bash
python3 "$ROSY_REPO/learning/envs/isaac/prepare_omx_urdf.py" \
  --model omx_f --output /scratch/rosy-isaac/omx_f.urdf
```

Use `--model omx_l` for the leader. Before opening Isaac, check the pinned file hashes, vendor URDF references, and the prepared Pinky URDF:

```bash
python3 "$ROSY_REPO/learning/envs/isaac/model_checks.py" \
  --pinky-urdf /scratch/rosy-isaac/rosy.urdf
```

Import and inspect one OMX model with Isaac Sim's own Python. This checks for exactly one articulation and the expected joint names in the generated USD:

```bash
"$ISAAC_PYTHON" "$ROSY_REPO/learning/envs/isaac/import_omx.py" \
  --model omx_f --urdf /scratch/rosy-isaac/omx_f.urdf \
  --output-dir /scratch/rosy-isaac/omx-f-usd --headless
```

These are importable geometry and joint models; `run_rosy.py` is a Pinky mobile-base runner and does not supply an OMX articulation controller, cameras, calibrated workcell, or trained policy. Datasets and model weights depend on a selected manipulation task and are not part of the robot description snapshot.

### GPU-host acceptance still required

[Latest-main headless evidence](../../../docs/validation/isaac-latest-core-main-2026-10-11/result.md) records the current CORE source, remote regression and measured motion/stop results. Rotation tracking remains below the acceptance band, so the complete ROS-SIM/RL gate stays HOLD.

The Pinky URDF places wheel joint origins at ±0.04055 m, a geometric center separation of **0.0811 m**; the wheel collision cylinders sit a further ±0.008 m out, a contact separation of **0.0971 m**. The Gazebo drive plugin and the Isaac controller both use that URDF nominal **0.0971 m** as `wheelDistance` (D-397, `middleware/devices/pinky/profile/config/geometry.yaml`); a robot's accepted `wheel_odometry` calibration record refines it on the device. On the GPU host, import the USD, confirm wheel axis/sign and ground contact, then compare commanded yaw with `/odom` and observed rotation. Also confirm one `/clock` publisher, TF frame IDs, command topic ownership, and zero-command/command-loss stopping before Nav2 or an extended run. The runtime receipt watchdog and zero target readback do not replace measured physical stopping or yaw tracking. Keep motion acceptance separate from an import or host test.
