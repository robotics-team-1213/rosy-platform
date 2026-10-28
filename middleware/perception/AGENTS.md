<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-06 | Updated: 2026-09-14 -->

# control (ROS distribution in ROSY Platform)

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-12

## Purpose
ROS 2 Jazzy `control` distribution in **ROSY Platform** for the Pinky Pro desk-maze robot (~11 cm; RPi, RPLidar C1, US-016, 3× IR cliff, BNO055 IMU, OV5647). D-630 puts sensing source in `sensors/sensing`, camera/OpenCV source in `front_camera/perception`, and Drive algorithm source in `../drive/{planning,tracking,recovery,calibration,safety}`. Existing import names, ROS node composition, entry points and share resources remain with this distribution. `core` owns the final external API and operational motor command path.

## Key Files
| File | Description |
|------|-------------|
| `STEPS.txt` | Korean operator runbook: bringup order, tuning log, LCD/web notes |
| `package.xml` / `setup.py` | ament_python package manifest and entry points |
| `resource/control` | ament resource marker (generated, do not edit) |
| `learned_lane_node` / `record_session` | Console scripts (D-356). `learned_lane_node` runs a delivered ONNX model on `camera/front` and publishes shadow-only `perception/learned/shadow` (launch: `launch/learned_lane.launch.py`); `record_session` records raw `camera/front` plus evidence topics into a harvest-aware session (`nodes/recording.py`) |
| `progress.md` | Current gate snapshot (SOURCE…FIELD). Overwrite; state of record over this file |
| `logs.md` | Append-only work journal, one entry per change |
| `index.md` | Generated: ADRs, plans, solutions, tests, recent logs. Do not edit |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `localization/`, `graph_health/`, `snapshots/` | D-747 location decisions/status, graph health and snapshot trigger policies with their dedicated ROS adapters; installed as existing `control.*` |
| `sensors/line_observation/`, `front_camera/object_observation/` | Line observer input validation/composition and advisory detections with their dedicated adapters; installed as existing `control.*` |
| `nodes/` | Remaining ROS, calibration/storage, recording and provider composition; existing control.* identity |
| `control/` | Thin source-import compatibility entries and thin source-import compatibility entries (see `control/AGENTS.md`) |
| `sensors/` | Sensor-evidence holder. The installed package is `sensing/` (see `sensors/AGENTS.md`) |
| `front_camera/perception/` | Camera/detector/learned evidence, installed as `control.sensing.perception` (see `front_camera/perception/AGENTS.md`) |
| `../drive/` | Existing Drive algorithms installed by this distribution under `control.control`, `control.planning`, `control.wander`, `control.safety` (see `../drive/AGENTS.md`) |
| `config/` | Shared and per-node ROS parameters (see `config/AGENTS.md`) |
| `launch/` | Launch files; bringup order matters (see `launch/AGENTS.md`) |
| `test/` | Pure-logic unittest suite, no ROS needed (see `test/AGENTS.md`) |
| `tools/` | ROS-name audit, calibration migration, Gazebo helpers (see `tools/AGENTS.md`) |
| `docs/` | Camera ground calibration, localization, narrow-passage notes, dated validation dumps (see `docs/AGENTS.md`) |
| `web/` | web_node dashboard UI — served from share/control/web (see `web/AGENTS.md`) |
| `map/` | Gazebo world asset for the desk maze (see `map/AGENTS.md`) |

### Size units (D-766)

Counted on their own in `test/architecture/size_units.txt` (unit limit 10,000 lines; the rest stays in `control`). Paths are relative to the colcon root; holders are the `control/_source_layout.py` entries named.

| Unit | Responsibility |
|------|----------------|
| `drive/tracking/wander` | `PACKAGE_DIRS` `control.wander`: the wander node's senses, judge, motion and navigator |
| `drive/planning/grid` | `PACKAGE_DIRS` `control.planning`: map check, point to go, best route, zigzag coverage |
| `perception/sensors/sensing` | `PACKAGE_DIRS` `control.sensing`: raw sensor data to robot-frame geometry |
| `drive/motion_limits` | `FLAT_ROOTS`: Drive safety limits that withhold or reduce a candidate, plus `adapter/` (`control.safety`); no final `/cmd_vel` (see its `AGENTS.md`) |
| `drive/calibration` | `FLAT_ROOTS`: stationary sensor checks and bounded calibration motion (see its `AGENTS.md`) |
| `drive/recovery` | `FLAT_ROOTS`: bounded recovery proposals (escape, trail retreat, hazard response) (see its `AGENTS.md`) |
| `perception/sensors/line_observation` | `CONTROL_ROOTS`: line observer node, input validation and composition, IR overlay, route followers |

## For AI Agents

### Working In This Directory
- Harness (D-61): read `progress.md` and `index.md` first. After a change, append `logs.md`, overwrite `progress.md` if a gate moved, then run `python tools/harness/rosy_harness.py generate` from the repo root.
- Treat this directory as part of ROSY Platform. The original checkout is archived for provenance; no runtime, build, or test may require it.
- Preserve pure-logic behavior and its tests before changing ROS wiring. The target runtime must not activate this package's legacy final `/cmd_vel` publisher beside `core`.
- Keep new **decision logic in its actual source holder** (`../drive/`, `sensors/sensing/`, `front_camera/perception/`, `localization/`, `graph_health/`, `snapshots/`, `sensors/line_observation/`, or `front_camera/object_observation/`). Decision modules stay ROS-free; dedicated adapters in the same functional holder may import ROS (D-747). Preserve the existing `control.*` identities; do not duplicate algorithms in compatibility entries.
- `config/robot.yaml` is the single shared parameter source; per-node yamls override after it.
- The lidar is mounted rotated: **scan 0° = rear, nose = 180° URDF nominal (D-397; measured 181–182°, an accepted lidar_mount record refines it)**. Every heading goes through `robot_yaw()` / `wrap_pi()`.
- Docs/STEPS.txt are Korean; code comments and logs are English. Comments explain *why* against measured hardware limits (lidar 5 cm min, US 2 cm blind zone, IR 4095 = ADC saturation, never a cliff).
- Learned loop (D-356): `learned_lane_node` is shadow-only and never publishes a command. Weights never live in `src/`; dataset, training and delivery tooling is in `learning/training/perception/`.
- Commits: short imperative behavioral summaries.
- `front_camera/perception/` is the separate P1a architecture size unit; its import remains `control.sensing.perception` and its colcon package remains `control`.

### Testing Requirements
- `python3 -m pytest test/ -q` from this package directory (`middleware/perception`); needs numpy/OpenCV. ROS graph tests require a separate isolated ROS Jazzy run.
- Keep the suite green before committing; add tests for new pure-logic decisions.

### Device flow
The Device is Raspberry Pi OS Lite 64-bit with the release installed at `/opt/rosy`. Keep the runtime stationary while installing and reading back identity and release evidence (scripts in `deploy/robot/pinky_pro/` and its `verify/`):

```bash
sudo ROSY_ROBOT_NUMBER=1 bash ./install-pi.sh
sudo ./verify-pi.sh
sudo ./runtime-mode.sh up
sudo ./device-readback.sh --json
```

- `install-pi.sh` derives `ROS_DOMAIN_ID` and `ROSY_NAMESPACE`. Do not write identity values into `.env` by hand.
- Enable `motor` or `hardware` only after the stationary core, immutable image digest, ROS graph and single-publisher checks are GO. Enable calibration and camera profiles only after the matching generation and sensor readback are retained.
- Record source/local/ROS-simulation results separately from artifact, Device and FIELD results. A host test or a successful build does not prove a Device install, sensor capture, motor motion or arm operation; ARM64 image publication, Pi readback, CSI timing, motor deadman and OMX acceptance each need their own evidence record.

### Common Patterns
- Subject mixins: each node = `rclpy.Node` + one-concern mixins (wander = Senses/Judge/Contact/Motion; safety = Bumper/Hazard/Gate/Scale).
- Legacy comparison chain: wander → raw command → safety_node → motors. The OS target owns final command selection in CORE and publication in RosBridge (D-38); do not start both final publishers.
- One fused status label (`control/modes.pick_mode`) on `/robot/mode`; `/safety/mode` is a deprecated same-value alias.

## Dependencies

### External
- ROS 2 Jazzy (`rclpy`, `std_msgs`, `geometry_msgs`, `nav_msgs`, `sensor_msgs`, `tf_transformations`), `slam_toolbox` for mapping.

<!-- MANUAL: -->
