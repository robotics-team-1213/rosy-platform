<!-- Parent: ../AGENTS.md -->

# control (ROS distribution in ROSY Platform)

**Parent context:** `../AGENTS.md`

## Purpose
ROS 2 Jazzy `control` distribution for the Pinky Pro desk-maze robot (~11 cm; RPi, RPLidar C1, US-016, 3× IR cliff, BNO055 IMU, OV5647). D-630: sensing source in `sensors/sensing`, camera/OpenCV source in `front_camera/perception`, Drive algorithms in `../drive/`. Existing import names, node composition, entry points and share resources stay with this distribution. `core` owns the final external API and the operational motor command path.

Source holders and installed identities: `control/_source_layout.py` (`CONTROL_ROOTS`, `PACKAGE_DIRS`, `FLAT_ROOTS`); size units: `test/architecture/size_units.txt` (D-766). Operator runbook (Korean): `STEPS.txt`. Folder map: `docs/reference/platform-folder-responsibilities.md`.

## For AI Agents

### Working In This Directory
- Harness (D-61): [progress.md](progress.md) · [logs.md](logs.md) · [index.md](index.md); procedure in the repository root `AGENTS.md`.
- Treat this directory as part of ROSY Platform. The original checkout is archived; no runtime, build, or test may require it.
- Preserve pure-logic behavior and its tests before changing ROS wiring. The target runtime must not activate this package's legacy final `/cmd_vel` publisher beside `core`.
- Put new **decision logic in its source holder** (`../drive/`, `sensors/sensing/`, `front_camera/perception/`, `calibration/`, `localization/`, `graph_health/`, `snapshots/`, `sensors/line_observation/`, `front_camera/object_observation/`).
- Decision modules stay ROS-free; dedicated adapters beside them may import ROS (D-747). Keep `control.*` identities; do not copy algorithms into compatibility entries.
- `config/robot.yaml` is the single shared parameter source; per-node yamls override it.
- The lidar is mounted rotated: **scan 0° = rear, nose = 180° URDF nominal (D-397; measured 181–182°, an accepted lidar_mount record refines it)**. Every heading goes through `robot_yaw()` / `wrap_pi()`.
- Docs/STEPS.txt are Korean; code comments and logs are English. Comments explain *why* against measured limits (lidar 5 cm min, US 2 cm blind zone, IR 4095 = ADC saturation, never a cliff).
- Learned loop (D-356): `learned_lane_node` is shadow-only and never publishes a command. Weights never live in `src/`; training and delivery tooling is in `learning/training/perception/`.
- Legacy chain: wander → raw command → safety_node → motors. The OS target selects the final command in CORE and publishes in RosBridge (D-38); never start both final publishers.
- One fused status label (`control/modes.pick_mode`) on `/robot/mode`; `/safety/mode` is a deprecated alias. Each node = `rclpy.Node` + one-concern mixins (wander = Senses/Judge/Contact/Motion; safety = Bumper/Hazard/Gate/Scale).
- Device install and enabling (scripts in `deploy/robot/pinky_pro/`): keep the runtime stationary during install and readback. Order: `install-pi.sh` → `verify-pi.sh` → `device-readback.sh --json`. `install-pi.sh` derives `ROS_DOMAIN_ID`/`ROSY_NAMESPACE`; never write identity values into `.env` by hand.
- Enable `motor` or `hardware` only after the stationary core, immutable image digest, ROS graph and single-publisher checks are GO. Enable calibration and camera profiles only after matching generation and sensor readback are retained.
- Record source/local/ROS-simulation results separately from artifact, Device and FIELD results. A host test or build does not prove a Device install, sensor capture, motor motion or arm operation; ARM64 image, Pi readback, CSI timing,
- motor deadman and OMX acceptance each need their own evidence.

### Testing Requirements
- `python3 -m pytest test/ -q` from `middleware/perception`; needs numpy/OpenCV. ROS graph tests need a separate isolated ROS Jazzy run. Add tests for new pure-logic decisions.

<!-- MANUAL: -->
