# Isaac Sim 5.1/6.x integration

`description/` remains the robot model source. `prepare_urdf.py` renders its xacro with the simulation collision geometry and without Gazebo plugins. `run_rosy.py` selects the installed 5.1 legacy importer or 6.x Python API by capability and creates ROS 2 graphs for one robot: `/rosy_01/cmd_vel` subscription, `/rosy_01/odom`, `/rosy_01/joint_states`, global `/tf`, and one global `/clock` publisher. The USD and URDF are generated artifacts, not repository source.

## Requirements

- Ubuntu 24.04 with ROS 2 Jazzy `xacro` and an Isaac Sim installation on a supported NVIDIA GPU host. The model PC retains 5.1 per [D-434](../../../docs/adr/D-434-model-pc-and-site-pc-roles.md); the [5.1 system requirements](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/installation/requirements.html) specify at least 32 GB RAM. The GPU runtime is not part of this repository or the Pinky Pi image.
- Source the ROSY Jazzy workspace for `xacro` package lookup. Before running Isaac Sim, follow the installed version's [ROS 2 bridge setup](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/installation/install_ros.html). Set `ROS_DOMAIN_ID=41` for `rosy_01`. Keep the SDK's Python 3.11 environment separate from external Jazzy Python 3.12; verify DDS discovery and topic receipt across the processes.
- Choose an output directory outside the repository. On this Windows workspace, generated files belong only under `X:\DevTemp\`; on the Linux GPU host, use a scratch directory outside the checkout.

## Run on the GPU host

```bash
source /opt/ros/jazzy/setup.bash
export ROSY_REPO=/path/to/rosy-os
source "$ROSY_REPO/install/setup.bash"
export ROS_DOMAIN_ID=41
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp  # or use the same supported RMW as CORE
python3 "$ROSY_REPO/learning/envs/isaac/prepare_urdf.py" --output /scratch/rosy-isaac/rosy.urdf
cd /path/to/isaac-sim
./python.sh "$ROSY_REPO/learning/envs/isaac/run_rosy.py" \
  --urdf /scratch/rosy-isaac/rosy.urdf \
  --output-dir /scratch/rosy-isaac/usd --namespace rosy_01 --headless
```

Set `ROSY_REPO` to the real ROSY checkout path and build its Jazzy overlay first. For a pip-installed 5.1 SDK, use its own venv Python instead of `./python.sh`, clear the external ROS `PYTHONPATH`, and set `LD_LIBRARY_PATH` to the SDK's `exts/isaacsim.ros2.bridge/jazzy/lib` as documented above. If the importer produces more than one articulation or base footprint prim, inspect the imported USD and pass `--robot-prim` and `--chassis-prim`. The runner stops with a clear error when discovery is ambiguous.

Run a single CORE instance in the same namespace and domain. Verify `/clock`, `/rosy_01/odom`, `/tf`, `/rosy_01/joint_states`, the wheel joint names, and the number of `/rosy_01/cmd_vel` publishers before enabling motion. Configure external ROS nodes with `use_sim_time=true`. Record motion and zero-command behavior from the live simulation, not just the graph declaration. The runner has a command freshness watchdog; [earlier CORE drive measurements](../../../docs/validation/cell-isaac-2026-10-04/isaac-core-drive.md) did not pass forward tracking or physical stopping. LiDAR, camera, Nav2 and two-robot Fleet are not accepted.

### Headless SDK environment

`--headless` sets 640×480 rendering with anti-aliasing off and excludes `isaacsim.gui.menu` from the initial startup order. The importer can subsequently enable that SDK dependency; keep its normal lifecycle, since runtime unloading left stale USD callbacks. Use `--frames 600` for a finite bootstrap check. D-434 limits the current 15 GB RAM host to one sensor-free Pinky, with no concurrent GPU training. Existing swap can support this bounded experiment; it does not meet the physical RAM requirement for accepting two robots with sensors.

Pinky imports merge fixed links to avoid separate massless reference bodies. Its wheels use verified force-type velocity drives, preserving a positive imported gain or the existing 1.0 fallback; the two caster joints remain passive. This restores motion at the default gain but does not establish accurate yaw tracking. OMX retains its separate fixed-link import behavior. Explicit `--wheel-damping` remains a measured tuning override.

Keep Isaac Lab and the standalone SDK in separate environments. The installed Lab metadata and Isaac 5.1 kernel require incompatible Starlette versions. [`requirements-sdk-5.1.txt`](requirements-sdk-5.1.txt) records the SDK repair pins, including CUDA 12.8 torchaudio; apply them only to a separate 5.1 SDK environment, with PyTorch's CUDA 12.8 wheel index. Do not apply them to the Lab environment. A copied venv can retain old shebangs, so invoke its explicit `bin/python -m pip`, remove unrelated Lab/notebook packages from that copy, and require `pip check` to pass with external ROS `PYTHONPATH` cleared.

The [2026-10-11 headless record](../../../docs/validation/isaac-headless-repair-2026-10-11/result.md) records CORE motion, actual stopping and isolated publisher-loss measurements separately from the remaining yaw-tracking, map, sensor and Fleet gates.

The soccer training environment deferred by D-98 belongs to `operations/apps/games/games/isaac/` and is not enabled here. See [D-322](../../../docs/adr/D-322-isaac-sim-rosy-integration.md) and the [research note](../../../docs/reference/isaac-sim-integration-research.md).

## Robot model assets

- **Pinky Pro:** The checked in URDF/xacro and 19 meshes live in [`middleware/apps/device/pinky/description/`](../../../middleware/apps/device/pinky/description/). `prepare_urdf.py` resolves these files for Isaac Sim. The official `pinklab-art/pinky_pro` model was checked at commit `014a09f289e6988894fbffde2624fdb1e257815b`; 13 meshes match byte for byte and six Collada visuals differ. Keep the ROSY model as the executable source until those visual differences are reviewed. See [`assets/README.md`](assets/README.md).
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
cd /path/to/isaac-sim
./python.sh "$ROSY_REPO/learning/envs/isaac/import_omx.py" \
  --model omx_f --urdf /scratch/rosy-isaac/omx_f.urdf \
  --output-dir /scratch/rosy-isaac/omx-f-usd --headless
```

These are importable geometry and joint models; `run_rosy.py` is a Pinky mobile-base runner and does not supply an OMX articulation controller, cameras, calibrated workcell, or trained policy. Datasets and model weights depend on a selected manipulation task and are not part of the robot description snapshot.

### GPU-host acceptance still required

The Pinky URDF places wheel joint origins at ±0.04055 m, a geometric center separation of **0.0811 m**; the wheel collision cylinders sit a further ±0.008 m out, a contact separation of **0.0971 m**. The Gazebo drive plugin and the Isaac controller both use that URDF nominal **0.0971 m** as `wheelDistance` (D-397, `middleware/apps/device/pinky/profile/config/geometry.yaml`); a robot's accepted `wheel_odometry` calibration record refines it on the device. On the GPU host, import the USD, confirm wheel axis/sign and ground contact, then compare commanded yaw with `/odom` and observed rotation. Also confirm one `/clock` publisher, TF frame IDs, command topic ownership, and zero-command/command-loss stopping before Nav2 or an extended run. Watchdog target zero and actual physical stopping require separate evidence; a successful import or host test does not clear the motion gate.
