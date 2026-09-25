<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-06 | Updated: 2026-09-24 -->

# control/ (Python package)

## Purpose
The package's Python code: executable ROS node wrappers at the top level and the pure-logic "subject" modules grouped into `control/`, `planning/`, `sensing/` subpackages plus `safety/` and `wander/` node packages. Data flow: sensor → geometry (`sensing/`) → policy (`control/`) → map goals (`planning/`).

## Key Files
| File | Description |
|------|-------------|
| `wander_node.py` | Entry wrapper — re-exports `WanderNode`/`main` from `wander/` |
| `safety_node.py` | Entry wrapper for the safety gate node |
| `calib_node.py` | Relative `calib/step` FSM; saves one explicitly configured calibration file and requests safety parameters. Bound records validate device/generation context. Parameter acknowledgement does not prove policy adoption |
| `calibration_record.py` / `calibration_storage.py` / `calibration_lock.py` | Versioned context/digest envelope, fixed runtime path, revision checks and locked atomic save; verified runtime consumer and authenticated identity source remain pending |
| `camera_detect_node.py` | OV5647 capture (BGR8, rotated 180°) through `sensing/camera_worker`, AE/AWB frozen after settle (`sensing/camera_controls`) → `camera.classify_frame` → `sensing/camera_policy` hysteresis → `/camera/blocked|side|observation|telemetry|controls`. `/camera/cliff` is always false: a monocular camera cannot separate a dark wall from a dark hole, so floor IR owns that decision |
| `control_node.py` | odom-P straight/rotate controller driven by `/goal_distance`, `/goal_rotate` |
| `goal_node.py` | Map point-to-go: `/map`+TF → `/goal_point`, `/route`; thin I/O over `planning.GoalBrain`; advisory only, never touches `/cmd_vel_raw` |
| `watch_node.py` | Graph health: required nodes, exclusive topic ownership, foreign-node detection → `/robot/ok|health|interrupt` |
| `watch.py` | Pure graph-inspect logic (ROS-free), covered by `test_watch.py` |
| `line_observer_node.py` | Normalised white-line evidence from IR reflectance or camera frames; modes include the lane-network followers (`route_a`/`route_b`/`route_ab` over `sensing/route_*`, fail-closed without `lane_graph_path`/`route`/`route_start`) and an optional `line/debug` overlay |
| `dock_observer_node.py` | Camera frames → `dock/observation` via `sensing/dock_observer`; owns no motion. Only the Gazebo camera (`camera_geometry_source` GAZEBO under `use_sim_time`) may use the declared height/pitch/hfov/offset; any other source fails closed (every frame publishes not-visible) |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `control/` | Pure motion policy + the canonical mode label (see `control/AGENTS.md`) |
| `planning/` | Occupancy-grid planning: A*, frontiers, zigzag, GoalBrain (see `planning/AGENTS.md`) |
| `safety/` | The safety gate node subjects (see `safety/AGENTS.md`) |
| `sensing/` | Raw sensor → robot-frame geometry (see `sensing/AGENTS.md`) |
| `wander/` | The wander FSM node (see `wander/AGENTS.md`) |

## For AI Agents

### Working In This Directory
- Top-level `*_node.py` files are thin entry wrappers — put logic in the subject modules, not here.
- Node files are `#!/usr/bin/env python3` executables wired in `setup.py` entry points; keep the `main()` + `rclpy.spin` + `KeyboardInterrupt`-safe shutdown shape.
- On shutdown, every node must leave motors stopped and status topics truthful (see `wander/node.py:stop_motors`).

### Testing Requirements
- Node wrappers are not unit-tested (no ROS in CI-style tests); keep their logic thin.
- Pure modules here (`watch.py`) must stay importable without ROS and tested in `test/`.

### Common Patterns
- Docstring convention: `"""Subject: <one concern>. …"""` — one subject per module/mixin.
- English comments/logs; explain *why* against hardware limits.

## Dependencies

### Internal
- `config/` (loaded via launch, `/**` wildcard first: `robot.yaml`), `launch/` bringup order: bringup+ADC → safety (+1.5 s) → wander (+3 s) → lcd/web/watch (+3.5 s).

### External
- `rclpy`, `std_msgs`, `geometry_msgs`, `nav_msgs`, `sensor_msgs`, `picamera2` (camera node), `tf_transformations`.

<!-- MANUAL: -->
