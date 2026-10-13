<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-06 | Updated: 2026-09-14 -->

# control (ROS distribution in ROSY Platform)

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-12

## Purpose
ROS 2 Jazzy `control` distribution in **ROSY Platform** for the Pinky Pro desk-maze robot (~11 cm; RPi, RPLidar C1, US-016, 3× IR cliff, BNO055 IMU, OV5647). D-630 puts sensing source in `sensors/sensing`, camera/OpenCV source in `vision/perception`, and Drive algorithm source in `../drive/{planning,tracking,recovery,calibration,safety}`. Existing import names, ROS node composition, entry points and share resources remain with this distribution. `core` owns the final external API and operational motor command path.

## Key Files
| File | Description |
|------|-------------|
| `CLAUDE.md` | Deep architecture guide (command chain, lidar trap, parameters) — read first |
| `STEPS.txt` | Korean operator runbook: bringup order, tuning log, LCD/web notes |
| `package.xml` / `setup.py` | ament_python package manifest and entry points |
| `resource/control` | ament resource marker (generated, do not edit) |
| `learned_lane_node` / `record_session` | Console scripts (D-356). `learned_lane_node` runs a delivered ONNX model on `camera/front` and publishes shadow-only `perception/learned/shadow` (launch: `launch/learned_lane.launch.py`); `record_session` records raw `camera/front` plus evidence topics into a harvest-aware session (`control/recording.py`) |
| `progress.md` | Current gate snapshot (SOURCE…FIELD). Overwrite; state of record over this file |
| `logs.md` | Append-only work journal, one entry per change |
| `index.md` | Generated: ADRs, plans, solutions, tests, recent logs. Do not edit |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `localization/`, `graph_health/`, `snapshots/` | D-747 location decisions/status, graph health and snapshot trigger policies with their dedicated ROS adapters; installed as existing `control.*` |
| `sensors/line_observation/`, `vision/object_observation/` | Line observer input validation/composition and advisory detections with their dedicated adapters; installed as existing `control.*` |
| `control/` | Existing ROS node composition and thin source-import compatibility entries (see `control/AGENTS.md`) |
| `sensors/` | Sensor-evidence holder. The installed package is `sensing/` (see `sensors/AGENTS.md`) |
| `vision/perception/` | Camera/detector/learned evidence, installed as `control.sensing.perception` (see `vision/perception/AGENTS.md`) |
| `../drive/` | Existing Drive algorithms installed by this distribution under `control.control`, `control.planning`, `control.wander`, `control.safety` (see `../drive/AGENTS.md`) |
| `config/` | Shared and per-node ROS parameters (see `config/AGENTS.md`) |
| `launch/` | Launch files; bringup order matters (see `launch/AGENTS.md`) |
| `test/` | Pure-logic unittest suite, no ROS needed (see `test/AGENTS.md`) |
| `tools/` | ROS-name audit, calibration migration, Gazebo helpers (see `tools/AGENTS.md`) |
| `docs/` | Camera ground calibration, localization, narrow-passage notes, dated validation dumps (see `docs/AGENTS.md`) |
| `web/` | web_node dashboard UI — served from share/control/web (see `web/AGENTS.md`) |
| `map/` | Gazebo world asset for the desk maze (see `map/AGENTS.md`) |

## For AI Agents

### Working In This Directory
- Harness (D-61): read `progress.md` and `index.md` first. After a change, append `logs.md`, overwrite `progress.md` if a gate moved, then run `python tools/harness/rosy_harness.py generate` from the repo root.
- Treat this directory as part of ROSY Platform. The original checkout is archived for provenance; no runtime, build, or test may require it.
- Preserve pure-logic behavior and its tests before changing ROS wiring. The target runtime must not activate this package's legacy final `/cmd_vel` publisher beside `core`.
- Keep new **decision logic in its actual pure-logic source holder** (`../drive/`, `sensors/sensing/`, `vision/perception/`, `localization/`, `graph_health/`, `snapshots/`, `sensors/line_observation/`, or `vision/object_observation/`) — no ROS imports there. Preserve the existing `control.*` identities; do not duplicate algorithms in compatibility entries.
- `config/robot.yaml` is the single shared parameter source; per-node yamls override after it.
- The lidar is mounted rotated: **scan 0° = rear, nose = 180° URDF nominal (D-397; measured 181–182°, an accepted lidar_mount record refines it)**. Every heading goes through `robot_yaw()` / `wrap_pi()`.
- Docs/STEPS.txt are Korean; code comments and logs are English. Comments explain *why* against measured hardware limits (lidar 5 cm min, US 2 cm blind zone, IR 4095 = ADC saturation, never a cliff).
- Learned loop (D-356): `learned_lane_node` is shadow-only and never publishes a command. Weights never live in `src/`; dataset, training and delivery tooling is in `learning/training/perception/`.
- Commits: short imperative behavioral summaries.
- `vision/perception/` is the separate P1a architecture size unit; its import remains `control.sensing.perception` and its colcon package remains `control`.

### Testing Requirements
- `python3 -m pytest test/ -q` from this package directory (`middleware/perception`); needs numpy/OpenCV. ROS graph tests require a separate isolated ROS Jazzy run.
- Keep the suite green before committing; add tests for new pure-logic decisions.

### Common Patterns
- Subject mixins: each node = `rclpy.Node` + one-concern mixins (wander = Senses/Judge/Contact/Motion; safety = Bumper/Hazard/Gate/Scale).
- Legacy comparison chain: wander → raw command → safety_node → motors. The OS target owns final command selection in CORE and publication in RosBridge (D-38); do not start both final publishers.
- One fused status label (`control/modes.pick_mode`) on `/robot/mode`; `/safety/mode` is a deprecated same-value alias.

## Dependencies

### External
- ROS 2 Jazzy (`rclpy`, `std_msgs`, `geometry_msgs`, `nav_msgs`, `sensor_msgs`, `tf_transformations`), `slam_toolbox` for mapping.

<!-- MANUAL: -->
